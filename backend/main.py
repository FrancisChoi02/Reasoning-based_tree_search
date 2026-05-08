# Input: HTTP requests from the SCT frontend, metric_definitions.yaml, SQLite DB
# Output: FastAPI application with SSE streaming — /api/ingest and /api/spread
# Position: Backend service layer bridging the frontend to the financial-spreading
#   pipeline and MCTS engine. If modified, update this header and README_backend.md.

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.mcts_search_factory import make_mcts_search_fn
from backend.tree_verifier import verify_trees_for_years
from utils.database.db_manager import (
    get_workflow,
    init_db,
    list_companies,
    list_workflows,
    save_workflow,
)
from utils.financial_spreading.financial_spreading_workflow import (
    FinancialSpreadingWorkflow,
    compute_yoy,
)
from utils.tree_search_related.pdf_json_pipeline import run_pdf_json_pipeline

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="Financial Spreading SCT Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.getenv("TREE_DB_PATH", "static/tree_poc.db")
YAML_PATH = os.getenv("METRIC_DEFINITIONS_YAML", "metric_definitions.yaml")
DEFAULT_MODEL = os.getenv("AZURE_OPENAI_MODEL", "gpt-4o")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    file_path: str = Field(..., description="Absolute path to the PDF file")
    company_name: str = Field(..., description="Company name for DB storage")
    year_period: str = Field(..., description="Fiscal year period, e.g. FY22")


class SpreadMetricItem(BaseModel):
    row_index: int = Field(..., description="Row index in the frontend SCT table")
    metric_name: str = Field(..., description="Display name of the metric")


