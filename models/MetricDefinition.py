# Input: metric_definitions.yaml (parsed dict per metric)
# Output: MetricDefinition dataclass consumed by MetricResolver and
#   FinancialSpreadingWorkflow
# Position: Domain model — canonical representation of a single metric's
#   definition (type, components, formula, synonyms). If modified, update this
#   header and the parent folder's README_models.md index.

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MetricDefinition:
    """Immutable definition of a financial metric loaded from YAML."""

    canonical_name: str
    input_type: str          # "direct" | "derived" | "derived_else_direct"
    metric_type: str          # "absolute" | "margin" | "ratio"
    statement_type: str       # "Income Statement" | "Balance Sheet" | "Cash Flow" | "Ratios" | "Others"
    is_mentioned: bool        # True = appears in final SCT table; False = intermediate only
    component_metrics: list[str] = field(default_factory=list)
    formula_note: str | None = None
    synonyms: list[str] = field(default_factory=list)
    derivation_code: dict | str | None = None
    direct_extraction_code: dict | str | None = None
    is_always_material: bool = False
    region_specific: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> MetricDefinition:
        return cls(
            canonical_name=data["canonical_name"],
            input_type=data.get("input_type", "derived"),
            metric_type=data.get("metric_type", "absolute"),
            statement_type=data.get("statement_type", "Others"),
            is_mentioned=data.get("is_mentioned", True),
            component_metrics=data.get("component_metrics", []),
            formula_note=data.get("formula_note"),
            synonyms=data.get("synonyms", []),
            derivation_code=data.get("derivation_code"),
            direct_extraction_code=data.get("direct_extraction_code"),
            is_always_material=data.get("is_always_material", False),
            region_specific=data.get("region_specific", False),
        )

    @property
    def formula(self) -> str | None:
        """Return the formula string from derivation_code, handling dict or string forms."""
        code = self.derivation_code
        if code is None:
            return None
        if isinstance(code, str):
            return code.strip()
        if isinstance(code, dict):
            formula = code.get("formula")
            return formula.strip() if isinstance(formula, str) and formula.strip() else None
        return None

    @property
    def derivation_components(self) -> list[str]:
        """Return the ordered component list from derivation_code, falling back to component_metrics."""
        code = self.derivation_code
        if isinstance(code, dict):
            comps = code.get("components", [])
            if comps:
                return [c.strip() if isinstance(c, str) else c for c in comps]
        return list(self.component_metrics)
