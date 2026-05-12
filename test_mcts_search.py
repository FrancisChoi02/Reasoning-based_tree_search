# Input: Query text, document identifier, SQLite DB path, and MCTS search configuration.
# Output: Runs a root-level MCTS document search smoke test (or workflow test) and
#   prints answer/source diagnostics with basic pass/fail checks.
# Position: Root-level manual smoke test runner for utils.tree_search_related.mcts_search
#   and utils.financial_spreading.financial_spreading_workflow.
#   If modified, update this header and the parent folder's .md index.

#  python test_mcts_search.py workflow \
#       --company "Unilever" \
#       --metrics "Revenue,EBITDA" \
#       --backend-url http://localhost:8000

#   For fast smoke tests (direct, no HTTP):

#   python test_mcts_search.py workflow \
#       --company "Unilever" \
#       --metrics "Revenue" --years "2021" \
#       --iterations 3


from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.mcts_search_factory import make_mcts_search_fn
from utils.database.db_manager import get_document
from utils.financial_spreading.financial_spreading_workflow import (
    FinancialSpreadingWorkflow,
    compute_yoy,
)
from utils.tree_search_related.mcts_search import MCTSQuery


# ── CLI helpers ──────────────────────────────────────────────────────────


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError("value must be greater than or equal to 0")
    return parsed


# ── Argument parsing ─────────────────────────────────────────────────────


def _add_mcts_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db-path",
        default="verify_test.db",
        help="SQLite database path",
    )
    parser.add_argument(
        "--doc-pk",
        type=_positive_int,
        help="Document primary key to search",
    )
    parser.add_argument(
        "--doc-name",
        help="Document name to search when doc_pk is not provided",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Question to ask against the document tree",
    )
    parser.add_argument(
        "--iterations",
        type=_positive_int,
        default=10,
        help="Number of MCTS iterations",
    )
    parser.add_argument(
        "--top-k",
        type=_positive_int,
        default=3,
        help="Number of top leaves to use for synthesis",
    )
    parser.add_argument(
        "--max-workers",
        type=_positive_int,
        default=4,
        help="Maximum number of concurrent workers for same-frontier leaf evaluation",
    )
    parser.add_argument(
        "--exploration-weight",
        type=_non_negative_float,
        default=1.414,
        help="UCB1 exploration weight",
    )
    parser.add_argument(
        "--max-eval-chars",
        type=_positive_int,
        default=3000,
        help="Maximum total characters used when scoring a leaf",
    )
    parser.add_argument(
        "--virtual-visits",
        type=_positive_int,
        default=3,
        help="Virtual visits used for prior seeding",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra result details",
    )


def _add_workflow_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--company",
        required=True,
        help="Company name (e.g. 'Unilever')",
    )
    parser.add_argument(
        "--years",
        default="2021,2022,2023,2024,2025",
        help="Comma-separated year periods (default: 2021,2022,2023,2024,2025)",
    )
    parser.add_argument(
        "--metrics",
        help="Comma-separated canonical metric names for partial resolution (omit for full table)",
    )
    parser.add_argument(
        "--full-table",
        action="store_true",
        help="Force full SCT table resolution even when --metrics is provided",
    )
    parser.add_argument(
        "--yaml-path",
        default="metric_definitions.yaml",
        help="Path to metric_definitions.yaml",
    )
    parser.add_argument(
        "--db-path",
        default="static/tree_poc.db",
        help="SQLite database path",
    )
    parser.add_argument(
        "--max-workers",
        type=_positive_int,
        default=3,
        help="MCTS max_workers for individual metric searches",
    )
    parser.add_argument(
        "--iterations",
        type=_positive_int,
        default=10,
        help="Number of MCTS iterations per search",
    )
    parser.add_argument(
        "--backend-url",
        default=None,
        help="Send request to a running backend at this URL (e.g. http://localhost:8000) "
             "instead of running the workflow directly in-process",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed MCTS search progress (forest stats, seeding, per-batch timing)",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MCTS search smoke test or financial spreading workflow test"
    )
    sub = parser.add_subparsers(dest="mode", help="Test mode")

    # -- mode mcts
    mcts_parser = sub.add_parser("mcts", help="Single-query MCTS search smoke test")
    _add_mcts_args(mcts_parser)

    # -- mode workflow
    wf_parser = sub.add_parser("workflow", help="Financial spreading workflow test")
    _add_workflow_args(wf_parser)

    return parser.parse_args()


# ── Document resolution ──────────────────────────────────────────────────


