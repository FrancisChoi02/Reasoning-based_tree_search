# Input: compute_dependency_closure from financial_spreading_workflow,
#   MetricDefinition, in-memory YAML-like aggregation dicts
# Output: Deterministic unit coverage for transitive metric dependency closure
# Position: Gap 5 — validates that partial-metric requests resolve only needed
#   dependencies. If modified, update this header and the parent folder's .md index.

from utils.financial_spreading.financial_spreading_workflow import (
    compute_dependency_closure,
)
from models.MetricDefinition import MetricDefinition


def _make_def(name: str, input_type: str = "direct", components: list[str] | None = None) -> MetricDefinition:
    return MetricDefinition(
        canonical_name=name,
        input_type=input_type,
        metric_type="absolute",
        statement_type="Income Statement",
        is_mentioned=False,
        component_metrics=components or [],
        derivation_code={"formula": " + ".join(components or []), "components": components or []},
    )


def test_single_direct_metric_closure_is_self():
    """A direct metric has no component dependencies — closure is just itself."""
    defs = [_make_def("Revenue")]
    needed = compute_dependency_closure({"Revenue"}, defs, {})
    assert needed == {"Revenue"}


def test_derived_metric_closure_includes_components():
    """A derived metric's closure walks transitively through all components."""
    defs = [
        _make_def("Gross Profit", input_type="derived_else_direct", components=["Revenue", "Cost of Sales"]),
        _make_def("Revenue"),
        _make_def("Cost of Sales"),
    ]
    needed = compute_dependency_closure({"Gross Profit"}, defs, {})
    assert needed == {"Gross Profit", "Revenue", "Cost of Sales"}


def test_deeply_nested_closure():
    """A 3-level dependency chain is fully traversed."""
    defs = [
        _make_def("EBITDA", input_type="derived_else_direct",
                  components=["Profit before Taxes", "Interest Expense (Net)", "Depreciation", "Amortization"]),
        _make_def("Interest Expense (Net)", input_type="derived_else_direct",
                  components=["Interest Paid", "Interest Received"]),
        _make_def("Profit before Taxes"),
        _make_def("Depreciation"),
        _make_def("Amortization"),
        _make_def("Interest Paid"),
        _make_def("Interest Received"),
    ]
    needed = compute_dependency_closure({"EBITDA"}, defs, {})
    assert needed == {
        "EBITDA", "Profit before Taxes", "Interest Expense (Net)",
        "Depreciation", "Amortization", "Interest Paid", "Interest Received",
    }


def test_multiple_metrics_union_of_closures():
    """Two independent metrics produce the union of their dependency sets."""
    defs = [
        _make_def("Revenue"),
        _make_def("Operating cashflow"),
        _make_def("Free cashflow", input_type="derived",
                  components=["Operating cashflow", "Capital Expenditure", "w/w Dividends"]),
        _make_def("Capital Expenditure"),
        _make_def("w/w Dividends"),
    ]
    needed = compute_dependency_closure({"Revenue", "Free cashflow"}, defs, {})
    assert needed == {
        "Revenue", "Free cashflow", "Operating cashflow",
        "Capital Expenditure", "w/w Dividends",
    }


def test_aggregation_sub_items_included():
    """Metrics that depend on aggregation totals pull in sub-items."""
    defs = [
        _make_def("Net Worth", input_type="derived_else_direct",
                  components=["Equity", "Reserves"]),
    ]
    aggs = {
        "Equity": {
            "components": [
                {"metric": "Ordinary Shares", "sign": 1},
                {"metric": "Preference Shares", "sign": 1},
            ],
        },
        "Reserves": {
            "components": [
                {"metric": "Retained Earnings", "sign": 1},
                {"metric": "Share Premium Account", "sign": 1},
            ],
        },
    }
    needed = compute_dependency_closure({"Net Worth"}, defs, aggs)
    assert needed == {
        "Net Worth", "Equity", "Reserves",
        "Ordinary Shares", "Preference Shares",
        "Retained Earnings", "Share Premium Account",
    }


def test_total_ext_funded_debt_closure():
    """Total Ext. Funded Debt depends on Short Term Debt + Long Term Debt aggregations."""
    defs = [
        _make_def("Total Ext. Funded Debt", input_type="derived",
                  components=["Short Term Debt", "Long Term Debt"]),
    ]
    aggs = {
        "Short Term Debt": {
            "components": [
                {"metric": "Overdrafts", "sign": 1},
                {"metric": "Loans < 1 year - Unsecured", "sign": 1},
            ],
        },
        "Long Term Debt": {
            "components": [
                {"metric": "Loans > 1 year - Secured", "sign": 1},
                {"metric": "Subordinated Debt", "sign": 1},
            ],
        },
    }
    needed = compute_dependency_closure({"Total Ext. Funded Debt"}, defs, aggs)
    assert needed == {
        "Total Ext. Funded Debt", "Short Term Debt", "Long Term Debt",
        "Overdrafts", "Loans < 1 year - Unsecured",
        "Loans > 1 year - Secured", "Subordinated Debt",
    }


def test_empty_request_returns_empty():
    """An empty request set produces an empty closure."""
    defs = [_make_def("Revenue")]
    needed = compute_dependency_closure(set(), defs, {})
    assert needed == set()


def test_unknown_metric_returned_as_is():
    """A metric not in definitions or aggregations is kept in the closure set."""
    defs = [_make_def("Revenue")]
    needed = compute_dependency_closure({"NonExistentMetric"}, defs, {})
    assert needed == {"NonExistentMetric"}


def test_aggregation_without_components():
    """Aggregation entry with no components adds only the aggregation name."""
    defs = [
        _make_def("SomeDerived", input_type="derived", components=["EmptyAgg"]),
    ]
    aggs = {"EmptyAgg": {}}
    needed = compute_dependency_closure({"SomeDerived"}, defs, aggs)
    assert needed == {"SomeDerived", "EmptyAgg"}
