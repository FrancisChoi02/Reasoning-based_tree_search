# Input: company name, list of year periods, DB path
# Output: tree readiness report — doc_pk, node/leaf counts, errors per year
# Position: Pre-flight check run before kicking off the MCTS spread. If modified,
#   update this header and README_backend.md.

from __future__ import annotations

from typing import Any

from utils.database.db_manager import get_doc_by_company_year
from utils.tree_search_related.tree_node import collect_leaves
from utils.tree_search_related.mcts_search import _load_forest_from_db


MIN_NODES = 10
"""Minimum total nodes a tree must have to be considered adequate."""

MIN_LEAVES = 3
"""Minimum leaf nodes with text a tree must have to be searchable."""


def verify_trees_for_years(
    company: str,
    year_periods: list[str],
    db_path: str = "static/tree_poc.db",
) -> dict[str, Any]:
    """Verify that a document tree exists and is adequate for each year.

    Returns a dict keyed by year with status, doc_pk, node counts, or error.
    """
    results: dict[str, Any] = {}
    for year in year_periods:
        results[year] = _verify_single_tree(company, year, db_path)
    return results


def _verify_single_tree(
    company: str,
    year_period: str,
    db_path: str,
) -> dict[str, Any]:
    try:
        doc = get_doc_by_company_year(company, year_period, db_path=db_path)
        doc_pk = doc["doc_pk"]
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    try:
        roots = _load_forest_from_db(doc_pk=doc_pk, db_path=db_path)
    except Exception as exc:
        return {
            "status": "error",
            "doc_pk": doc_pk,
            "error": f"Failed to load tree: {exc}",
        }

    total_nodes = sum(1 for _ in _walk_all(roots))
    all_leaves = [leaf for root in roots for leaf in collect_leaves(root)]
    leaves_with_text = sum(1 for leaf in all_leaves if (leaf.text_content or "").strip())

    issues: list[str] = []
    if total_nodes < MIN_NODES:
        issues.append(
            f"Tree has only {total_nodes} nodes (minimum {MIN_NODES} required)"
        )
    if leaves_with_text < MIN_LEAVES:
        issues.append(
            f"Only {leaves_with_text} leaves have text content "
            f"(minimum {MIN_LEAVES} required)"
        )

    return {
        "status": "ok" if not issues else "degraded",
        "doc_pk": doc_pk,
        "total_nodes": total_nodes,
        "total_leaves": len(all_leaves),
        "leaves_with_text": leaves_with_text,
        "issues": issues,
    }


def _walk_all(roots):
    """Yield every TreeNode in the forest, depth-first."""
    for root in roots:
        yield root
        for child in _walk_children(root):
            yield child


def _walk_children(node):
    for child in node.children:
        yield child
        yield from _walk_children(child)
