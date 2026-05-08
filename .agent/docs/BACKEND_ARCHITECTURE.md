# Backend API Architecture & Startup Guide

## Overview

The backend provides a FastAPI service bridging the SCT frontend to the PDF extraction pipeline, MCTS search engine, and financial-spreading workflow. Results are streamed to the frontend in real time via Server-Sent Events (SSE).

**Data flow**: `Frontend → selects company from dropdown (GET /api/companies) → POST /api/spread → 5× MCTSQuery (one per year) → FinancialSpreadingWorkflow → SSE stream → Frontend cells update in real time`

---

## API Endpoints

### POST /api/ingest

Ingest a PDF file into the SQLite document tree.

```
Body: { file_path, company_name, year_period }
Response: { status, doc_pk, doc_name, node_count, processing_time_seconds }
```

Steps:
1. Validates the PDF exists on disk
2. Calls `run_pdf_json_pipeline()` with `store_to_db=True`
3. Pipeline runs TOC detection → hierarchical extraction → recursive subdivision → DB insert
4. Returns doc_pk and node count

### POST /api/spread

Stream financial spreading results via SSE.

```
Body: { company_name, year_periods[], metrics[{row_index, metric_name, year[]}] }
Response: text/event-stream
```

SSE event types:

| Event | Payload | When |
|---|---|---|
| `tree_verification` | `{event, results: {FY21: {status, doc_pk, total_nodes, ...}, ...}}` | Immediately on connect |
| Metric resolved | `{canonical_name, year, row_index, value, status, formula, error, source_location, component_details}` | Per metric, per year, as resolved — component_details lists sub-metrics with their own values and source locations |
| `year_error` | `{event, year, message}` | Per year if tree missing or workflow fails |
| `complete` | `{event: "complete", workflow_id}` | After all years processed (workflow_id for history) |

### POST /api/mock/spread

Mock SSE stream for frontend testing (data source "TEST"). Same body/event format as `/api/spread` but returns random values at high speed (~1-2 seconds total).

```
Body: { company_name, year_periods[], metrics[{row_index, metric_name}] }
Response: text/event-stream  (same event types as /api/spread)
```

### GET /api/history

List past workflows, optionally filtered by company.

```
Query:  ?company_name=Unilever
Response: [{ workflow_id, company_name, data_source, year_periods, metric_count, created_at }, ...]
```

### GET /api/history/{workflow_id}

Retrieve full SCT data for a past workflow.

```
Response: { workflow_id, company_name, data_source, year_periods, sct_data: { FY21: { section: [metrics] }, ... }, created_at }
```

### GET /api/companies

List distinct company names that have been ingested into the DB.

```
Response: ["Unilever", ...]
```

Used by the frontend to populate the company dropdown instead of a free-text input.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ Frontend (sample_webpage.html)                       │
│  POST /api/spread with selected metrics              │
│  Consumes SSE via fetch() + ReadableStream           │
│  Updates cells on each metric event (flash anim)     │
└──────────────────┬──────────────────────────────────┘
                   │ SSE (text/event-stream)
                   ▼
┌─────────────────────────────────────────────────────┐
│ FastAPI (backend/main.py)                            │
│  StreamingResponse wrapping async generator          │
│  ┌─ Verification: verify_trees_for_years()           │
│  └─ Workflow thread: run_workflow()                  │
│       └─ asyncio.Queue ← bridge (thread-safe)        │
└──────────────────┬──────────────────────────────────┘
                   │ per year
                   ▼
┌─────────────────────────────────────────────────────┐
│ MCTS Search Factory (mcts_search_factory.py)         │
│  make_mcts_search_fn(company, year) → MCTSSearchFn   │
│  ┌─ MCTSQuery (per company+year forest)              │
│  └─ Numeric extraction from synthesized answer       │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│ FinancialSpreadingWorkflow                           │
│  5-phase resolution: direct → aggregations →         │
│  derived_else_direct → derived → fallback            │
│  progress_callback → SSE event per mentioned metric  │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│ SQLite DB (static/tree_poc.db)                       │
│  documents table: company, year_period, raw_json     │
│  nodes table: hierarchical tree with text_content    │
│  5 separate trees loaded per year period             │
└─────────────────────────────────────────────────────┘
```

### Thread-to-Async Bridge

The `FinancialSpreadingWorkflow` is synchronous. To stream SSE without blocking the event loop:

1. An `asyncio.Queue` is created in the async context
2. The sync workflow runs in a `threading.Thread`
3. The `progress_callback` pushes each resolved `Metric` into the queue via `asyncio.run_coroutine_threadsafe()`
4. The async generator awaits `queue.get()` and yields formatted SSE strings
5. A `None` sentinel (guarded by `try/finally`) signals completion

### Tree Verification (Pre-flight)

Before any MCTS search begins, `verify_trees_for_years()` checks all requested years:

- **Existence**: Document with matching `company` + `year_period` exists in DB
- **Node count**: ≥ 10 total nodes (avoids empty/corrupt trees)
- **Leaf text**: ≥ 3 leaf nodes with non-empty `text_content` (ensures searchability)

Results stream immediately as the first SSE event. Years with errors are skipped during the workflow run (a `year_error` event fires for each).

---

## File Map

```
backend/
├── main.py                  # FastAPI app, SSE/spread, mock, history endpoints
├── tree_verifier.py         # Pre-flight tree readiness check
├── mcts_search_factory.py   # Per-year MCTSSearchFn factory + numeric extraction
└── README_backend.md        # API reference
frontend/
└── sample_webpage.html      # SSE consumer, clickable history, TEST mock routing
tests/
├── test_backend_ingest.py   # Ingest endpoint validation
└── test_backend_spread.py   # SSE stream parsing, event order, metric serialization
ingest_unilever.sh           # Batch ingest: calls /api/ingest for 5 Unilever PDFs
```

---

## Startup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Start the backend

```bash
cd Reasoning-based_tree_search
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

The API docs are then available at `http://localhost:8000/docs` (Swagger UI).

### 3. Ingest a PDF (one per year)

```bash
curl -X POST http://localhost:8000/api/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "/absolute/path/to/Unilever-FY22.pdf",
    "company_name": "Unilever",
    "year_period": "FY22"
  }'
```

Repeat for each year (FY21–FY25). Each creates a separate document tree in the DB.

### 4. Open the frontend

Open `frontend/sample_webpage.html` directly in a browser (no web server needed — it's a single static file).

1. Enter the company name (e.g. "Unilever")
2. Select a data source
3. Check at least 2 metric rows
4. Click "Run analysis"

Cells populate in real time with a yellow-green flash animation as each metric resolves.

### 5. Run tests

```bash
python -m pytest tests/test_backend_ingest.py tests/test_backend_spread.py -v
```

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `TREE_DB_PATH` | `static/tree_poc.db` | SQLite database path |
| `METRIC_DEFINITIONS_YAML` | `metric_definitions.yaml` | Metric definitions file |
| `AZURE_OPENAI_MODEL` | `gpt-4o` | Model for PDF extraction pipeline |
