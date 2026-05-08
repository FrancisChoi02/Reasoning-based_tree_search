# Input: Metric, MetricDefinition
# Output: Verifies Metric.as_sse_event() produces valid SSE-formatted output
#   with the expected fields (Gap 3).
# Position: Test for Gap 3 fix. If modified, update this header.

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.Metric import AdditionalContext, ComponentDetail, Metric
from models.MetricDefinition import MetricDefinition


def _make_definition(**overrides) -> MetricDefinition:
    defaults = {
        "canonical_name": "Revenue",
        "input_type": "direct",
        "metric_type": "absolute",
        "statement_type": "Income Statement",
        "is_mentioned": True,
        "synonyms": ["Revenue", "Turnover"],
    }
    defaults.update(overrides)
    return MetricDefinition(**defaults)


def test_sse_event_resolved_metric():
    """SSE event for a successfully resolved metric."""
    mdef = _make_definition()
    metric = Metric(
        canonical_name="Revenue",
        definition=mdef,
        value=50000.0,
        status="resolved",
        resolution_method="direct",
    )

    event = metric.as_sse_event(row_index=0, year="2025")

    # Must start with SSE data: prefix
    assert event.startswith("data: "), f"Bad SSE prefix: {event[:30]}"
    # Must end with double newline
    assert event.endswith("\n\n"), f"Bad SSE suffix: {event[-10:]}"

    # Extract JSON payload
    payload_str = event[len("data: "):-2]
    payload = json.loads(payload_str)

    assert payload["canonical_name"] == "Revenue"
    assert payload["year"] == "2025"
    assert payload["value"] == 50000.0
    assert payload["status"] == "resolved"
    assert payload["error"] is None
    assert payload["row_index"] == 0
    print("[PASS] Gap 3: SSE event for resolved metric")


def test_sse_event_unresolved_metric():
    """SSE event for an unresolved metric includes error text."""
    mdef = _make_definition()
    metric = Metric(
        canonical_name="Net Profit",
        definition=mdef,
        status="unresolved",
        resolution_method="na",
        additional_context=AdditionalContext(
            metric_name="Net Profit",
            input_type="derived",
            resolution_method="na",
            status_note="Components missing: Interest Paid, Taxation",
        ),
    )

    event = metric.as_sse_event(year="2024")
    payload_str = event[len("data: "):-2]
    payload = json.loads(payload_str)

    assert payload["status"] == "unresolved"
    assert payload["error"] == "Components missing: Interest Paid, Taxation"
    assert payload["value"] is None
    # row_index is optional — should be absent when not provided
    assert "row_index" not in payload
    print("[PASS] Gap 3: SSE event for unresolved metric with error")


def test_sse_event_partial_metric():
    """SSE event for a partially resolved metric."""
    mdef = _make_definition(canonical_name="Net Worth")
    metric = Metric(
        canonical_name="Net Worth",
        definition=mdef,
        status="partial",
        value=None,
        resolution_method="derived",
        formula_used="Equity + Reserves",
        additional_context=AdditionalContext(
            metric_name="Net Worth",
            input_type="derived",
            resolution_method="derived",
            formula="Equity + Reserves",
            status_note="Some sub-items unresolved.",
        ),
    )

    event = metric.as_sse_event(row_index=10, year="2023")
    payload_str = event[len("data: "):-2]
    payload = json.loads(payload_str)

    assert payload["status"] == "partial"
    assert payload["formula"] == "Equity + Reserves"
    assert payload["row_index"] == 10
    assert payload["error"] is None  # partial != unresolved
    print("[PASS] Gap 3: SSE event for partial metric")


def test_sse_event_component_details_serialized():
    """SSE event includes component_details with source_location when present."""
    mdef = _make_definition(
        canonical_name="Gross Profit",
        input_type="derived_else_direct",
    )
    ctx = AdditionalContext(
        metric_name="Gross Profit",
        input_type="derived",
        resolution_method="derived",
        success=True,
        result=20000.0,
        formula="Revenue - Cost of Sales",
        component_details=[
            ComponentDetail(
                component_name="Revenue",
                value=50000.0,
                status_note="Successfully retrieved metric value.",
                source_location="Unilever FY22, pp. 12-15",
            ),
            ComponentDetail(
                component_name="Cost of Sales",
                value=30000.0,
                status_note="Successfully retrieved metric value.",
                source_location="Unilever FY22, pp. 18-20",
            ),
        ],
        status_note="Successfully calculated.",
    )
    metric = Metric(
        canonical_name="Gross Profit",
        definition=mdef,
        value=20000.0,
        status="resolved",
        resolution_method="derived",
        formula_used="Revenue - Cost of Sales",
        additional_context=ctx,
    )

    event = metric.as_sse_event(row_index=1, year="2022")
    payload_str = event[len("data: "):-2]
    payload = json.loads(payload_str)

    assert payload["source_location"] == "Unilever FY22, pp. 12-15"
    details = payload["component_details"]
    assert details is not None
    assert len(details) == 2
    assert details[0]["component_name"] == "Revenue"
    assert details[0]["value"] == 50000.0
    assert details[0]["source_location"] == "Unilever FY22, pp. 12-15"
    assert details[1]["component_name"] == "Cost of Sales"
    assert details[1]["value"] == 30000.0
    assert details[1]["source_location"] == "Unilever FY22, pp. 18-20"
    print("[PASS] Gap 3: SSE event includes component_details with source_location")


def test_sse_event_direct_metric_has_source_location():
    """SSE event for a direct metric includes source_location from its single component."""
    mdef = _make_definition(canonical_name="Revenue", input_type="direct")
    ctx = AdditionalContext(
        metric_name="Revenue",
        input_type="direct",
        resolution_method="direct",
        success=True,
        result=50000.0,
        component_details=[
            ComponentDetail(
                component_name="Revenue",
                value=50000.0,
                status_note="Direct retrieval successful.",
                source_location="Unilever FY22, pp. 12-15",
            ),
        ],
        status_note="Successfully retrieved via direct MCTS search.",
    )
    metric = Metric(
        canonical_name="Revenue",
        definition=mdef,
        value=50000.0,
        status="resolved",
        resolution_method="direct",
        additional_context=ctx,
    )

    event = metric.as_sse_event(row_index=0, year="2022")
    payload_str = event[len("data: "):-2]
    payload = json.loads(payload_str)

    assert payload["source_location"] == "Unilever FY22, pp. 12-15"
    assert payload["component_details"] is not None
    assert len(payload["component_details"]) == 1
    print("[PASS] Gap 3: direct metric SSE event includes source_location")


def test_sse_event_no_context_defaults():
    """SSE event with no additional_context defaults to null source_location and component_details."""
    mdef = _make_definition()
    metric = Metric(
        canonical_name="Revenue",
        definition=mdef,
        value=50000.0,
        status="resolved",
        resolution_method="direct",
    )

    event = metric.as_sse_event(row_index=0, year="2022")
    payload_str = event[len("data: "):-2]
    payload = json.loads(payload_str)

    assert payload["source_location"] is None
    assert payload["component_details"] is None
    assert payload["formula"] is None
    print("[PASS] Gap 3: no-context metric defaults to null source fields")


if __name__ == "__main__":
    test_sse_event_resolved_metric()
    test_sse_event_unresolved_metric()
    test_sse_event_partial_metric()
    test_sse_event_component_details_serialized()
    test_sse_event_direct_metric_has_source_location()
    test_sse_event_no_context_defaults()
