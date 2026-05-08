"""Test script: connect to /api/spread SSE endpoint and print all events.

Usage:
    # Test real endpoint
    python test_sse_stream.py --company "Unilever"

    # Test mock endpoint
    python test_sse_stream.py --company "TEST (Mock)" --mock

    # Custom backend URL
    python test_sse_stream.py --company "Unilever" --url http://localhost:8000



    # Full SCT table (cross-year concurrent, sequential within-year)                               
  python test_mcts_search.py workflow \                                                          
      --company "Unilever" \                                                                     
      --full-table \                                                                             
      --db-path static/tree_poc.db                                                               
                                                                                                 
  # Partial metrics with concurrent within-year + cross-year                                     
  python test_mcts_search.py workflow \                                                          
      --company "Unilever" \                                                                     
      --metrics "Revenue,EBITDA,Gross Profit" \                                                  
      --db-path static/tree_poc.db                                                               
                                                                                                 
  # Partial with custom year range                                                               
  python test_mcts_search.py workflow \                                                          
      --company "Unilever" \                                                                     
      --metrics "Revenue,Net Profit" \                                                           
      --years "2023,2024,2025" \                                                                 
      --db-path static/tree_poc.db                                                               
                                                                                                 
  # Original MCTS mode (unchanged)                                                               
  python test_mcts_search.py mcts \                                                              
      --db-path verify_test.db --doc-pk 1 \                                                      
      --query "What was Unilever's revenue in 2022?" \                                           
      --iterations 10                          
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="Test SSE stream from /api/spread")
    parser.add_argument("--company", default="TEST (Mock)", help="Company name")
    parser.add_argument("--mock", action="store_true", help="Use mock endpoint")
    parser.add_argument("--url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--years", default="2021,2022,2023,2024,2025", help="Comma-separated year periods")
    parser.add_argument("--metrics", default="Revenue,Gross Profit,EBITDA,Net Profit", help="Comma-separated metric names (at least 2)")
    args = parser.parse_args()

    year_periods = [y.strip() for y in args.years.split(",") if y.strip()]
    metric_names = [m.strip() for m in args.metrics.split(",") if m.strip()]

    if len(metric_names) < 2:
        print("ERROR: At least 2 metrics required")
        sys.exit(1)

    metrics_payload = [
        {"row_index": i, "metric_name": name}
        for i, name in enumerate(metric_names)
    ]

    endpoint = f"{args.url}/api/mock/spread" if args.mock else f"{args.url}/api/spread"

    body = {
        "company_name": args.company,
        "year_periods": year_periods,
        "metrics": metrics_payload,
        "data_source": "Internal Model",
    }

    print(f"Connecting to: {endpoint}")
    print(f"Company: {args.company}")
    print(f"Years: {year_periods}")
    print(f"Metrics ({len(metrics_payload)}): {[m['metric_name'] for m in metrics_payload]}")
    print("-" * 60)

    start = time.monotonic()
    event_count = 0
    resolved_count = 0
    unresolved_count = 0
    row_index_issues: list[str] = []

    try:
        response = requests.post(
            endpoint,
            json=body,
            stream=True,
            timeout=600,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        buffer = ""
        for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
            if not chunk:
                continue

            buffer += chunk if isinstance(chunk, str) else chunk.decode("utf-8")
            lines = buffer.split("\n")
            buffer = lines.pop() or ""

            for line in lines:
                if not line.startswith("data: "):
                    continue

                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    print(f"[PARSE ERROR] {line[:120]}")
                    continue

                event_count += 1

                # System events
                if "event" in event and event["event"] in ("tree_verification", "complete", "year_error"):
                    event_type = event["event"]
                    if event_type == "tree_verification":
                        for yr, r in (event.get("results") or {}).items():
                            status = r.get("status", "?")
                            print(f"[VERIFY] {yr}: {status}  nodes={r.get('total_nodes','?')}  leaves_with_text={r.get('leaves_with_text','?')}")
                            if r.get("issues"):
                                for issue in r["issues"]:
                                    print(f"         issue: {issue}")
                    elif event_type == "year_error":
                        print(f"[YEAR ERROR] {event.get('year')}: {event.get('message')}")
                    elif event_type == "complete":
                        wid = event.get("workflow_id")
                        print(f"[COMPLETE] workflow_id={wid}")
                    continue

                # Metric event
                name = event.get("canonical_name", "?")
                year = event.get("year", "?")
                ri = event.get("row_index")
                status = event.get("status", "?")
                value = event.get("value")
                formula = event.get("formula")
                error = event.get("error")
                src = event.get("source_location")
                comps = event.get("component_details")

                if status == "resolved":
                    resolved_count += 1
                    print(f"[RESOLVED] row={ri}  {name}  year={year}  value={value}")
                elif status == "unresolved":
                    unresolved_count += 1
                    print(f"[UNRESOLVED] row={ri}  {name}  year={year}  error={error}")
                else:
                    print(f"[{status.upper()}] row={ri}  {name}  year={year}  value={value}")

                if ri is None:
                    row_index_issues.append(f"{name} (year={year}) — row_index is None, frontend will ignore this event")

                if formula:
                    print(f"           formula={formula}")
                if src:
                    print(f"           source_location={src}")
                if comps:
                    for cd in comps:
                        print(f"           component: {cd.get('component_name')} = {cd.get('value')}  ({cd.get('source_location', '')})")

    except requests.exceptions.ConnectionError as e:
        print(f"\nERROR: Cannot connect to backend at {args.url}")
        print(f"  {e}")
        print(f"  Is the backend running? Try: uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("\nERROR: Request timed out after 120s")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    elapsed = time.monotonic() - start
    print("-" * 60)
    print(f"Total events: {event_count}")
    print(f"  Resolved:   {resolved_count}")
    print(f"  Unresolved: {unresolved_count}")
    print(f"  Without row_index: {len(row_index_issues)}")
    if row_index_issues:
        for issue in row_index_issues:
            print(f"    WARNING: {issue}")
    print(f"Elapsed: {elapsed:.2f}s")


if __name__ == "__main__":
    main()
