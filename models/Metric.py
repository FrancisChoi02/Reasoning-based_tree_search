# Input: MetricDefinition (definition reference), resolve_metric result
# Output: Metric value object consumed by frontend SCT table and tooltip display
# Position: Domain model — resolved instance of a financial metric. If modified,
#   update this header and the parent folder's README_models.md index.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from models.MetricDefinition import MetricDefinition


@dataclass
class ComponentDetail:
    """Detail for a single component used in a derived-metric calculation."""
    component_name: str
    value: float | None = None
    status_note: str = ""
    source_location: str = ""


@dataclass
class AdditionalContext:
    """Full resolution trail for a metric — used for tooltip display in the frontend."""
    metric_name: str
    input_type: str
    resolution_method: str
    success: bool = False
    result: float | None = None
    formula: str | None = None
    component_details: list[ComponentDetail] = field(default_factory=list)
    status_note: str = ""


@dataclass
class Metric:
    """Resolved metric with its value, status, and full resolution context."""

    canonical_name: str
    definition: MetricDefinition
    value: float | None = None
    status: str = "pending"  # "pending" | "resolved" | "partial" | "unresolved"
    resolution_method: str | None = None  # "direct" | "derived" | "fallback_search" | "na"
    formula_used: str | None = None
    additional_context: AdditionalContext | None = None

    @property
    def is_resolved(self) -> bool:
        return self.status == "resolved"

    @property
    def display_value(self) -> str:
        if self.value is None:
            return "NA"
        if self.definition.metric_type in ("margin", "ratio"):
            return f"{self.value:.2f}"
        return f"{self.value:,.0f}"

    def as_sse_event(
        self,
        *,
        row_index: int | None = None,
        year: str | None = None,
    ) -> str:
        """Serialize this metric as an SSE event for frontend streaming.

        Returns an SSE-formatted string (``data: {...}\\n\\n``) with fields:
        row_index, canonical_name, year, value, status, formula, error,
        source_location, component_details.
        """
        payload: dict[str, Any] = {
            "canonical_name": self.canonical_name,
            "year": year,
            "value": self.value,
            "status": self.status,
            "formula": self.formula_used,
            "error": None,
            "source_location": None,
            "component_details": None,
        }
        if row_index is not None:
            payload["row_index"] = row_index
        if self.status == "unresolved" and self.additional_context:
            payload["error"] = self.additional_context.status_note
        if self.additional_context and self.additional_context.component_details:
            payload["component_details"] = [
                {
                    "component_name": cd.component_name,
                    "value": cd.value,
                    "source_location": cd.source_location,
                }
                for cd in self.additional_context.component_details
            ]
            first = self.additional_context.component_details[0]
            if first.source_location:
                payload["source_location"] = first.source_location
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
