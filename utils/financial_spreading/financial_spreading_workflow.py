# Input: metric_definitions.yaml, MCTS search callable
# Output: FinancialSpreadingWorkflow — orchestrates metric resolution in
#   dependency order, assembles the final SCT table for the frontend
# Position: Top-level orchestrator. If modified, update this header and the
#   parent folder's README_financial_spreading.md index.

from __future__ import annotations

import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import yaml

from models.MetricDefinition import MetricDefinition
from models.Metric import AdditionalContext, ComponentDetail, Metric
from utils.financial_spreading.resolve_metric import (
    FormulaEvaluator,
    MetricResolver,
    MCTSSearchFn,
    SearchResult,
    _format_source_location,
)


def compute_dependency_closure(
    requested_names: set[str],
    definitions: list[MetricDefinition],
    aggregations: dict[str, dict],
) -> set[str]:
    """Compute the full transitive closure of metric dependencies.

    Given a set of requested canonical names, walks through
    ``derivation_components`` and aggregation sub-items to find every metric
    that must be resolved first.
    """
    name_to_def = {d.canonical_name: d for d in definitions}
    needed: set[str] = set(requested_names)
    queue: list[str] = list(requested_names)

    while queue:
        name = queue.pop(0)
        mdef = name_to_def.get(name)
        if mdef is not None:
            for comp in mdef.derivation_components:
                if comp not in needed:
                    needed.add(comp)
                    queue.append(comp)
            continue

        agg = aggregations.get(name, {})
        for comp in agg.get("components", []):
            comp_name = comp["metric"]
            if comp_name not in needed:
                needed.add(comp_name)
                queue.append(comp_name)

    return needed


def compute_yoy(
    sct_by_year: dict[str, dict[str, list[Metric]]],
    years: list[str],
) -> list[dict[str, Any]]:
    """Compute Year-over-Year % change for every metric across consecutive years.

    Returns a list of dicts suitable for SSE event emission, each containing
    canonical_name, year (e.g. "2022_YoY"), value, status, and component_details.
    """
    events: list[dict[str, Any]] = []
    if len(years) < 2:
        return events

    sorted_years = sorted(years)
    for i in range(1, len(sorted_years)):
        prev_year = sorted_years[i - 1]
        curr_year = sorted_years[i]
        yoy_label = f"{curr_year}_YoY"

        prev_sct = sct_by_year.get(prev_year, {})
        curr_sct = sct_by_year.get(curr_year, {})

        all_sections = set(prev_sct.keys()) | set(curr_sct.keys())
        for section in all_sections:
            prev_metrics = {m.canonical_name: m for m in prev_sct.get(section, [])}
            curr_metrics = {m.canonical_name: m for m in curr_sct.get(section, [])}

            for name, curr_m in curr_metrics.items():
                prev_m = prev_metrics.get(name)
                if prev_m is None or prev_m.value is None or curr_m.value is None:
                    yoy_value = None
                    yoy_status = "unresolved"
                elif prev_m.value == 0:
                    yoy_value = None
                    yoy_status = "unresolved"
                else:
                    yoy_value = round((curr_m.value - prev_m.value) / abs(prev_m.value) * 100, 2)
                    yoy_status = "resolved"

                events.append({
                    "canonical_name": name,
                    "year": yoy_label,
                    "value": yoy_value,
                    "status": yoy_status,
                    "formula": f"({curr_year} - {prev_year}) / |{prev_year}| * 100",
                    "component_details": [
                        {"component_name": f"{curr_year} value", "value": curr_m.value},
                        {"component_name": f"{prev_year} value", "value": prev_m.value},
                    ],
                })

    return events


ProgressCallback = Callable[[Metric], None]
"""Called after each metric is resolved so the frontend can update its cell."""


