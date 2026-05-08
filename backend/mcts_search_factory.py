# Input: company name, year period, DB path (per-search MCTSQuery kwargs)
# Output: MCTSSearchFn callable — (canonical_name, synonyms) -> SearchResult | None
# Position: Adapts MCTSQuery for the MetricResolver / FinancialSpreadingWorkflow
#   contract. If modified, update this header and README_backend.md.

from __future__ import annotations

import re
from typing import Any

from utils.financial_spreading.resolve_metric import MCTSSearchFn, SearchResult
from utils.tree_search_related.mcts_search import MCTSQuery


def make_mcts_search_fn(
    company: str,
    year_period: str,
    db_path: str = "static/tree_poc.db",
    *,
    per_call_instance: bool = False,
    **mcts_kwargs: Any,
) -> MCTSSearchFn:
    """Create a year-scoped MCTS search function for the financial spreading workflow.

    The returned callable matches ``MCTSSearchFn``: it accepts a canonical metric
    name plus a list of synonyms, runs MCTS over the document tree for the given
    company+year, and returns a ``SearchResult`` with the numeric value and source
    attribution metadata, or ``None`` on error.

    When ``per_call_instance`` is True, each call creates a fresh ``MCTSQuery``
    so concurrent callers do not share mutable tree state.  Use this for
    within-year concurrent metric resolution.
    """

    default_kwargs: dict[str, Any] = {
        "num_iterations": 10,
        "top_k": 3,
        "exploration_weight": 1.414,
        "max_workers": 3,
    }
    for key, value in default_kwargs.items():
        mcts_kwargs.setdefault(key, value)

    def _run_search(canonical_name: str, synonyms: list[str]) -> SearchResult | None:
        query = _build_search_query(canonical_name, synonyms)
        mcts = MCTSQuery(
            company=company,
            year_period=year_period,
            db_path=db_path,
            **mcts_kwargs,
        )
        try:
            result = mcts.search(query)
            answer = result.get("answer", "")
            value = _extract_numeric_value(str(answer))
            top_pages = ""
            sources = result.get("sources")
            if sources and len(sources) > 0:
                top_pages = str(sources[0].get("pages", ""))
            return SearchResult(
                value=value,
                source_file=company,
                source_year=year_period,
                source_pages=top_pages,
            )
        except Exception:
            return None

    if per_call_instance:
        return _run_search

    mcts = MCTSQuery(
        company=company,
        year_period=year_period,
        db_path=db_path,
        **mcts_kwargs,
    )

    def search(canonical_name: str, synonyms: list[str]) -> SearchResult | None:
        query = _build_search_query(canonical_name, synonyms)
        try:
            result = mcts.search(query)
            answer = result.get("answer", "")
            value = _extract_numeric_value(str(answer))
            top_pages = ""
            sources = result.get("sources")
            if sources and len(sources) > 0:
                top_pages = str(sources[0].get("pages", ""))
            return SearchResult(
                value=value,
                source_file=company,
                source_year=year_period,
                source_pages=top_pages,
            )
        except Exception:
            return None

    return search


def _build_search_query(canonical_name: str, synonyms: list[str]) -> str:
    """Build a focused MCTS query from the metric name and its synonym bank."""
    unique_synonyms: list[str] = []
    seen: set[str] = {canonical_name.lower()}
    for syn in synonyms:
        lower = syn.lower()
        if lower not in seen:
            seen.add(lower)
            unique_synonyms.append(syn)

    main = f"Find the exact numeric value of '{canonical_name}'"
    if unique_synonyms:
        alts = ", ".join(unique_synonyms[:6])
        main += f" (also known as: {alts})"
    return main + (
        ". Return only the numeric figure. If the value is presented with "
        "parentheses indicating a negative amount, treat it as negative."
    )


def _extract_numeric_value(text: str) -> float | None:
    """Pull the first plausible financial number out of an MCTS answer string.

    Handles commas, leading/trailing whitespace, parentheses-for-negative
    convention, and common suffixes like "million" or "billion".
    """
    if not text or not text.strip():
        return None

    cleaned = text.strip()
    multiplier = 1.0

    if re.search(r"\b(billion|bn)\b", cleaned, re.IGNORECASE):
        multiplier = 1_000_000_000.0
    elif re.search(r"\b(million|mm|mil)\b", cleaned, re.IGNORECASE):
        multiplier = 1_000_000.0
    elif re.search(r"\b(thousand|k)\b", cleaned, re.IGNORECASE):
        multiplier = 1_000.0

    cleaned = re.sub(r"(?<=\d),(?=\d)", "", cleaned)

    is_negative = False
    paren_match = re.search(r"\(\s*([\d,.]+)\s*\)", cleaned)
    if paren_match:
        is_negative = True
        cleaned = paren_match.group(1)

    match = re.search(r"-?[\d,.]+\.?\d*", cleaned)
    if not match:
        return None

    try:
        value = float(match.group(0).replace(",", ""))
    except ValueError:
        return None

    if is_negative:
        value = -abs(value)
    return round(value * multiplier, 2)
