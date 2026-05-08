# Input: FinancialSpreadingWorkflow, Metric, MetricDefinition
# Output: Verifies that _resolve_aggregations() fires the progress_callback
#   for each aggregation metric (Gap 1), while respecting the is_mentioned
#   filter (Gap 4).
# Position: Test for Gap 1 fix. If modified, update this header.

import copy
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.Metric import Metric
from utils.financial_spreading.financial_spreading_workflow import (
    FinancialSpreadingWorkflow,
)
from utils.financial_spreading.resolve_metric import SearchResult


def _dummy_mcts_search(canonical_name: str, synonyms: list[str]) -> SearchResult | None:
    return SearchResult(value=100.0)


def test_aggregation_callback_fires_for_mentioned():
    """Gap 1: _resolve_aggregations() fires progress_callback for aggregations
    that have is_mentioned: true."""
    fired: list[str] = []

    def capture(metric: Metric) -> None:
        fired.append(metric.canonical_name)

    workflow = FinancialSpreadingWorkflow(
        yaml_path="metric_definitions.yaml",
        mcts_search=_dummy_mcts_search,
        progress_callback=capture,
    )

    # Temporarily set one aggregation to is_mentioned: true so we can verify
    # the Gap 1 callback path is active.
    saved = copy.deepcopy(workflow.aggregations)
    try:
        for agg_name in workflow.aggregations:
            workflow.aggregations[agg_name]["is_mentioned"] = True

        workflow._definitions = workflow._load_definitions()
        ordered = workflow._topological_sort(workflow._definitions)

        # Phase 1: resolve all direct metrics (needed by aggregation sub-items)
        for mdef in ordered:
            if mdef.input_type == "direct":
                workflow._resolve_and_store(mdef, precision=5)

        fired.clear()
        workflow._resolve_aggregations()

        expected = list(workflow.aggregations.keys())
        assert len(expected) > 0, "No aggregations defined in YAML"

        for agg_name in expected:
            assert agg_name in fired, (
                f"Aggregation '{agg_name}' should have fired progress_callback "
                f"when is_mentioned=True. Fired: {fired}"
            )
    finally:
        workflow.aggregations = saved

    print("[PASS] Gap 1: _resolve_aggregations callback fires when is_mentioned=true")


def test_aggregation_callback_suppressed_for_unmentioned():
    """Gap 1 + Gap 4: aggregations with is_mentioned: false do NOT fire the
    progress_callback (prevents frontend noise)."""
    fired: list[str] = []

    def capture(metric: Metric) -> None:
        fired.append(metric.canonical_name)

    workflow = FinancialSpreadingWorkflow(
        yaml_path="metric_definitions.yaml",
        mcts_search=_dummy_mcts_search,
        progress_callback=capture,
    )

    workflow._definitions = workflow._load_definitions()
    ordered = workflow._topological_sort(workflow._definitions)

    for mdef in ordered:
        if mdef.input_type == "direct":
            workflow._resolve_and_store(mdef, precision=5)

    fired.clear()
    workflow._resolve_aggregations()

    # All default aggregations (Equity, Reserves, Short Term Debt, Long Term Debt)
    # have is_mentioned: false → no callbacks should fire.
    assert len(fired) == 0, (
        f"Expected 0 callbacks for unmentioned aggregations, got: {fired}"
    )

    print("[PASS] Gap 1+4: unmentioned aggregation callbacks correctly suppressed")


if __name__ == "__main__":
    test_aggregation_callback_fires_for_mentioned()
    test_aggregation_callback_suppressed_for_unmentioned()