class FinancialSpreadingWorkflow:
    """Orchestrates the full financial-spreading pipeline.

    Usage::

        workflow = FinancialSpreadingWorkflow(
            yaml_path="metric_definitions.yaml",
            mcts_search=my_search_fn,
        )
        sct_table = workflow.run()
    """

    def __init__(
        self,
        yaml_path: str,
        mcts_search: MCTSSearchFn | None = None,
        *,
        progress_callback: ProgressCallback | None = None,
    ):
        with open(yaml_path, encoding="utf-8") as fh:
            self._raw = yaml.safe_load(fh)

        self._mcts_search = mcts_search
        self._progress_callback = progress_callback
        self._evaluator = FormulaEvaluator()
        self._resolver = MetricResolver(mcts_search)

        # Populated by run()
        self._definitions: list[MetricDefinition] = []
        self._resolved: dict[str, Metric] = {}
        self._resolved_lock = threading.Lock()

        # Classification & alias map from YAML
        self.classification: dict[str, list[str]] = self._raw.get("classification", {})
        self.alias_map: dict[str, str] = self._raw.get("alias_map", {})
        self.aggregations: dict[str, dict] = self._raw.get("aggregations", {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, *, precision: int = 5) -> dict[str, list[Metric]]:
        """Execute the full workflow and return the SCT table.

        Returns a dict keyed by ``statement_type``, each value a list of
        resolved Metrics in the order they should appear in the table.
        """
        self._definitions = self._load_definitions()
        ordered = self._topological_sort(self._definitions)
        self._resolved.clear()

        # Phase 1: direct-only metrics (no dependencies) — includes aggregation
        # sub-items that feed into Phase 2.
        for mdef in ordered:
            if mdef.input_type == "direct":
                self._resolve_and_store(mdef, precision)

        # Phase 2: compute aggregation totals (Equity, Reserves, Short Term Debt,
        # Long Term Debt) from their now-resolved sub-items so derived metrics
        # that depend on them (Net Worth, Tangible Net Worth, etc.) can resolve.
        self._resolve_aggregations()

        # Phase 2b: fallback MCTS search for aggregation totals that still have
        # no value (all sub-items missed).  Aggregations are not in self._definitions
        # so Phase 5 won't cover them — we must handle them explicitly here.
        for agg_name, agg_data in self.aggregations.items():
            agg_metric = self._resolved.get(agg_name)
            if agg_metric is not None and agg_metric.value is not None:
                continue
            synonyms = agg_data.get("synonyms", [agg_name])
            mdef = MetricDefinition(
                canonical_name=agg_name,
                input_type="direct",
                metric_type="absolute",
                statement_type=agg_data.get("statement_type", "Balance Sheet"),
                is_mentioned=agg_data.get("is_mentioned", False),
                synonyms=list(synonyms),
            )
            self._resolve_fallback(mdef, precision)

        # Phase 3: derived_else_direct — try direct first, then derived
        for mdef in ordered:
            if mdef.input_type == "derived_else_direct":
                self._resolve_and_store(mdef, precision)

        # Phase 4: derived — compute from (now-resolved) components
        for mdef in ordered:
            if mdef.input_type == "derived":
                self._resolve_and_store(mdef, precision)

        # Phase 5: fallback MCTS search for any still unresolved
        for mdef in ordered:
            metric = self._resolved.get(mdef.canonical_name)
            if metric is None or metric.status == "unresolved":
                self._resolve_fallback(mdef, precision)

        return self._assemble_sct_table()

    @property
    def resolved_metrics(self) -> dict[str, Metric]:
        """Access resolved metrics after ``run()`` completes."""
        return dict(self._resolved)

    def run_for_years(
        self,
        years: list[str],
        search_fn_by_year: dict[str, MCTSSearchFn] | None = None,
        *,
        precision: int = 5,
    ) -> dict[str, dict[str, list[Metric]]]:
        """Resolve metrics for multiple years with shared definition loading.

        ``search_fn_by_year`` maps each year to its own MCTS search function
        (each year has its own document forest in the DB).  If omitted, the
        same ``mcts_search`` passed to ``__init__`` is used for every year.

        Returns ``{year: sct_table}`` where each sct_table is the same shape
        as ``run()`` output.
        """
        if not years:
            raise ValueError("years must not be empty")

        # Load definitions and topological order once (shared across years)
        self._definitions = self._load_definitions()
        ordered = self._topological_sort(self._definitions)

        results: dict[str, dict[str, list[Metric]]] = {}
        original_search = self._mcts_search

        for year in years:
            # Switch the resolver's MCTS function for this year's forest
            if search_fn_by_year and year in search_fn_by_year:
                self._mcts_search = search_fn_by_year[year]
                self._resolver = MetricResolver(self._mcts_search)
            elif search_fn_by_year is None:
                # Reuse the single search function (caller handles year-awareness)
                self._resolver = MetricResolver(self._mcts_search)
            else:
                raise ValueError(
                    f"No MCTS search function provided for year {year!r}"
                )

            self._resolved.clear()

            # Phase 1: direct-only metrics
            for mdef in ordered:
                if mdef.input_type == "direct":
                    self._resolve_and_store(mdef, precision)

            # Phase 2: aggregation totals
            self._resolve_aggregations()

            # Phase 2b: fallback MCTS for aggregation totals with no value
            for agg_name, agg_data in self.aggregations.items():
                agg_metric = self._resolved.get(agg_name)
                if agg_metric is not None and agg_metric.value is not None:
                    continue
                synonyms = agg_data.get("synonyms", [agg_name])
                mdef = MetricDefinition(
                    canonical_name=agg_name,
                    input_type="direct",
                    metric_type="absolute",
                    statement_type=agg_data.get("statement_type", "Balance Sheet"),
                    is_mentioned=agg_data.get("is_mentioned", False),
                    synonyms=list(synonyms),
                )
                self._resolve_fallback(mdef, precision)

            # Phase 3: derived_else_direct
            for mdef in ordered:
                if mdef.input_type == "derived_else_direct":
                    self._resolve_and_store(mdef, precision)

            # Phase 4: derived
            for mdef in ordered:
                if mdef.input_type == "derived":
                    self._resolve_and_store(mdef, precision)

            # Phase 5: fallback
            for mdef in ordered:
                metric = self._resolved.get(mdef.canonical_name)
                if metric is None or metric.status == "unresolved":
                    self._resolve_fallback(mdef, precision)

            results[year] = self._assemble_sct_table()

        # Restore original search function
        self._mcts_search = original_search
        self._resolver = MetricResolver(self._mcts_search)

        return results

    def run_partial(
        self,
        canonical_names: list[str],
        *,
        precision: int = 5,
    ) -> dict[str, list[Metric]]:
        """Resolve only the requested metrics and their transitive dependencies.

        Uses within-phase concurrency (max 3 workers per phase) to accelerate
        direct and derived_else_direct resolution.  Aggregation sub-items and
        derived metrics that depend on them are resolved in dependency order.
        """
        self._definitions = self._load_definitions()
        self._resolved.clear()

        requested = set(canonical_names)
        needed = compute_dependency_closure(requested, self._definitions, self.aggregations)
        direct_defs, ded_defs, derived_defs = self._categorize_metrics(needed)

        # Phase 1: concurrent direct metrics (includes aggregation sub-items)
        self._resolve_phase_concurrently(direct_defs, precision, max_workers=3)

        # Phase 2: aggregations needed by the requested/derived closure
        needed_aggs = {
            name: cfg
            for name, cfg in self.aggregations.items()
            if name in needed
        }
        if needed_aggs:
            self._resolve_aggregations_subset(needed_aggs)

        # Phase 2b: fallback MCTS for aggregation totals that still have no value
        for agg_name in needed_aggs:
            agg_metric = self._resolved.get(agg_name)
            if agg_metric is not None and agg_metric.value is not None:
                continue
            agg_data = self.aggregations[agg_name]
            synonyms = agg_data.get("synonyms", [agg_name])
            mdef = MetricDefinition(
                canonical_name=agg_name,
                input_type="direct",
                metric_type="absolute",
                statement_type=agg_data.get("statement_type", "Balance Sheet"),
                is_mentioned=agg_data.get("is_mentioned", False),
                synonyms=list(synonyms),
            )
            self._resolve_fallback(mdef, precision)

        # Phase 3: concurrent derived_else_direct
        self._resolve_phase_concurrently(ded_defs, precision, max_workers=3)

        # Phase 4: derived — must be sequential and in topological order because
        # later metrics depend on earlier ones (e.g. Net Funded Debt depends on
        # Total Ext. Funded Debt). Pure derived metrics only evaluate formulas,
        # so concurrency provides no speed benefit and breaks correctness.
        derived_ordered = self._topological_sort(derived_defs)
        for mdef in derived_ordered:
            self._resolve_and_store(mdef, precision)

        # Phase 5: fallback for any still unresolved
        name_to_def = {d.canonical_name: d for d in self._definitions}
        for name in needed:
            metric = self._resolved.get(name)
            if metric is None or metric.status == "unresolved":
                mdef = name_to_def.get(name)
                if mdef is not None:
                    self._resolve_fallback(mdef, precision)

        # Phase 5b: retry any partial derived metrics whose dependencies may
        # have been resolved by the Phase 5 fallback (or a now-complete
        # aggregation).  Re-run the formula with the updated _resolved dict.
        partial_derived = {}
        for name in needed:
            m = self._resolved.get(name)
            if m is not None and m.status == "partial" and m.resolution_method == "derived":
                mdef = name_to_def.get(name)
                if mdef is not None:
                    partial_derived[name] = mdef
        if partial_derived:
            # Re-sort so dependencies resolve before dependents
            partial_ordered = self._topological_sort(list(partial_derived.values()))
            for mdef in partial_ordered:
                self._resolve_and_store(mdef, precision)

        return self._assemble_sct_table(only_names=needed)

    # ------------------------------------------------------------------
    # Concurrent resolution helpers
    # ------------------------------------------------------------------

    def _categorize_metrics(
        self,
        needed_names: set[str],
    ) -> tuple[list[MetricDefinition], list[MetricDefinition], list[MetricDefinition]]:
        """Split needed metric definitions into (direct, derived_else_direct, derived)."""
        name_to_def = {d.canonical_name: d for d in self._definitions}
        direct: list[MetricDefinition] = []
        ded: list[MetricDefinition] = []
        derived: list[MetricDefinition] = []

        for name in needed_names:
            mdef = name_to_def.get(name)
            if mdef is None:
                continue
            if mdef.input_type == "direct":
                direct.append(mdef)
            elif mdef.input_type == "derived_else_direct":
                ded.append(mdef)
            elif mdef.input_type == "derived":
                derived.append(mdef)

        return direct, ded, derived

    def _resolve_phase_concurrently(
        self,
        mdefs: list[MetricDefinition],
        precision: int,
        *,
        max_workers: int = 3,
    ) -> None:
        """Resolve a phase of metrics concurrently using a thread pool."""
        if not mdefs:
            return

        actual_workers = min(max_workers, max(1, len(mdefs)))
        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            futures = {
                executor.submit(self._resolve_and_store_thread_safe, mdef, precision): mdef
                for mdef in mdefs
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    # Error already captured in the metric's status_note
                    pass

    def _resolve_and_store_thread_safe(
        self,
        mdef: MetricDefinition,
        precision: int,
    ) -> None:
        """Thread-safe variant of _resolve_and_store for concurrent phases.

        Uses self._resolved_lock to protect shared dict access.  Metric
        resolution (MCTS search / formula evaluation) runs outside the lock
        so LLM calls remain fully concurrent.
        """
        with self._resolved_lock:
            if mdef.canonical_name in self._resolved:
                return

        if mdef.input_type in ("direct", "derived_else_direct"):
            metric = self._resolver.resolve_metric(mdef, precision=precision)
            if not metric.is_resolved:
                metric = self._resolve_with_components_thread_safe(mdef, precision)
        else:
            metric = self._resolve_with_components_thread_safe(mdef, precision)

        with self._resolved_lock:
            self._resolved[mdef.canonical_name] = metric

        if self._progress_callback and mdef.is_mentioned:
            self._progress_callback(metric)

    def _resolve_with_components_thread_safe(
        self,
        mdef: MetricDefinition,
        precision: int,
    ) -> Metric:
        """Thread-safe component-based resolution — reads _resolved under lock."""
        formula = mdef.formula
        if formula is None:
            return Metric(
                canonical_name=mdef.canonical_name,
                definition=mdef,
                status="unresolved",
                resolution_method="na",
                additional_context=AdditionalContext(
                    metric_name=mdef.canonical_name,
                    input_type=mdef.input_type,
                    resolution_method="derived",
                    status_note="No derivation formula defined.",
                ),
            )

        components = mdef.derivation_components
        if not components:
            return Metric(
                canonical_name=mdef.canonical_name,
                definition=mdef,
                status="unresolved",
                resolution_method="na",
                additional_context=AdditionalContext(
                    metric_name=mdef.canonical_name,
                    input_type=mdef.input_type,
                    resolution_method="derived",
                    status_note="No component metrics defined.",
                ),
            )

        with self._resolved_lock:
            component_map: dict[str, float] = {}
            component_details: list[ComponentDetail] = []
            issues: list[str] = []

            for comp_name in components:
                comp_metric = self._resolved.get(comp_name)
                if comp_metric is None or comp_metric.value is None:
                    issues.append(f"{comp_name}: not yet resolved")
                    component_details.append(
                        ComponentDetail(component_name=comp_name, status_note="Not resolved.")
                    )
                else:
                    comp_source = ""
                    if (comp_metric.additional_context and
                            comp_metric.additional_context.component_details):
                        comp_source = comp_metric.additional_context.component_details[0].source_location
                    component_map[comp_name] = comp_metric.value
                    component_details.append(
                        ComponentDetail(
                            component_name=comp_name,
                            value=comp_metric.value,
                            status_note="Successfully retrieved metric value.",
                            source_location=comp_source,
                        )
                    )

        if issues:
            return Metric(
                canonical_name=mdef.canonical_name,
                definition=mdef,
                status="partial",
                resolution_method="derived",
                formula_used=formula,
                additional_context=AdditionalContext(
                    metric_name=mdef.canonical_name,
                    input_type=mdef.input_type,
                    resolution_method="derived",
                    formula=formula,
                    component_details=component_details,
                    status_note=f"Component issue(s): {'; '.join(issues)}",
                ),
            )

        try:
            result = self._evaluator.evaluate(formula, component_map, precision)
        except Exception as exc:
            return Metric(
                canonical_name=mdef.canonical_name,
                definition=mdef,
                status="unresolved",
                resolution_method="derived",
                formula_used=formula,
                additional_context=AdditionalContext(
                    metric_name=mdef.canonical_name,
                    input_type=mdef.input_type,
                    resolution_method="derived",
                    formula=formula,
                    component_details=component_details,
                    status_note=f"Formula evaluation error: {exc}",
                ),
            )

        return Metric(
            canonical_name=mdef.canonical_name,
            definition=mdef,
            value=result,
            status="resolved",
            resolution_method="derived",
            formula_used=formula,
            additional_context=AdditionalContext(
                metric_name=mdef.canonical_name,
                input_type=mdef.input_type,
                resolution_method="derived",
                success=True,
                result=result,
                formula=formula,
                component_details=component_details,
                status_note="Successfully calculated.",
            ),
        )

    def _resolve_aggregations_subset(
        self,
        needed_aggs: dict[str, dict],
    ) -> None:
        """Compute aggregation totals only for the given subset.

        Same logic as _resolve_aggregations() but scoped to the needed
        aggregations so we don't do unnecessary work in partial-mode runs.
        """
        for agg_name, agg_data in needed_aggs.items():
            total = 0.0
            all_resolved = True
            comp_details: list[ComponentDetail] = []

            for comp in agg_data.get("components", []):
                sub_name = comp["metric"]
                sign = comp.get("sign", 1)
                with self._resolved_lock:
                    sub_metric = self._resolved.get(sub_name)

                if sub_metric is None or sub_metric.value is None:
                    all_resolved = False
                    comp_details.append(
                        ComponentDetail(
                            component_name=sub_name,
                            status_note="Not resolved.",
                        )
                    )
                else:
                    total += sub_metric.value * sign
                    sub_source = ""
                    if (sub_metric.additional_context and
                            sub_metric.additional_context.component_details):
                        sub_source = sub_metric.additional_context.component_details[0].source_location
                    comp_details.append(
                        ComponentDetail(
                            component_name=sub_name,
                            value=sub_metric.value,
                            status_note="Successfully retrieved metric value.",
                            source_location=sub_source,
                        )
                    )

            resolved_count = sum(1 for cd in comp_details if cd.value is not None)
            status = "resolved" if all_resolved else ("partial" if resolved_count > 0 else "unresolved")
            formula_parts = []
            for comp in agg_data.get("components", []):
                sign_str = "+" if comp.get("sign", 1) >= 0 else "-"
                formula_parts.append(f"{sign_str} {comp['metric']}")
            formula = " ".join(formula_parts).lstrip("+ ")

            synonyms = agg_data.get("synonyms", [agg_name])
            mdef = MetricDefinition(
                canonical_name=agg_name,
                input_type="derived",
                metric_type="absolute",
                statement_type=agg_data.get("statement_type", "Balance Sheet"),
                is_mentioned=agg_data.get("is_mentioned", False),
                component_metrics=[c["metric"] for c in agg_data.get("components", [])],
                formula_note=formula,
                synonyms=list(synonyms),
            )

            # Partial sums flow through: unresolved sub-items are ignored (treated as 0).
            metric = Metric(
                canonical_name=agg_name,
                definition=mdef,
                value=total if resolved_count > 0 else None,
                status=status,
                resolution_method="derived",
                formula_used=formula,
                additional_context=AdditionalContext(
                    metric_name=agg_name,
                    input_type="derived",
                    resolution_method="derived",
                    success=all_resolved,
                    result=total if resolved_count > 0 else None,
                    formula=formula,
                    component_details=comp_details,
                    status_note=(
                        "Successfully calculated."
                        if all_resolved
                        else f"{resolved_count}/{len(comp_details)} sub-items resolved. Unresolved items treated as 0."
                    ),
                ),
            )
            with self._resolved_lock:
                self._resolved[agg_name] = metric
            if self._progress_callback and mdef.is_mentioned:
                self._progress_callback(metric)

    # ------------------------------------------------------------------
    # Loading & ordering
    # ------------------------------------------------------------------

    def _load_definitions(self) -> list[MetricDefinition]:
        metrics_raw = self._raw.get("metrics", [])
        if not metrics_raw:
            raise ValueError("No metrics defined in YAML under 'metrics' key.")
        definitions = [MetricDefinition.from_dict(data) for data in metrics_raw]

        # Inject aggregation sub-item definitions so they have full definitions
        for agg_name, agg_data in self.aggregations.items():
            for comp in agg_data.get("components", []):
                sub_name = comp["metric"]
                if not any(d.canonical_name == sub_name for d in definitions):
                    definitions.append(
                        MetricDefinition(
                            canonical_name=sub_name,
                            input_type="direct",
                            metric_type="absolute",
                            statement_type=agg_data.get("statement_type", "Balance Sheet"),
                            is_mentioned=False,
                            synonyms=comp.get("synonyms", [sub_name]),
                        )
                    )

        return definitions

    def _topological_sort(self, definitions: list[MetricDefinition]) -> list[MetricDefinition]:
        """Sort definitions so that components come before their dependents."""
        name_to_def = {d.canonical_name: d for d in definitions}
        in_degree: dict[str, int] = {d.canonical_name: 0 for d in definitions}
        adjacency: dict[str, list[str]] = {d.canonical_name: [] for d in definitions}

        for mdef in definitions:
            for comp_name in mdef.derivation_components:
                if comp_name in name_to_def:
                    adjacency[comp_name].append(mdef.canonical_name)
                    in_degree[mdef.canonical_name] += 1

        queue = deque([name for name, deg in in_degree.items() if deg == 0])
        ordered: list[MetricDefinition] = []

        while queue:
            name = queue.popleft()
            ordered.append(name_to_def[name])
            for dependent in adjacency[name]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # Append any remaining (circular dependencies — resolve as best-effort)
        seen = {d.canonical_name for d in ordered}
        unseen = [d for d in definitions if d.canonical_name not in seen]
        if unseen:
            import logging
            _log = logging.getLogger(__name__)
            _log.warning(
                "Circular dependency detected among metrics: %s. "
                "These will be resolved last and may produce incorrect results.",
                [d.canonical_name for d in unseen],
            )
            ordered.extend(unseen)

        return ordered

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _resolve_and_store(self, mdef: MetricDefinition, precision: int) -> None:
        if mdef.canonical_name in self._resolved:
            return

        if mdef.input_type in ("direct", "derived_else_direct"):
            # Try the resolver first (direct MCTS for direct; MCTS-then-derived for
            # derived_else_direct).  Fall back to component-based resolution if the
            # resolver cannot satisfy the metric.
            metric = self._resolver.resolve_metric(mdef, precision=precision)
            if not metric.is_resolved:
                metric = self._resolve_with_components(mdef, precision)
        else:
            metric = self._resolve_with_components(mdef, precision)

        self._resolved[mdef.canonical_name] = metric
        if self._progress_callback and mdef.is_mentioned:
            self._progress_callback(metric)

    def _resolve_with_components(self, mdef: MetricDefinition, precision: int) -> Metric:
        """Resolve a derived metric using already-resolved component values."""
        formula = mdef.formula
        if formula is None:
            return Metric(
                canonical_name=mdef.canonical_name,
                definition=mdef,
                status="unresolved",
                resolution_method="na",
                additional_context=AdditionalContext(
                    metric_name=mdef.canonical_name,
                    input_type=mdef.input_type,
                    resolution_method="derived",
                    status_note="No derivation formula defined.",
                ),
            )

        components = mdef.derivation_components
        if not components:
            return Metric(
                canonical_name=mdef.canonical_name,
                definition=mdef,
                status="unresolved",
                resolution_method="na",
                additional_context=AdditionalContext(
                    metric_name=mdef.canonical_name,
                    input_type=mdef.input_type,
                    resolution_method="derived",
                    status_note="No component metrics defined.",
                ),
            )

        component_map: dict[str, float] = {}
        component_details: list[ComponentDetail] = []
        issues: list[str] = []

        for comp_name in components:
            comp_metric = self._resolved.get(comp_name)
            if comp_metric is None or comp_metric.value is None:
                issues.append(f"{comp_name}: not yet resolved")
                component_details.append(
                    ComponentDetail(component_name=comp_name, status_note="Not resolved.")
                )
            else:
                comp_source = ""
                if (comp_metric.additional_context and
                        comp_metric.additional_context.component_details):
                    comp_source = comp_metric.additional_context.component_details[0].source_location
                component_map[comp_name] = comp_metric.value
                component_details.append(
                    ComponentDetail(
                        component_name=comp_name,
                        value=comp_metric.value,
                        status_note="Successfully retrieved metric value.",
                        source_location=comp_source,
                    )
                )

        if issues:
            return Metric(
                canonical_name=mdef.canonical_name,
                definition=mdef,
                status="partial",
                resolution_method="derived",
                formula_used=formula,
                additional_context=AdditionalContext(
                    metric_name=mdef.canonical_name,
                    input_type=mdef.input_type,
                    resolution_method="derived",
                    formula=formula,
                    component_details=component_details,
                    status_note=f"Component issue(s): {'; '.join(issues)}",
                ),
            )

        try:
            result = self._evaluator.evaluate(formula, component_map, precision)
        except Exception as exc:
            return Metric(
                canonical_name=mdef.canonical_name,
                definition=mdef,
                status="unresolved",
                resolution_method="derived",
                formula_used=formula,
                additional_context=AdditionalContext(
                    metric_name=mdef.canonical_name,
                    input_type=mdef.input_type,
                    resolution_method="derived",
                    formula=formula,
                    component_details=component_details,
                    status_note=f"Formula evaluation error: {exc}",
                ),
            )

        return Metric(
            canonical_name=mdef.canonical_name,
            definition=mdef,
            value=result,
            status="resolved",
            resolution_method="derived",
            formula_used=formula,
            additional_context=AdditionalContext(
                metric_name=mdef.canonical_name,
                input_type=mdef.input_type,
                resolution_method="derived",
                success=True,
                result=result,
                formula=formula,
                component_details=component_details,
                status_note="Successfully calculated.",
            ),
        )

    def _resolve_fallback(self, mdef: MetricDefinition, precision: int) -> None:
        """Final attempt: MCTS search for the metric itself using synonyms."""
        if self._mcts_search is None:
            metric = Metric(
                canonical_name=mdef.canonical_name,
                definition=mdef,
                status="unresolved",
                resolution_method="na",
                additional_context=AdditionalContext(
                    metric_name=mdef.canonical_name,
                    input_type=mdef.input_type,
                    resolution_method="na",
                    status_note="No MCTS search configured — cannot fall back.",
                ),
            )
        else:
            synonyms = mdef.synonyms or [mdef.canonical_name]
            fallback_error: str | None = None
            try:
                search_result = self._mcts_search(mdef.canonical_name, synonyms)
            except Exception as exc:
                search_result = None
                fallback_error = str(exc)
            if search_result is not None and search_result.value is not None:
                fallback_value = search_result.value
                metric = Metric(
                    canonical_name=mdef.canonical_name,
                    definition=mdef,
                    value=fallback_value,
                    status="resolved",
                    resolution_method="fallback_search",
                    additional_context=AdditionalContext(
                        metric_name=mdef.canonical_name,
                        input_type=mdef.input_type,
                        resolution_method="fallback_search",
                        success=True,
                        result=fallback_value,
                        component_details=[
                            ComponentDetail(
                                component_name=mdef.canonical_name,
                                value=fallback_value,
                                status_note="Retrieved via fallback MCTS search.",
                                source_location=_format_source_location(search_result),
                            )
                        ],
                        status_note="Successfully retrieved via fallback search.",
                    ),
                )
            else:
                na_note = "Unavailable — set to NA."
                if fallback_error:
                    na_note += f" (Search error: {fallback_error})"
                metric = Metric(
                    canonical_name=mdef.canonical_name,
                    definition=mdef,
                    status="unresolved",
                    resolution_method="na",
                    additional_context=AdditionalContext(
                        metric_name=mdef.canonical_name,
                        input_type=mdef.input_type,
                        resolution_method="na",
                        status_note=na_note,
                    ),
                )

        self._resolved[mdef.canonical_name] = metric
        if self._progress_callback and mdef.is_mentioned:
            self._progress_callback(metric)

    # ------------------------------------------------------------------
    # SCT table assembly
    # ------------------------------------------------------------------

    def _assemble_sct_table(
        self,
        only_names: set[str] | None = None,
    ) -> dict[str, list[Metric]]:
        """Group resolved (is_mentioned=True) metrics by statement_type.

        When *only_names* is provided (partial-metric execution), only those
        canonical names appear in the output table.
        """
        table: dict[str, list[Metric]] = {}
        section_order = ["Income Statement", "Balance Sheet", "Cash Flow", "Ratios", "Others"]

        name_filter = only_names

        # Collect mentioned metrics from definitions (aggregations already resolved in Phase 2)
        for mdef in self._definitions:
            if not mdef.is_mentioned:
                continue
            if name_filter is not None and mdef.canonical_name not in name_filter:
                continue
            metric = self._resolved.get(mdef.canonical_name)
            if metric is None:
                metric = Metric(
                    canonical_name=mdef.canonical_name,
                    definition=mdef,
                    status="unresolved",
                    resolution_method="na",
                )
            section = mdef.statement_type
            if section not in table:
                table[section] = []
            table[section].append(metric)

        # Include aggregation metrics that have is_mentioned: true
        for agg_name, agg_cfg in self.aggregations.items():
            if not agg_cfg.get("is_mentioned", False):
                continue
            if name_filter is not None and agg_name not in name_filter:
                continue
            agg_metric = self._resolved.get(agg_name)
            if agg_metric is not None:
                section = agg_cfg.get("statement_type", "Balance Sheet")
                if section not in table:
                    table[section] = []
                table[section].append(agg_metric)

        # Sort by section order, keep others at the end
        result: dict[str, list[Metric]] = {}
        for section in section_order:
            if section in table:
                result[section] = table[section]
        for section in table:
            if section not in result:
                result[section] = table[section]
        return result

    def _resolve_aggregations(self) -> None:
        """Compute aggregation totals (Equity, Reserves, Short Term Debt, Long Term Debt)
        from their sub-items and store them as resolved Metrics."""
        for agg_name, agg_data in self.aggregations.items():
            total = 0.0
            all_resolved = True
            comp_details: list[ComponentDetail] = []

            for comp in agg_data.get("components", []):
                sub_name = comp["metric"]
                sign = comp.get("sign", 1)
                sub_metric = self._resolved.get(sub_name)

                if sub_metric is None or sub_metric.value is None:
                    all_resolved = False
                    comp_details.append(
                        ComponentDetail(
                            component_name=sub_name,
                            status_note="Not resolved.",
                        )
                    )
                else:
                    total += sub_metric.value * sign
                    sub_source = ""
                    if (sub_metric.additional_context and
                            sub_metric.additional_context.component_details):
                        sub_source = sub_metric.additional_context.component_details[0].source_location
                    comp_details.append(
                        ComponentDetail(
                            component_name=sub_name,
                            value=sub_metric.value,
                            status_note="Successfully retrieved metric value.",
                            source_location=sub_source,
                        )
                    )

            resolved_count = sum(1 for cd in comp_details if cd.value is not None)
            status = "resolved" if all_resolved else ("partial" if resolved_count > 0 else "unresolved")
            formula_parts = []
            for comp in agg_data.get("components", []):
                sign_str = "+" if comp.get("sign", 1) >= 0 else "-"
                formula_parts.append(f"{sign_str} {comp['metric']}")
            formula = " ".join(formula_parts).lstrip("+ ")

            synonyms = agg_data.get("synonyms", [agg_name])
            mdef = MetricDefinition(
                canonical_name=agg_name,
                input_type="derived",
                metric_type="absolute",
                statement_type=agg_data.get("statement_type", "Balance Sheet"),
                is_mentioned=agg_data.get("is_mentioned", False),
                component_metrics=[c["metric"] for c in agg_data.get("components", [])],
                formula_note=formula,
                synonyms=list(synonyms),
            )

            # Partial sums flow through: unresolved sub-items are ignored (treated as 0).
            # Status is "resolved" only when every sub-item resolved, "partial" when
            # at least one resolved, "unresolved" when none resolved at all.
            metric = Metric(
                canonical_name=agg_name,
                definition=mdef,
                value=total if resolved_count > 0 else None,
                status=status,
                resolution_method="derived",
                formula_used=formula,
                additional_context=AdditionalContext(
                    metric_name=agg_name,
                    input_type="derived",
                    resolution_method="derived",
                    success=all_resolved,
                    result=total if resolved_count > 0 else None,
                    formula=formula,
                    component_details=comp_details,
                    status_note=(
                        "Successfully calculated."
                        if all_resolved
                        else f"{resolved_count}/{len(comp_details)} sub-items resolved. Unresolved items treated as 0."
                    ),
                ),
            )
            self._resolved[agg_name] = metric
            if self._progress_callback and mdef.is_mentioned:
                self._progress_callback(metric)