def resolve_doc_pk(*, db_path: str, doc_pk: Optional[int], doc_name: Optional[str]) -> int:
    if doc_pk is not None:
        get_document(doc_pk, db_path=db_path)
        return doc_pk

    if not doc_name:
        raise ValueError("Either --doc-pk or --doc-name must be provided")

    document = get_document(doc_name, db_path=db_path)
    return int(document["doc_pk"])


# ── MCTS mode ────────────────────────────────────────────────────────────


def run_mcts_mode(args: argparse.Namespace) -> int:
    try:
        doc_pk = resolve_doc_pk(
            db_path=args.db_path,
            doc_pk=args.doc_pk,
            doc_name=args.doc_name,
        )
    except Exception as exc:
        print(f"[FAIL] Document lookup failed: {exc}")
        return 1

    searcher = MCTSQuery(
        doc_pk=doc_pk,
        db_path=args.db_path,
        num_iterations=args.iterations,
        top_k=args.top_k,
        exploration_weight=args.exploration_weight,
        max_eval_chars=args.max_eval_chars,
        max_workers=args.max_workers,
        virtual_visits=args.virtual_visits,
        verbose=args.verbose,
    )

    print("=== MCTS Search Smoke Test ===")
    print(f"db_path: {args.db_path}")
    print(f"doc_pk: {doc_pk}")
    print(f"iterations: {args.iterations}")
    print(f"top_k: {args.top_k}")
    print(f"max_workers: {args.max_workers}")
    print(f"query: {args.query}")

    started_at = time.perf_counter()
    try:
        result = searcher.search(args.query)
    except Exception as exc:
        print(f"[FAIL] MCTS search crashed: {exc}")
        return 1
    elapsed_seconds = time.perf_counter() - started_at

    answer = (result.get("answer") or "").strip()
    sources = result.get("sources") or []
    visited_leaf_count = int(result.get("visited_leaf_count") or 0)
    iterations = int(result.get("iterations") or 0)

    print("\n=== Answer ===")
    print(answer)

    print("\n=== Sources ===")
    for index, source in enumerate(sources, start=1):
        print(
            f"[{index}] title={source.get('title')!r} "
            f"pages={source.get('pages')} score={source.get('score')} "
            f"visits={source.get('visits')} path={source.get('path')}"
        )

    print("\n=== Summary ===")
    print(f"elapsed_seconds: {elapsed_seconds:.3f}")
    print(f"iterations: {iterations}")
    print(f"visited_leaf_count: {visited_leaf_count}")
    print(f"source_count: {len(sources)}")

    if args.verbose:
        print("\n=== Full Result ===")
        print(result)

    errors = []
    if not answer:
        errors.append("Answer is empty")
    if iterations != args.iterations:
        errors.append(
            f"Iteration mismatch: expected {args.iterations}, got {iterations}"
        )
    if visited_leaf_count <= 0:
        errors.append("No leaves were visited")
    if not sources:
        errors.append("No sources returned")

    if errors:
        print("\n=== Errors ===")
        for error in errors:
            print(f"- {error}")
        print("\n[FAIL] MCTS search smoke test failed.")
        return 1

    print("\n[PASS] MCTS search smoke test passed.")
    return 0


# ── Workflow mode (HTTP backend) ─────────────────────────────────────────


def _consume_sse_stream(response: urllib.request.http.client.HTTPResponse) -> list[dict]:
    """Read an SSE stream line-by-line and return parsed event dicts."""
    events: list[dict] = []
    data_buffer = ""
    for line_bytes in response:
        line = line_bytes.decode("utf-8").rstrip("\n").rstrip("\r")
        if line.startswith("data: "):
            data_buffer += line[6:]
        elif line == "" and data_buffer:
            try:
                events.append(json.loads(data_buffer))
            except json.JSONDecodeError:
                pass
            data_buffer = ""
    if data_buffer:
        try:
            events.append(json.loads(data_buffer))
        except json.JSONDecodeError:
            pass
    return events


