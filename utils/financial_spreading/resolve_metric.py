# Input: MetricDefinition, Metric, MCTS search callable, component-value map
# Output: MetricResolver — resolves a single metric via direct / derived /
#   derived_else_direct strategies with safe formula evaluation
# Position: Core resolution engine for financial spreading. If modified, update
#   this header and the parent folder's README_financial_spreading.md index.

from __future__ import annotations

import re
import operator
from dataclasses import dataclass
from typing import Any, Callable

from models.MetricDefinition import MetricDefinition
from models.Metric import AdditionalContext, ComponentDetail, Metric


@dataclass
class SearchResult:
    """Value returned by MCTS search along with source attribution metadata."""
    value: float | None
    source_file: str = ""       # e.g. "Unilever"
    source_year: str = ""       # e.g. "FY22"
    source_pages: str = ""      # e.g. "12-15"


def _format_source_location(result: SearchResult | None) -> str:
    """Format MCTS source attribution for tooltip display."""
    if not result:
        return ""
    parts = [result.source_file, result.source_year]
    label = " ".join(p for p in parts if p)
    if result.source_pages:
        label = f"{label}, pp. {result.source_pages}" if label else f"pp. {result.source_pages}"
    return label


MCTSSearchFn = Callable[[str, list[str]], SearchResult | None]
"""Signature: (canonical_name, synonyms) -> SearchResult or None."""


class FormulaEvaluator:
    """Safe recursive-descent arithmetic evaluator.

    Replaces metric-name variables with their numeric values, then evaluates the
    resulting expression.  Only digits, decimal points, operators (+, -, *, /),
    parentheses and whitespace are allowed after substitution.
    """

    _OPS = {
        "+": operator.add,
        "-": operator.sub,
        "*": operator.mul,
        "/": operator.truediv,
    }

    def evaluate(self, formula: str, component_map: dict[str, float], precision: int = 5) -> float:
        if not formula or not formula.strip():
            raise ValueError("Empty formula")
        substituted = self._substitute_variables(formula, component_map)
        self._validate_expression(substituted)
        tokens = self._tokenize(substituted)
        result = self._parse_expression(tokens)
        if result is None:
            raise ValueError(f"Could not parse expression: {substituted}")
        return round(result, precision)

    def _substitute_variables(self, formula: str, component_map: dict[str, float]) -> str:
        """Replace metric names (longest first to avoid partial overlap) with their values."""
        result = formula
        for name in sorted(component_map.keys(), key=len, reverse=True):
            value = component_map[name]
            result = result.replace(name, str(value))
        return result

    def _validate_expression(self, expression: str) -> None:
        allowed = re.compile(r"^[\d.\s+\-*/()]+$")
        if not allowed.match(expression):
            raise ValueError(f"Expression contains disallowed characters: {expression}")

    def _tokenize(self, expression: str) -> list[str]:
        tokens = []
        cursor = 0
        length = len(expression)
        while cursor < length:
            char = expression[cursor]
            if char.isspace():
                cursor += 1
                continue
            if char in "+-*/()":
                tokens.append(char)
                cursor += 1
            elif char.isdigit() or char == ".":
                start = cursor
                while cursor < length and (expression[cursor].isdigit() or expression[cursor] == "."):
                    cursor += 1
                tokens.append(expression[start:cursor])
            else:
                raise ValueError(f"Unexpected character '{char}' in expression")
        return tokens

    def _parse_expression(self, tokens: list[str]) -> float | None:
        if not tokens:
            return None
        value, pos = self._parse_add_sub(tokens, 0)
        if pos < len(tokens):
            raise ValueError(f"Unexpected token '{tokens[pos]}' at position {pos}")
        return value

    def _parse_add_sub(self, tokens: list[str], pos: int) -> tuple[float | None, int]:
        left, pos = self._parse_mul_div(tokens, pos)
        while pos < len(tokens) and tokens[pos] in ("+", "-"):
            op = self._OPS[tokens[pos]]
            right, pos = self._parse_mul_div(tokens, pos + 1)
            if left is None or right is None:
                left = None
            else:
                left = op(left, right)
        return left, pos

    def _parse_mul_div(self, tokens: list[str], pos: int) -> tuple[float | None, int]:
        left, pos = self._parse_atom(tokens, pos)
        while pos < len(tokens) and tokens[pos] in ("*", "/"):
            op = self._OPS[tokens[pos]]
            right, pos = self._parse_atom(tokens, pos + 1)
            if left is None or right is None:
                left = None
            elif op is operator.truediv and right == 0:
                left = None
            else:
                left = op(left, right)
        return left, pos

    def _parse_atom(self, tokens: list[str], pos: int) -> tuple[float | None, int]:
        if pos >= len(tokens):
            return None, pos
        token = tokens[pos]
        if token == "(":
            value, pos = self._parse_add_sub(tokens, pos + 1)
            if pos < len(tokens) and tokens[pos] == ")":
                return value, pos + 1
            return None, pos
        if token == "-":
            value, pos = self._parse_atom(tokens, pos + 1)
            return (-value if value is not None else None), pos
        if token == "+":
            return self._parse_atom(tokens, pos + 1)
        try:
            return float(token), pos + 1
        except ValueError:
            return None, pos


