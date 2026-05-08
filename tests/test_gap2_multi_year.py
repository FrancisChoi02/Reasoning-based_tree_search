# Input: FinancialSpreadingWorkflow, mock MCTS search functions per year
# Output: Verifies run_for_years() resolves multiple years independently with
#   shared definition loading and returns distinct SCT tables (Gap 2).
# Position: Test for Gap 2 fix. If modified, update this header.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.financial_spreading.financial_spreading_workflow import (
    FinancialSpreadingWorkflow,
)
from utils.financial_spreading.resolve_metric import SearchResult


def _make_search(year_value: float):
    """Return an MCTS search function that always returns *year_value*."""

    def search(canonical_name: str, synonyms: list[str]) -> SearchResult | None:
        return SearchResult(value=year_value, source_file="TestCo", source_pages="1-2", source_year="2025")

    return search


def test_run_for_years_basic():
    """Gap 2: run_for_years() returns a dict keyed by year with SCT tables."""
    years = ["2023", "2024", "2025"]
    search_by_year = {yr: _make_search(i * 1000.0) for i, yr in enumerate(years)}

    workflow = FinancialSpreadingWorkflow(
        yaml_path="metric_definitions.yaml",
    )

    results = workflow.run_for_years(
        years=years,
        search_fn_by_year=search_by_year,
        precision=2,
    )

    assert isinstance(results, dict), f"Expected dict, got {type(results).__name__}"
    assert set(results.keys()) == set(years), (
        f"Expected keys {years}, got {list(results.keys())}"
    )

    # Each year should have the same SCT sections
    first_year_sections = set(results[years[0]].keys())
    for yr in years[1:]:
        assert set(results[yr].keys()) == first_year_sections, (
            f"Year {yr} sections differ from {years[0]}: "
            f"{set(results[yr].keys())} vs {first_year_sections}"
        )

    # Different years should produce different values (different search fns)
    revenue_2023 = _find_metric(results["2023"], "Revenue")
    revenue_2025 = _find_metric(results["2025"], "Revenue")
    assert revenue_2023 is not None and revenue_2025 is not None
    assert revenue_2023.value != revenue_2025.value, (
        "Different years with different search functions should produce "
        "different values"
    )

    print(f"[PASS] Gap 2: run_for_years() resolved {len(years)} years "
          f"with {len(first_year_sections)} sections each")


def test_run_for_years_empty_years_raises():
    """run_for_years() with empty list must raise ValueError."""
    workflow = FinancialSpreadingWorkflow(
        yaml_path="metric_definitions.yaml",
    )
    try:
        workflow.run_for_years([], search_fn_by_year={})
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    print("[PASS] Gap 2: empty years raises ValueError")


def _find_metric(sct_table: dict, canonical_name: str):
    """Find a metric by canonical_name across all sections in the SCT table."""
    for section_metrics in sct_table.values():
        for metric in section_metrics:
            if metric.canonical_name == canonical_name:
                return metric
    return None


if __name__ == "__main__":
    test_run_for_years_basic()
    test_run_for_years_empty_years_raises()
