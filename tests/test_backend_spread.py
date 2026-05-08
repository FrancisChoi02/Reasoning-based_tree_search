# Input: FastAPI TestClient pointed at backend.main:app, existing DB with test data
# Output: Integration tests for POST /api/spread — SSE stream parsing, event order
# Position: Test coverage for the SSE streaming spread endpoint. If modified,
#   update this header.

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.main import app

client = TestClient(app)


def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE text into a list of event dicts."""
    events: list[dict] = []
    for line in text.split("\n"):
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


class TestSpreadRequestValidation:

    def test_empty_body_rejected(self):
        resp = client.post("/api/spread", json={})
        assert resp.status_code == 422

    def test_missing_metrics(self):
        resp = client.post("/api/spread", json={
            "company_name": "TestCo",
            "year_periods": ["2022"],
        })
        assert resp.status_code == 422

    def test_single_metric_rejected(self):
        """min_length=2 on metrics list."""
        resp = client.post("/api/spread", json={
            "company_name": "TestCo",
            "year_periods": ["2022"],
            "metrics": [{"row_index": 0, "metric_name": "Revenue"}],
        })
        assert resp.status_code == 422

    def test_valid_request_returns_sse_stream(self):
        """Even without real data, the endpoint should start streaming (verification
        events then possibly year_error events)."""
        resp = client.post("/api/spread", json={
            "company_name": "TestCo",
            "year_periods": ["2022", "2023"],
            "metrics": [
                {"row_index": 0, "metric_name": "Revenue"},
                {"row_index": 1, "metric_name": "Gross Profit"},
            ],
        })
        # Should return 200 and stream (even if trees don't exist)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = _parse_sse_events(resp.text)
        assert len(events) > 0, "Expected at least one SSE event"

        # First event should be tree_verification
        assert events[0]["event"] == "tree_verification"

    def test_verification_event_structure(self):
        resp = client.post("/api/spread", json={
            "company_name": "TestCo",
            "year_periods": ["2022"],
            "metrics": [
                {"row_index": 0, "metric_name": "Revenue"},
                {"row_index": 1, "metric_name": "Gross Profit"},
            ],
        })
        events = _parse_sse_events(resp.text)
        verification = events[0]
        assert "results" in verification
        assert "2022" in verification["results"]

        # For a non-existent company+year, status should be "error"
        fy22_result = verification["results"]["2022"]
        assert fy22_result["status"] == "error"

    def test_unknown_company_gets_tree_errors(self):
        resp = client.post("/api/spread", json={
            "company_name": "NonExistentCorp",
            "year_periods": ["2021", "2022", "2023", "2024", "2025"],
            "metrics": [
                {"row_index": 0, "metric_name": "Revenue"},
                {"row_index": 1, "metric_name": "Net Profit"},
            ],
        })
        events = _parse_sse_events(resp.text)
        verification = events[0]

        # All 5 years should have error status
        for year in ["2021", "2022", "2023", "2024", "2025"]:
            assert year in verification["results"]
            assert verification["results"][year]["status"] == "error"

        # Expect year_error events for each year (no tree available)
        year_errors = [e for e in events if e.get("event") == "year_error"]
        assert len(year_errors) == 5

    def test_stream_ends_with_complete_event(self):
        resp = client.post("/api/spread", json={
            "company_name": "TestCo",
            "year_periods": ["2022"],
            "metrics": [
                {"row_index": 0, "metric_name": "Revenue"},
                {"row_index": 1, "metric_name": "Gross Profit"},
            ],
        })
        events = _parse_sse_events(resp.text)
        assert events[-1]["event"] == "complete"


class TestSSEEventParsing:

    def test_metric_event_fields(self):
        """Verify the metric SSE payload format matches what the frontend expects."""
        from models.Metric import Metric
        from models.MetricDefinition import MetricDefinition

        mdef = MetricDefinition(
            canonical_name="Revenue",
            input_type="direct",
            metric_type="absolute",
            statement_type="Income Statement",
            is_mentioned=True,
        )
        metric = Metric(
            canonical_name="Revenue",
            definition=mdef,
            value=12345.67,
            status="resolved",
            resolution_method="direct",
        )

        sse_text = metric.as_sse_event(row_index=0, year="2022")
        assert sse_text.startswith("data: ")
        assert sse_text.endswith("\n\n")

        payload = json.loads(sse_text[6:].strip())
        assert payload["canonical_name"] == "Revenue"
        assert payload["year"] == "2022"
        assert payload["row_index"] == 0
        assert payload["value"] == 12345.67
        assert payload["status"] == "resolved"

    def test_unresolved_metric_includes_error(self):
        from models.Metric import Metric, AdditionalContext
        from models.MetricDefinition import MetricDefinition

        mdef = MetricDefinition(
            canonical_name="Gross Profit",
            input_type="derived_else_direct",
            metric_type="absolute",
            statement_type="Income Statement",
            is_mentioned=True,
        )
        ctx = AdditionalContext(
            metric_name="Gross Profit",
            input_type="derived_else_direct",
            resolution_method="na",
            status_note="No data available.",
        )
        metric = Metric(
            canonical_name="Gross Profit",
            definition=mdef,
            status="unresolved",
            resolution_method="na",
            additional_context=ctx,
        )

        sse_text = metric.as_sse_event(row_index=1, year="2022")
        payload = json.loads(sse_text[6:].strip())
        assert payload["status"] == "unresolved"
        assert payload["value"] is None
        assert "No data available" in payload["error"]
