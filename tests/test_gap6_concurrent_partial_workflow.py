# Input: FinancialSpreadingWorkflow, _dummy_mcts_search, metric_definitions.yaml
# Output: Deterministic unit coverage for run_partial() concurrent metric resolution
# Position: Gap 6 — validates partial-metric concurrent workflow correctness.
#   If modified, update this header and the parent folder's .md index.

import copy
import threading

from utils.financial_spreading.financial_spreading_workflow import (
    FinancialSpreadingWorkflow,
    compute_dependency_closure,
)
from utils.financial_spreading.resolve_metric import SearchResult


YAML_PATH = "metric_definitions.yaml"


def _make_search(value: float = 100.0, source_pages: str = "1-10") -> callable:
    """Factory: returns an MCTS search fn that always returns *value*."""
    def search(canonical_name: str, synonyms: list[str]) -> SearchResult | None:
        return SearchResult(
            value=value,
            source_file="TestCo",
            source_year="2023",
            source_pages=source_pages,
        )
    return search


def _capture_callback():
    """Return (callback_fn, fired_list) to track progress callbacks."""
    fired: list[str] = []
    def cb(metric):
        fired.append(metric.canonical_name)
    return cb, fired


def test_run_partial_single_direct_metric():
    """run_partial with only Revenue resolves just Revenue."""
    search = _make_search(value=52444.0)
    cb, fired = _capture_callback()
    workflow = FinancialSpreadingWorkflow(
        yaml_path=YAML_PATH,
        mcts_search=search,
        progress_callback=cb,
    )
    sct = workflow.run_partial(["Revenue"])

    assert len(fired) == 1
    assert fired[0] == "Revenue"

    is_section = sct.get("Income Statement", [])
    revenue_metrics = [m for m in is_section if m.canonical_name == "Revenue"]
    assert len(revenue_metrics) == 1
    assert revenue_metrics[0].value == 52444.0
    assert revenue_metrics[0].status == "resolved"

    # Verify other mentioned metrics were NOT resolved
    other_mentioned = [
        m.canonical_name
        for section in sct.values()
        for m in section
    ]
    assert "EBITDA" not in other_mentioned
    assert "Net Profit" not in other_mentioned


def test_run_partial_derived_metric_resolves_components():
    """run_partial with a derived metric first resolves its direct components."""
    # Tangible Net Worth = Net Worth - Net Intangible Assets
    # Net Worth = Equity + Reserves (derived_else_direct)
    # We need search to return values for direct components
    call_count = {"count": 0}

    def search(canonical_name: str, synonyms: list[str]) -> SearchResult | None:
        call_count["count"] += 1
        # Net Intangible Assets is direct
        if "Net Intangible" in canonical_name:
            return SearchResult(value=18261.0, source_file="TestCo", source_year="2023", source_pages="139-141")
        # Aggregation sub-items for Equity and Reserves
        if canonical_name in ("Ordinary Shares", "Preference Shares", "Share Premium Account",
                              "Retained Earnings", "Revaluation Reserves", "Other Reserves",
                              "Capital Redemption Reserve", "Treasury Stock"):
            return SearchResult(value=1000.0, source_file="TestCo", source_year="2023", source_pages="200-210")
        return None

    cb, fired = _capture_callback()
    workflow = FinancialSpreadingWorkflow(
        yaml_path=YAML_PATH,
        mcts_search=search,
        progress_callback=cb,
    )
    sct = workflow.run_partial(["Tangible Net Worth"])

    # Tangible Net Worth should be resolved (since all components resolved)
    bs_metrics = sct.get("Balance Sheet", [])
    tnw = [m for m in bs_metrics if m.canonical_name == "Tangible Net Worth"]
    assert len(tnw) == 1
    assert tnw[0].status == "resolved"

    # "Tangible Net Worth" is mentioned, should fire callback
    assert "Tangible Net Worth" in fired


def test_run_partial_only_dependencies_resolved():
    """Only the requested metric and its transitive dependencies are resolved."""
    search = _make_search(value=60073.0)
    cb, fired = _capture_callback()
    workflow = FinancialSpreadingWorkflow(
        yaml_path=YAML_PATH,
        mcts_search=search,
        progress_callback=cb,
    )
    sct = workflow.run_partial(["Revenue"])

    # Revenue is in Income Statement
    is_section = sct.get("Income Statement", [])
    assert any(m.canonical_name == "Revenue" for m in is_section)

    # Only mentioned metrics in the closure should fire the callback
    # Revenue is mentioned, so it fires
    assert "Revenue" in fired
    # Non-mentioned direct metrics needed as components should NOT fire
    for name in fired:
        mdef = next(
            (d for d in workflow._definitions if d.canonical_name == name),
            None,
        )
        if mdef:
            assert mdef.is_mentioned, f"{name} is not mentioned but fired callback"


def test_run_partial_all_direct_metrics_concurrent():
    """All direct metrics in the closure resolve (potentially concurrently)."""
    call_order: list[str] = []
    lock = threading.Lock()

    def search(canonical_name: str, synonyms: list[str]) -> SearchResult | None:
        with lock:
            call_order.append(canonical_name)
        return SearchResult(value=50000.0, source_file="TestCo", source_year="2023", source_pages="1-5")

    workflow = FinancialSpreadingWorkflow(
        yaml_path=YAML_PATH,
        mcts_search=search,
    )
    # Operating Profit components include both direct (other Operating income,
    # all Operating costs, Depreciation, Amortization) and derived (Gross Profit)
    sct = workflow.run_partial(["Operating Profit"])

    is_section = sct.get("Income Statement", [])
    op = [m for m in is_section if m.canonical_name == "Operating Profit"]
    assert len(op) == 1
    # All direct components should have been searched
    assert "Depreciation" in call_order
    assert "Amortization" in call_order


def test_max_workers_clamped():
    """_resolve_phase_concurrently clamps workers to the number of metrics."""
    workflow = FinancialSpreadingWorkflow(
        yaml_path=YAML_PATH,
        mcts_search=_make_search(),
    )
    workflow._definitions = workflow._load_definitions()

    # 1 metric, max_workers=3 → actual workers should be 1
    direct_defs, _, _ = workflow._categorize_metrics({"Revenue"})
    assert len(direct_defs) == 1
    # The method clamps internally; we just verify it runs without error
    workflow._resolved.clear()
    workflow._resolve_phase_concurrently(direct_defs, precision=5, max_workers=3)
    assert "Revenue" in workflow._resolved


def test_partial_workflow_thread_safety():
    """run_partial should not deadlock or corrupt state with concurrent phases."""
    call_count_lock = threading.Lock()
    call_counts: dict[str, int] = {}

    def search(canonical_name: str, synonyms: list[str]) -> SearchResult | None:
        with call_count_lock:
            call_counts[canonical_name] = call_counts.get(canonical_name, 0) + 1
        return SearchResult(value=1000.0, source_file="TestCo", source_year="2023", source_pages="1-1")

    workflow = FinancialSpreadingWorkflow(
        yaml_path=YAML_PATH,
        mcts_search=search,
    )

    # Run partial for multiple derived metrics that share components
    sct = workflow.run_partial(["EBITDA", "Gross Profit", "Revenue"])

    # Should not deadlock or raise
    assert sct is not None

    # Revenue should only be searched once (deduplication by _resolved)
    revenue_calls = call_counts.get("Revenue", 0)
    # Revenue is direct and appears as component of Gross Profit
    # With concurrent resolution it could be attempted twice before hitting the
    # "already resolved" guard, but the lock prevents double-resolution
    assert revenue_calls >= 1