class MetricResolver:
    """Resolves a single MetricDefinition into a Metric value object.

    Resolution strategies (in priority order):
      1. direct       — MCTS search on the PDF JSON tree using synonyms
      2. derived      — recursively resolve components, then evaluate formula
      3. fallback     — if derived fails, try MCTS search for the metric itself
      4. na           — set value to None

    The ``mcts_search`` callable abstracts the actual search so this module
    stays decoupled from the specific MCTS / tree-search implementation.
    """

    def __init__(self, mcts_search: MCTSSearchFn | None = None):
        self._mcts_search = mcts_search
        self._evaluator = FormulaEvaluator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_metric(
        self,
        metric_def: MetricDefinition,
        *,
        region: str | None = None,
        precision: int = 5,
    ) -> Metric:
        """Resolve *metric_def* and return a populated Metric."""
        resolution_order = self._resolution_order(metric_def.input_type)

        metric = Metric(canonical_name=metric_def.canonical_name, definition=metric_def)

        for method in resolution_order:
            context = self._try_resolve(metric_def, method, region, precision)
            if context is not None and self._is_success(context):
                metric.value = context.result
                metric.status = "resolved"
                metric.resolution_method = method
                metric.formula_used = context.formula
                metric.additional_context = context
                return metric

            if context is not None:
                metric.additional_context = context
                metric.formula_used = context.formula

        metric.status = "unresolved"
        metric.resolution_method = "na"
        metric.value = None
        return metric

    # ------------------------------------------------------------------
    # Resolution strategies
    # ------------------------------------------------------------------

    def _try_resolve(
        self,
        metric_def: MetricDefinition,
        method: str,
        region: str | None,
        precision: int,
    ) -> AdditionalContext | None:
        if method == "direct":
            return self._resolve_direct(metric_def)
        if method == "derived":
            return self._resolve_derived(metric_def, region, precision)
        if method == "fallback_search":
            return self._resolve_direct(metric_def)  # same MCTS path
        return None

    def _resolve_direct(self, metric_def: MetricDefinition) -> AdditionalContext | None:
        """MCTS search using the metric's synonym bank."""
        if self._mcts_search is None:
            return AdditionalContext(
                metric_name=metric_def.canonical_name,
                input_type=metric_def.input_type,
                resolution_method="direct",
                status_note="No MCTS search function configured.",
            )

        synonyms = metric_def.synonyms or [metric_def.canonical_name]
        try:
            search_result = self._mcts_search(metric_def.canonical_name, synonyms)
        except Exception as exc:
            return AdditionalContext(
                metric_name=metric_def.canonical_name,
                input_type=metric_def.input_type,
                resolution_method="direct",
                status_note=f"MCTS search error: {exc}",
            )

        if search_result is None or search_result.value is None:
            return AdditionalContext(
                metric_name=metric_def.canonical_name,
                input_type=metric_def.input_type,
                resolution_method="direct",
                status_note=f"Not found via MCTS search. Synonyms tried: {synonyms}",
            )

        comp_detail = ComponentDetail(
            component_name=metric_def.canonical_name,
            value=search_result.value,
            status_note="Direct retrieval successful.",
            source_location=_format_source_location(search_result),
        )
        return AdditionalContext(
            metric_name=metric_def.canonical_name,
            input_type=metric_def.input_type,
            resolution_method="direct",
            success=True,
            result=search_result.value,
            component_details=[comp_detail],
            status_note="Successfully retrieved via direct MCTS search.",
        )

    def _resolve_derived(
        self,
        metric_def: MetricDefinition,
        region: str | None,
        precision: int,
    ) -> AdditionalContext | None:
        """Compute metric from its component metrics using the derivation formula."""
        formula = metric_def.formula
        if formula is None:
            return AdditionalContext(
                metric_name=metric_def.canonical_name,
                input_type=metric_def.input_type,
                resolution_method="derived",
                status_note="No derivation formula defined.",
            )

        components = metric_def.derivation_components
        if not components:
            return AdditionalContext(
                metric_name=metric_def.canonical_name,
                input_type=metric_def.input_type,
                resolution_method="derived",
                status_note="No component metrics defined for derivation.",
            )

        component_map: dict[str, float] = {}
        component_details: list[ComponentDetail] = []
        issues: list[str] = []

        for comp_name in components:
            comp_result = self._get_component_value(comp_name)
            comp_value = comp_result.get("value")
            comp_note = comp_result.get("status_note", "")
            comp_source = comp_result.get("source_location", "")

            component_details.append(
                ComponentDetail(
                    component_name=comp_name,
                    value=comp_value,
                    status_note=comp_note,
                    source_location=comp_source,
                )
            )

            if comp_value is None:
                issues.append(f"{comp_name}: {comp_note}")
            else:
                component_map[comp_name] = comp_value

        if issues:
            return AdditionalContext(
                metric_name=metric_def.canonical_name,
                input_type=metric_def.input_type,
                resolution_method="derived",
                formula=formula,
                component_details=component_details,
                status_note=f"Component(s) missing: {'; '.join(issues)}",
            )

        try:
            computed = self._evaluator.evaluate(formula, component_map, precision)
        except Exception as exc:
            return AdditionalContext(
                metric_name=metric_def.canonical_name,
                input_type=metric_def.input_type,
                resolution_method="derived",
                formula=formula,
                component_details=component_details,
                status_note=f"Formula evaluation error: {exc}",
            )

        return AdditionalContext(
            metric_name=metric_def.canonical_name,
            input_type=metric_def.input_type,
            resolution_method="derived",
            success=True,
            result=computed,
            formula=formula,
            component_details=component_details,
            status_note="Successfully calculated.",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolution_order(input_type: str) -> list[str]:
        if input_type == "derived_else_direct":
            return ["direct", "derived", "fallback_search"]
        if input_type == "direct":
            return ["direct", "fallback_search"]
        return ["derived", "fallback_search"]

    @staticmethod
    def _is_success(context: AdditionalContext) -> bool:
        return context.success

    def _get_component_value(self, component_name: str) -> dict[str, Any]:
        """Retrieve a component's value via MCTS search.

        The component name is used directly as a search query (it will be
        resolved later against its own MetricDefinition when run through the
        workflow's dependency-ordered resolution).
        """
        if self._mcts_search is None:
            return {"value": None, "status_note": "No MCTS search configured.", "source_location": ""}
        try:
            search_result = self._mcts_search(component_name, [component_name])
            if search_result is not None and search_result.value is not None:
                return {
                    "value": search_result.value,
                    "status_note": "Successfully retrieved metric value.",
                    "source_location": _format_source_location(search_result),
                }
            return {
                "value": None,
                "status_note": f"Metric '{component_name}' not found.",
                "source_location": "",
            }
        except Exception as exc:
            return {"value": None, "status_note": f"Search error: {exc}", "source_location": ""}