def _print_metric_event(evt: dict, tag: str) -> None:
    """Print a single metric SSE event with full detail (matching test_sse_stream.py output)."""
    name = evt.get("canonical_name", "?")
    year = evt.get("year", "?")
    ri = evt.get("row_index")
    value = evt.get("value")
    formula = evt.get("formula")
    error = evt.get("error")
    src = evt.get("source_location")
    comps = evt.get("component_details")

    if tag == "RESOLVED" and value is not None:
        print(f"[{tag}] row={ri}  {name}  year={year}  value={value}")
    elif tag == "UNRESOLVED":
        print(f"[{tag}] row={ri}  {name}  year={year}  error={error}")
    else:
        vstr = f"{value:,.2f}" if isinstance(value, (int, float)) else str(value)
        print(f"[{tag}] row={ri}  {name}  year={year}  value={vstr}")

    if formula:
        print(f"           formula={formula}")
    if src:
        print(f"           source_location={src}")
    if comps:
        for cd in comps:
            sv = cd.get("value")
            sv_str = f"{sv:,.2f}" if isinstance(sv, (int, float)) else str(sv)
            print(f"           component: {cd.get('component_name')} = {sv_str}  ({cd.get('source_location', '')})")


def run_workflow_via_http(args: argparse.Namespace) -> int:
    """Send a POST to the backend /api/spread endpoint and display the SSE stream."""
    import urllib.request

    years = [y.strip() for y in args.years.split(",") if y.strip()]
    metrics = None
    if args.metrics:
        metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]

    is_full_table = args.full_table or (metrics is None)
    if not is_full_table:
        metric_items = [
            {"row_index": i, "metric_name": m}
            for i, m in enumerate(metrics)
        ]
    else:
        metric_items = [
            {"row_index": 0, "metric_name": "ALL"},
        ]

    payload = json.dumps({
        "company_name": args.company,
        "year_periods": years,
        "metrics": metric_items,
        "data_source": "Internal Model",
    }).encode("utf-8")

    url = f"{args.backend_url.rstrip('/')}/api/spread"

    print(f"Connecting to: {url}")
    print(f"Company: {args.company}")
    print(f"Years: {years}")
    print(f"Metrics ({len(metric_items)}): {[m['metric_name'] for m in metric_items]}")
    print("-" * 60)

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    overall_started = time.perf_counter()
    event_count = 0
    resolved_count = 0
    unresolved_count = 0
    row_index_issues: list[str] = []

    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            data_buffer = ""
            for line_bytes in response:
                line = line_bytes.decode("utf-8").rstrip("\n").rstrip("\r")
                if line.startswith("data: "):
                    data_buffer += line[6:]
                elif line == "" and data_buffer:
                    try:
                        evt = json.loads(data_buffer)
                    except json.JSONDecodeError:
                        data_buffer = ""
                        continue
                    data_buffer = ""

                    event_count += 1
                    event_type = evt.get("event", "")

                    # System events
                    if event_type == "tree_verification":
                        for yr, r in (evt.get("results") or {}).items():
                            status = r.get("status", "?")
                            print(f"[VERIFY] {yr}: {status}  nodes={r.get('total_nodes','?')}  leaves_with_text={r.get('leaves_with_text','?')}")
                            if r.get("issues"):
                                for issue in r["issues"]:
                                    print(f"         issue: {issue}")
                        continue

                    if event_type == "year_error":
                        print(f"[YEAR ERROR] {evt.get('year')}: {evt.get('message')}")
                        continue

                    if event_type == "complete":
                        wid = evt.get("workflow_id")
                        print(f"[COMPLETE] workflow_id={wid}")
                        continue

                    # Metric / YoY events
                    if event_type in ("metric", "yoy"):
                        name = evt.get("canonical_name", "?")
                        year = evt.get("year", "?")
                        ri = evt.get("row_index")
                        status = evt.get("status", "?")
                        value = evt.get("value")
                        formula = evt.get("formula")
                        error = evt.get("error")
                        src = evt.get("source_location")
                        comps = evt.get("component_details")

                        if status == "resolved":
                            resolved_count += 1
                            tag = "RESOLVED"
                        elif status == "unresolved":
                            unresolved_count += 1
                            tag = "UNRESOLVED"
                        else:
                            tag = status.upper()

                        _print_metric_event(evt, tag)

                        if ri is None:
                            row_index_issues.append(
                                f"{name} (year={year}) — row_index is None, frontend will ignore this event"
                            )

                # end data_buffer processing

            # Process trailing buffer
            if data_buffer:
                try:
                    evt = json.loads(data_buffer)
                    if evt.get("event") == "complete":
                        print(f"[COMPLETE] workflow_id={evt.get('workflow_id')}")
                except json.JSONDecodeError:
                    pass

    except urllib.error.URLError as exc:
        print(f"\nERROR: Cannot connect to backend at {args.backend_url}")
        print(f"  {exc}")
        print(f"  Is the backend running? Try: uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload")
        return 1
    except Exception as exc:
        print(f"\nERROR: {exc}")
        return 1

    overall_elapsed = time.perf_counter() - overall_started
    print("-" * 60)
    print(f"Total events: {event_count}")
    print(f"  Resolved:   {resolved_count}")
    print(f"  Unresolved: {unresolved_count}")
    print(f"  Without row_index: {len(row_index_issues)}")
    if row_index_issues:
        for issue in row_index_issues:
            print(f"    WARNING: {issue}")
    print(f"Elapsed: {overall_elapsed:.2f}s")

    if resolved_count == 0:
        print("\n[FAIL] No metrics were resolved.")
        return 1

    print("\n[PASS] Financial spreading workflow test (HTTP) passed.")
    return 0


