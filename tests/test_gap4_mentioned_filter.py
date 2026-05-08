# Input: FinancialSpreadingWorkflow, MetricDefinition (is_mentioned: true/false)
# Output: Verifies progress_callback only fires for is_mentioned: true metrics,
#   filtering out intermediate/component metric noise (Gap 4).
# Position: Test for Gap 4 fix. If modified, update this header.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.Metric import Metric
from models.MetricDefinition import MetricDefinition
from utils.financial_spreading.financial_spreading_workflow import (
    FinancialSpreadingWorkflow,
)
from utils.financial_spreading.resolve_metric import SearchResult


def _dummy_mcts_search(canonical_name: str, synonyms: list[str]) -> SearchResult | None:
    return SearchResult(value=500.0)


def test_mentioned_filter_in_resolve_and_store():
    """Metrics with is_mentioned=False must NOT fire progress_callback
    during _resolve_and_store()."""
    fired: list[str] = []

    def capture(metric: Metric) -> None:
        fired.append(metric.canonical_name)

    workflow = FinancialSpreadingWorkflow(
        yaml_path="metric_definitions.yaml",
        mcts_search=_dummy_mcts_search,
        progress_callback=capture,
    )

    workflow._definitions = workflow._load_definitions()

    # Count mentioned vs non-mentioned across all definitions
    mentioned = [d for d in workflow._definitions if d.is_mentioned]
    unmentioned = [d for d in workflow._definitions if not d.is_mentioned]

    assert len(unmentioned) > 0, "Need at least one unmentioned metric to test"
    assert len(mentioned) > 0, "Need at least one mentioned metric to test"

    # Resolve an unmentioned direct metric
    unmentioned_direct = next(
        (d for d in unmentioned if d.input_type == "direct"), None
    )
    assert unmentioned_direct is not None, (
        "Need at least one unmentioned direct metric"
    )

    fired.clear()
    workflow._resolve_and_store(unmentioned_direct, precision=5)

    assert unmentioned_direct.canonical_name not in fired, (
        f"Unmentioned metric '{unmentioned_direct.canonical_name}' fired "
        f"progress_callback but is_mentioned=False"
    )

    # Resolve a mentioned metric — must fire
    mentioned_direct = next(
        (d for d in mentioned if d.input_type == "direct"), None
    )
    assert mentioned_direct is not None, "Need at least one mentioned direct metric"

    fired.clear()
    workflow._resolve_and_store(mentioned_direct, precision=5)

    assert mentioned_direct.canonical_name in fired, (
        f"Mentioned metric '{mentioned_direct.canonical_name}' did NOT fire "
        f"progress_callback"
    )

    print(
        f"[PASS] Gap 4: mentioned filter — {len(unmentioned)} intermediate metrics "
        f"suppressed, {len(mentioned)} mentioned metrics allowed"
    )


def test_mentioned_filter_in_fallback():
    """Unmentioned metrics must NOT fire progress_callback from _resolve_fallback()."""
    fired: list[str] = []

    def capture(metric: Metric) -> None:
        fired.append(metric.canonical_name)

    workflow = FinancialSpreadingWorkflow(
        yaml_path="metric_definitions.yaml",
        mcts_search=_dummy_mcts_search,
        progress_callback=capture,
    )

    workflow._definitions = workflow._load_definitions()

    # Find an unmentioned metric not yet resolved
    unmentioned = next(
        (d for d in workflow._definitions
         if not d.is_mentioned and d.canonical_name not in workflow._resolved),
        None,
    )
    assert unmentioned is not None

    fired.clear()
    workflow._resolve_fallback(unmentioned, precision=5)
    assert unmentioned.canonical_name not in fired, (
        f"Unmentioned metric '{unmentioned.canonical_name}' fired from fallback"
    )

    print("[PASS] Gap 4: fallback respects is_mentioned filter")


if __name__ == "__main__":
    test_mentioned_filter_in_resolve_and_store()
    test_mentioned_filter_in_fallback()