class SpreadRequest(BaseModel):
    company_name: str = Field(..., description="Company to query across all years")
    year_periods: list[str] = Field(
        ..., min_length=1, description="Fiscal years to resolve, e.g. ['2021','2022','2023','2024','2025']"
    )
    metrics: list[SpreadMetricItem] = Field(
        ..., min_length=2, description="Metrics selected from the frontend SCT table"
    )
    data_source: str = Field(default="Internal Model", description="Selected data source name")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_frontend_to_canonical_map() -> dict[str, str]:
    """Build a mapping from frontend metric display names to YAML canonical names."""
    with open(YAML_PATH, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    mapping: dict[str, str] = {}
    for metric_data in raw.get("metrics", []):
        canonical = metric_data["canonical_name"]
        mapping[_normalize(canonical)] = canonical
        for syn in metric_data.get("synonyms", []):
            mapping[_normalize(syn)] = canonical

    for agg_name in raw.get("aggregations", {}):
        mapping[_normalize(agg_name)] = agg_name
        for syn in raw.get("aggregations", {}).get(agg_name, {}).get("synonyms", []):
            mapping[_normalize(syn)] = agg_name

    return mapping


def _normalize(name: str) -> str:
    """Normalize a metric name for fuzzy matching: lowercase, strip punctuation suffixes."""
    cleaned = name.strip().lower()
    cleaned = cleaned.replace("(loss)", "").replace("(x)", "").strip()
    return cleaned


def _resolve_canonical_name(frontend_name: str, mapping: dict[str, str]) -> str | None:
    """Map a frontend metric name to its YAML canonical name."""
    direct = mapping.get(_normalize(frontend_name))
    if direct:
        return direct
    # Try without trailing parenthetical (e.g. "Ext. Gearing (TFD/TNW) (x)")
    base = _normalize(frontend_name.split("(")[0])
    return mapping.get(base)


def _serialize_sct(sct: dict[str, list]) -> dict[str, list[dict[str, Any]]]:
    """Convert a raw SCT table (Metric objects) to serializable dicts for DB storage."""
    serialized: dict[str, list[dict[str, Any]]] = {}
    for section, metrics_list in sct.items():
        serialized[section] = []
        for m in metrics_list:
            serialized[section].append({
                "canonical_name": m.canonical_name,
                "value": m.value,
                "status": m.status,
                "resolution_method": m.resolution_method,
                "formula_used": m.formula_used,
                "display_value": m.display_value,
                "error": m.additional_context.status_note if m.additional_context and m.status == "unresolved" else None,
                "source_location": (
                    m.additional_context.component_details[0].source_location
                    if m.additional_context and m.additional_context.component_details
                    else ""
                ),
                "component_details": [
                    {
                        "component_name": cd.component_name,
                        "value": cd.value,
                        "source_location": cd.source_location,
                    }
                    for cd in m.additional_context.component_details
                ] if m.additional_context and m.additional_context.component_details else [],
            })
    return serialized


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/ingest")
async def tree_file_ingest(request: IngestRequest) -> dict[str, Any]:
    """Ingest a PDF file: extract tree structure and store in SQLite."""
    pdf_path = Path(request.file_path)
    if not pdf_path.is_file():
        raise HTTPException(status_code=400, detail=f"PDF file not found: {request.file_path}")

    _ensure_db()
    try:
        result = run_pdf_json_pipeline(
            pdf_path=str(pdf_path),
            model=DEFAULT_MODEL,
            company=request.company_name,
            year_period=request.year_period,
            store_to_db=True,
            db_path=DB_PATH,
            persist=False,
            add_summary=True,
            verbose=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {exc}") from exc

    return {
        "status": "ok",
        "doc_pk": result.get("db_doc_pk"),
        "doc_name": result.get("pdf_name"),
        "node_count": result.get("db_node_count"),
        "processing_time_seconds": result.get("processing_time_seconds"),
    }


@app.post("/api/spread")
async def financial_spreading_for_SCT_table(request: SpreadRequest) -> StreamingResponse:
    """Run financial spreading across multiple years with SSE streaming.

    Each resolved metric is streamed as an SSE event so the frontend can update
    cells in real time.  The first event reports tree verification status; the
    last event signals completion.
    """
    _ensure_db()

    name_map = _load_frontend_to_canonical_map()
    year_periods = request.year_periods

    # Verify trees before kicking off the search
    verification = verify_trees_for_years(
        company=request.company_name,
        year_periods=year_periods,
        db_path=DB_PATH,
    )

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    workflow_id = None
    accumulated_sct: dict[str, Any] = {}

    def on_metric_resolved(metric, year: str):
        mapped_index = _lookup_row_index(metric.canonical_name, request.metrics, name_map)
        event = metric.as_sse_event(row_index=mapped_index, year=year)
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    def run_workflow():
        nonlocal workflow_id, accumulated_sct

        # Determine if this is a full-table or partial-metric request
        with open(YAML_PATH, encoding="utf-8") as fh:
            raw_yaml = yaml.safe_load(fh)
        all_mentioned: set[str] = {
            m["canonical_name"] for m in raw_yaml.get("metrics", [])
            if m.get("is_mentioned")
        }
        selected_canonical: set[str] = set()
        for item in request.metrics:
            canonical = _resolve_canonical_name(item.metric_name, name_map)
            if canonical:
                selected_canonical.add(canonical)
        is_full_table = selected_canonical == all_mentioned

        raw_sct_by_year: dict[str, dict[str, list]] = {}
        raw_sct_lock = threading.Lock()

        valid_years = [
            y for y in year_periods
            if verification.get(y, {}).get("status") != "error"
        ]

        # Emit errors for years with no tree
        for year in year_periods:
            if year not in valid_years:
                error_event = (
                    f"data: {json.dumps({'event': 'year_error', 'year': year, 'message': 'Tree not available for this year'})}\n\n"
                )
                asyncio.run_coroutine_threadsafe(queue.put(error_event), loop)

        if not valid_years:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)
            return

        def resolve_year(year: str):
            """Resolve a single year — runs in its own thread."""
            search_fn = make_mcts_search_fn(
                company=request.company_name,
                year_period=year,
                db_path=DB_PATH,
                per_call_instance=not is_full_table,
            )
            workflow = FinancialSpreadingWorkflow(
                yaml_path=YAML_PATH,
                mcts_search=search_fn,
                progress_callback=lambda m, y=year: on_metric_resolved(m, y),
            )
            if is_full_table:
                sct = workflow.run()
            else:
                sct = workflow.run_partial(list(selected_canonical))
            return year, sct

        try:
            # Cross-year concurrent resolution
            with ThreadPoolExecutor(max_workers=len(valid_years)) as executor:
                futures = {
                    executor.submit(resolve_year, year): year
                    for year in valid_years
                }
                for future in as_completed(futures):
                    year = futures[future]
                    try:
                        resolved_year, sct = future.result()
                        with raw_sct_lock:
                            raw_sct_by_year[resolved_year] = sct
                    except Exception as exc:
                        error_event = (
                            f"data: {json.dumps({'event': 'year_error', 'year': year, 'message': str(exc)})}\n\n"
                        )
                        asyncio.run_coroutine_threadsafe(queue.put(error_event), loop)

            # YoY computation after all years complete
            if len(raw_sct_by_year) >= 2:
                sorted_years = sorted(raw_sct_by_year.keys())
                yoy_events = compute_yoy(raw_sct_by_year, sorted_years)
                for yoy_event in yoy_events:
                    mapped_index = _lookup_row_index(
                        yoy_event["canonical_name"], request.metrics, name_map
                    )
                    yoy_event["row_index"] = mapped_index
                    asyncio.run_coroutine_threadsafe(
                        queue.put(f"data: {json.dumps(yoy_event, ensure_ascii=False)}\n\n"),
                        loop,
                    )

            # Serialize for DB storage
            for year, sct in raw_sct_by_year.items():
                accumulated_sct[year] = _serialize_sct(sct)

            # Persist workflow to DB for history
            if accumulated_sct:
                workflow_id = save_workflow(
                    company_name=request.company_name,
                    data_source=request.data_source,
                    year_periods=year_periods,
                    sct_data=accumulated_sct,
                    db_path=DB_PATH,
                )
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    async def event_generator():
        # 1. Tree verification event
        yield f"data: {json.dumps({'event': 'tree_verification', 'results': verification})}\n\n"

        # 2. Start workflow in background thread
        thread = threading.Thread(target=run_workflow, daemon=True)
        thread.start()

        # 3. Stream metric events as they arrive
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

        # 4. Completion event (includes workflow_id for history lookup)
        complete_payload: dict[str, Any] = {"event": "complete"}
        if workflow_id is not None:
            complete_payload["workflow_id"] = workflow_id
        yield f"data: {json.dumps(complete_payload)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# History endpoints
# ---------------------------------------------------------------------------

@app.get("/api/history")
async def get_history(company_name: str | None = None) -> list[dict[str, Any]]:
    """List all past workflow runs, optionally filtered by company."""
    _ensure_db()
    return list_workflows(company_name=company_name, db_path=DB_PATH)


@app.get("/api/history/{workflow_id}")
async def get_workflow_by_id(workflow_id: int) -> dict[str, Any]:
    """Retrieve the full SCT data for a past workflow run."""
    _ensure_db()
    try:
        return get_workflow(workflow_id, db_path=DB_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/companies")
async def get_companies() -> list[str]:
    """Return distinct company names that have been ingested into the DB."""
    _ensure_db()
    return list_companies(db_path=DB_PATH)


# ---------------------------------------------------------------------------
# Mock SSE endpoint (for data source "TEST")
# ---------------------------------------------------------------------------

class MockSpreadRequest(BaseModel):
    company_name: str = "TestCo"
    year_periods: list[str] = Field(default=["2021", "2022", "2023", "2024", "2025"])
    metrics: list[SpreadMetricItem] = Field(..., min_length=2)
    data_source: str = "TEST"


@app.post("/api/mock/spread")
async def mock_spread(request: MockSpreadRequest) -> StreamingResponse:
    """Stream mock SSE events simulating real-time metric calculation at high speed."""

    async def event_generator():
        # 1. Tree verification (all OK for mock)
        yield f"data: {json.dumps({'event': 'tree_verification', 'results': {yr: {'status': 'ok', 'doc_pk': 0, 'total_nodes': 99, 'total_leaves': 40, 'leaves_with_text': 35, 'issues': []} for yr in request.year_periods}})}\n\n"

        # Generate mock values for each metric across all years (base + slight year drift)
        for item in request.metrics:
            mock_base = random.uniform(500, 50000)
            for year in request.year_periods:
                # Simulate year-over-year growth of ~5-15%
                year_idx = request.year_periods.index(year)
                growth = 1.0 + year_idx * random.uniform(0.03, 0.12)
                mock_val = round(mock_base * growth, 2)

                is_success = random.random() > 0.12  # 88% success
                if is_success:
                    payload = {
                        "canonical_name": item.metric_name,
                        "year": year,
                        "row_index": item.row_index,
                        "value": mock_val,
                        "status": "resolved",
                        "formula": f"[Mock] {item.metric_name}_base * growth_factor",
                        "error": None,
                        "source_location": "Mock Data, pp. 1-99",
                        "component_details": [
                            {
                                "component_name": f"{item.metric_name} (primary)",
                                "value": round(mock_val * 0.65, 2),
                                "source_location": "Mock Data, pp. 1-50",
                            },
                            {
                                "component_name": f"{item.metric_name} (secondary)",
                                "value": round(mock_val * 0.35, 2),
                                "source_location": "Mock Data, pp. 51-99",
                            },
                        ],
                    }
                else:
                    payload = {
                        "canonical_name": item.metric_name,
                        "year": year,
                        "row_index": item.row_index,
                        "value": None,
                        "status": "unresolved",
                        "formula": None,
                        "error": "Simulated data gap.",
                        "source_location": None,
                        "component_details": None,
                    }
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(random.uniform(0.02, 0.08))

            # YoY: compute from mock FY24 and FY25
            fy24_val = round(mock_base * (1.0 + 3 * random.uniform(0.03, 0.10)), 2)
            fy25_val = round(mock_base * (1.0 + 4 * random.uniform(0.03, 0.12)), 2)
            if fy24_val and fy24_val != 0:
                yoy_pct = round((fy25_val - fy24_val) / abs(fy24_val) * 100, 2)
            else:
                yoy_pct = 0.0

            yoy_payload = {
                "canonical_name": item.metric_name,
                "year": "YoY",
                "row_index": item.row_index,
                "value": yoy_pct,
                "status": "resolved",
                "formula": "(FY25 - FY24) / |FY24| * 100",
                "error": None,
                "source_location": None,
                "component_details": [
                    {
                        "component_name": "FY25 value",
                        "value": fy25_val,
                        "source_location": "Mock Data, pp. 1-99",
                    },
                    {
                        "component_name": "FY24 value",
                        "value": fy24_val,
                        "source_location": "Mock Data, pp. 1-99",
                    },
                ],
            }
            yield f"data: {json.dumps(yoy_payload)}\n\n"

        # 2. Complete
        yield f"data: {json.dumps({'event': 'complete'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Helpers (continued)
# ---------------------------------------------------------------------------

def _lookup_row_index(
    canonical_name: str,
    requested_metrics: list[SpreadMetricItem],
    name_map: dict[str, str],
) -> int | None:
    """Find the frontend row_index for a resolved canonical metric name."""
    canonical_lower = canonical_name.lower().strip()
    for item in requested_metrics:
        mapped = _resolve_canonical_name(item.metric_name, name_map)
        if mapped and mapped.lower().strip() == canonical_lower:
            return item.row_index
        if item.metric_name.lower().strip() == canonical_lower:
            return item.row_index
    return None


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def _ensure_db() -> None:
    """Initialize the database if it does not exist."""
    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    init_db(DB_PATH)