# ── Workflow mode (direct / in-process) ──────────────────────────────────


def _print_sct_table(sct: dict[str, list], year: str) -> None:
    """Pretty-print a single-year SCT table."""
    print(f"\n{'─' * 80}")
    print(f"  Year: {year}")
    print(f"{'─' * 80}")

    for section, metrics in sct.items():
        print(f"\n  [{section}]")
        for m in metrics:
            value_str = f"{m.value:,.2f}" if m.value is not None else "N/A"
            print(
                f"    {m.canonical_name:<45} {value_str:>20}  [{m.status}]"
            )


def _build_search_fn_for_year(
    company: str,
    year: str,
    db_path: str,
    per_call_instance: bool,
    max_workers: int,
    iterations: int,
    verbose: bool = False,
):
    return make_mcts_search_fn(
        company=company,
        year_period=year,
        db_path=db_path,
        per_call_instance=per_call_instance,
        max_workers=max_workers,
        num_iterations=iterations,
        verbose=verbose,
    )


def run_workflow_direct(args: argparse.Namespace) -> int:
    years = [y.strip() for y in args.years.split(",") if y.strip()]
    if not years:
        print("[FAIL] At least one year must be specified")
        return 1

    metrics = None
    if args.metrics:
        metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]

    is_full_table = args.full_table or (metrics is None)

    print("=== Financial Spreading Workflow Test (direct) ===")
    print(f"company: {args.company}")
    print(f"years: {years}")
    print(f"mode: {'full SCT' if is_full_table else 'partial'}")
    if not is_full_table:
        print(f"requested metrics: {metrics}")
    print(f"yaml_path: {args.yaml_path}")
    print(f"db_path: {args.db_path}")
    print(f"mcts max_workers: {args.max_workers}")
    print(f"mcts iterations: {args.iterations}")
    print(f"Note: Expect ~10-30s per MCTS metric search. {len(years)} year(s) "
          f"× N metrics × ~{(args.iterations * 1.5):.0f}s ≈ several minutes.")
    print()

    overall_started = time.perf_counter()

    # ── Cross-year concurrent execution ──────────────────────────────
    sct_by_year: dict[str, dict] = {}
    sct_lock = threading.Lock()
    progress_lock = threading.Lock()

    def resolve_year(year: str) -> tuple[str, dict]:
        year_start = time.perf_counter()
        resolved_in_year: list[str] = []

        def on_metric(m):
            tag = "RESOLVED" if m.status == "resolved" else m.status.upper()
            with progress_lock:
                if m.status == "resolved":
                    resolved_in_year.append(m.canonical_name)
                print(f"[{tag}] {m.canonical_name}  year={year}  value={m.value}")
                if m.formula_used:
                    print(f"         formula={m.formula_used}")
                if m.additional_context:
                    if m.status == "unresolved" and m.additional_context.status_note:
                        print(f"         error={m.additional_context.status_note}")
                    if m.additional_context.component_details:
                        for cd in m.additional_context.component_details:
                            sv = f"{cd.value:,.2f}" if isinstance(cd.value, (int, float)) else str(cd.value)
                            print(f"         component: {cd.component_name} = {sv}  ({cd.source_location or ''})")

        search_fn = _build_search_fn_for_year(
            company=args.company,
            year=year,
            db_path=args.db_path,
            per_call_instance=not is_full_table,
            max_workers=args.max_workers,
            iterations=args.iterations,
            verbose=args.verbose,
        )

        workflow = FinancialSpreadingWorkflow(
            yaml_path=args.yaml_path,
            mcts_search=search_fn,
            progress_callback=on_metric,
        )

        if is_full_table:
            sct = workflow.run()
        else:
            sct = workflow.run_partial(metrics)

        year_elapsed = time.perf_counter() - year_start
        with progress_lock:
            print(
                f"  [{year}] resolved {len(resolved_in_year)}/{len(workflow.resolved_metrics)} "
                f"metrics in {year_elapsed:.2f}s"
            )
        return year, sct

    with ThreadPoolExecutor(max_workers=len(years)) as executor:
        futures = {executor.submit(resolve_year, y): y for y in years}
        for future in as_completed(futures):
            year = futures[future]
            try:
                y, sct = future.result()
                with sct_lock:
                    sct_by_year[y] = sct
            except Exception as exc:
                print(f"  [{year}] ERROR: {exc}")

    overall_elapsed = time.perf_counter() - overall_started

    # ── Print results ───────────────────────────────────────────────
    for year in years:
        if year in sct_by_year:
            _print_sct_table(sct_by_year[year], year)

    # ── YoY summary ─────────────────────────────────────────────────
    if len(sct_by_year) >= 2:
        sorted_years = sorted(sct_by_year.keys())
        yoy_events = compute_yoy(sct_by_year, sorted_years)
        if yoy_events:
            print(f"\n{'─' * 80}")
            print("  Year-over-Year (% change)")
            print(f"{'─' * 80}")
            by_metric: dict[str, dict[str, float | None]] = {}
            for evt in yoy_events:
                by_metric.setdefault(evt["canonical_name"], {})[evt["year"]] = evt["value"]

            for name, period_values in sorted(by_metric.items()):
                parts = " | ".join(
                    f"{p}: {v:>8.1f}%" if v is not None else f"{p}: {'N/A':>8}"
                    for p, v in sorted(period_values.items())
                )
                print(f"  {name:<45} {parts}")

    # ── Summary ─────────────────────────────────────────────────────
    total_resolved = 0
    total_metrics = 0
    for sct in sct_by_year.values():
        for section_metrics in sct.values():
            for m in section_metrics:
                total_metrics += 1
                if m.status == "resolved":
                    total_resolved += 1

    print(f"\n{'═' * 80}")
    print(f"  Total elapsed: {overall_elapsed:.2f}s")
    print(f"  Years completed: {len(sct_by_year)}/{len(years)}")
    print(f"  Total metrics: {total_metrics}")
    print(f"  Resolved: {total_resolved}")
    print(f"  Unresolved: {total_metrics - total_resolved}")
    print(f"{'═' * 80}")

    if len(sct_by_year) < len(years):
        print("\n[FAIL] Not all years completed.")
        return 1
    if total_resolved == 0:
        print("\n[FAIL] No metrics were resolved.")
        return 1

    print("\n[PASS] Financial spreading workflow test (direct) passed.")
    return 0


# ── Main ─────────────────────────────────────────────────────────────────


MAIN_HELP = """
Sample commands
───────────────
  # Full SCT table via direct pipeline (no HTTP server needed)
  python test_mcts_search.py workflow \\
      --company "Unilever" \\
      --full-table \\
      --db-path static/tree_poc.db

  # Full SCT table with verbose MCTS search logging
  python test_mcts_search.py workflow \\
      --company "Unilever" \\
      --full-table \\
      --db-path static/tree_poc.db \\
      --verbose

  # Partial metrics via HTTP backend (hits localhost:8000)
  python test_mcts_search.py workflow \\
      --company "Unilever" \\
      --metrics "Revenue,EBITDA" \\
      --backend-url http://localhost:8000

  # Partial metrics via direct pipeline (in-process, no HTTP)
  python test_mcts_search.py workflow \\
      --company "Unilever" \\
      --metrics "Revenue,EBITDA,Gross Profit" \\
      --db-path static/tree_poc.db

  # Partial with custom year range
  python test_mcts_search.py workflow \\
      --company "Unilever" \\
      --metrics "Revenue,Net Profit" \\
      --years "2023,2024,2025" \\
      --db-path static/tree_poc.db

  # Short MCTS iterations for faster direct-mode smoke tests
  python test_mcts_search.py workflow \\
      --company "Unilever" \\
      --metrics "Revenue" --years "2021" \\
      --iterations 3 \\
      --verbose

  # Original MCTS mode (unchanged)
  python test_mcts_search.py mcts \\
      --db-path verify_test.db --doc-pk 1 \\
      --query "What was Unilever's revenue in 2022?" \\
      --iterations 10
"""


def main() -> int:
    args = parse_args()

    if args.mode == "workflow":
        if args.backend_url:
            return run_workflow_via_http(args)
        return run_workflow_direct(args)

    if args.mode == "mcts":
        return run_mcts_mode(args)

    # No mode specified — print help
    print(MAIN_HELP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
