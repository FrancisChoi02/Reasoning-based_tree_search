# Input: Existing JSON file path (output_json_format) and optional DB path.
# Output: Round-trip verification — JSON→DB (raw + nodes), DB→in-memory tree, with printed diagnostics.
# Position: Verification script for the JSON→DB→Tree pipeline. If modified, update this header and the parent folder's .md index.

import argparse
import copy
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List

from utils.database.db_manager import load_json_to_db, get_document
from utils.tree_search_related.tree_node import (
    TreeNode,
    count_nodes,
    collect_leaves,
    max_depth,
)


def _count_json_records(records: list) -> int:
    """Recursively count all nodes in the records list."""
    total = 0
    for rec in records:
        total += 1
        children = rec.get("nodes", [])
        if children:
            total += _count_json_records(children)
    return total


def _load_forest_from_db(doc_pk: int, db_path: str = "tree_poc.db") -> List[TreeNode]:
    """Load all root nodes for a document. Returns a list of root TreeNodes."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM nodes WHERE doc_pk = ? ORDER BY depth, child_order",
        (doc_pk,),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        raise ValueError(f"No nodes found for doc_pk={doc_pk}")

    nodes_by_pk: Dict[int, TreeNode] = {}
    for row in rows:
        node = TreeNode(
            node_pk=row["node_pk"],
            doc_pk=row["doc_pk"],
            node_id=row["node_id"],
            title=row["title"],
            start_index=row["start_index"],
            end_index=row["end_index"],
            summary=row["summary"],
            prefix_summary=row["prefix_summary"],
            text_content=row["text_content"],
            depth=row["depth"],
            child_order=row["child_order"],
        )
        nodes_by_pk[row["node_pk"]] = node

    roots: List[TreeNode] = []
    for row in rows:
        node = nodes_by_pk[row["node_pk"]]
        parent_pk = row["parent_node_pk"]
        if parent_pk is None:
            roots.append(node)
        elif parent_pk in nodes_by_pk:
            parent = nodes_by_pk[parent_pk]
            node.parent = parent
            parent.children.append(node)

    return roots


def verify_raw_json(db_path: str, doc_pk: int, original_data: dict) -> bool:
    """Verify raw_json stored in DB matches the original data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT raw_json FROM documents WHERE doc_pk = ?", (doc_pk,))
    row = cursor.fetchone()
    conn.close()

    if row is None:
        print("  [FAIL] No raw_json found in documents table")
        return False

    stored = json.loads(row[0])
    if stored == original_data:
        print(f"  [OK] raw_json matches original ({len(row[0])} chars)")
        return True
    else:
        print("  [FAIL] raw_json does NOT match original (data mutated by _assign_node_ids)")
        return False


def verify_node_count(db_path: str, doc_pk: int, expected: int) -> bool:
    """Verify node count in DB matches expected."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM nodes WHERE doc_pk = ?", (doc_pk,))
    actual = cursor.fetchone()[0]
    conn.close()

    if actual == expected:
        print(f"  [OK] DB node count: {actual} (matches expected)")
        return True
    else:
        print(f"  [FAIL] DB node count: {actual}, expected: {expected}")
        return False


def verify_tree_integrity(roots: List[TreeNode], expected_node_count: int) -> bool:
    """Verify in-memory tree/forest structure is consistent."""
    all_pass = True
    total_in_tree = sum(count_nodes(r) for r in roots)

    print(f"  Root nodes : {len(roots)}")
    print(f"  Total nodes: {total_in_tree}")
    print(f"  Leaves     : {sum(len(collect_leaves(r)) for r in roots)}")
    print(f"  Max depth  : {max(max_depth(r) for r in roots)}")

    if total_in_tree != expected_node_count:
        print(f"  [FAIL] Tree node count {total_in_tree} != expected {expected_node_count}")
        all_pass = False
    else:
        print(f"  [OK] Node count matches")

    for root in roots:
        for child in root.children:
            if child.parent is not root:
                print(f"  [FAIL] Broken parent pointer on child {child.title!r}")
                all_pass = False
                break

    if all_pass and len(roots) > 1:
        print(f"  [OK] Forest of {len(roots)} trees, all parent/child pointers consistent")
    elif all_pass:
        print(f"  [OK] Single tree, parent/child pointers consistent")

    return all_pass


def print_tree_preview(root: TreeNode, max_depth_show: int = 2) -> None:
    """Print a compact tree preview up to max_depth_show levels."""
    def _walk(node: TreeNode, indent: str = "", is_last: bool = True) -> None:
        connector = "└── " if is_last else "├── "
        prefix = indent + connector if node.parent is not None else ""
        label = f"{node.title!r} (id={node.node_id}, children={len(node.children)})"
        print(f"  {prefix}{label}")
        if node.depth >= max_depth_show and node.children:
            print(f"  {indent}{'    ' if is_last else '│   '}... ({len(node.children)} children hidden)")
            return
        for i, child in enumerate(node.children):
            is_child_last = i == len(node.children) - 1
            child_indent = indent + ("    " if is_last else "│   ") if node.parent is not None else "  "
            _walk(child, child_indent, is_child_last)

    _walk(root)


def run_verification(json_path: str, db_path: str = "verify_test.db") -> bool:
    """Full round-trip verification. Returns True if all checks pass."""
    path = Path(json_path)
    if not path.is_file():
        print(f"[ERROR] JSON file not found: {json_path}")
        return False

    print(f"[*] Loading JSON: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data_snapshot = copy.deepcopy(data)

    records = data.get("records") or data.get("structure", [])
    expected_nodes = _count_json_records(records)
    json_format = "records" if "records" in data else "structure"
    print(f"    Format: {json_format}, top-level entries: {len(records)}, total nodes: {expected_nodes}")

    # Step 1: Store in DB
    print("\n[1/3] Storing JSON into DB (raw_json + nodes)")
    result = load_json_to_db(data, db_path=db_path, verbose=True)
    doc_pk = result["doc_pk"]
    db_node_count = result["node_count"]
    print(f"    doc_pk={doc_pk}, stored nodes={db_node_count}")

    # Step 2: Verify DB content
    print("\n[2/3] Verifying DB content")
    all_pass = True
    all_pass &= verify_raw_json(db_path, doc_pk, data_snapshot)
    all_pass &= verify_node_count(db_path, doc_pk, expected_nodes)

    doc = get_document(doc_pk, db_path=db_path)
    print(f"  [OK] Document query: name={doc['doc_name']!r}, checksum={doc['checksum'][:12]}...")

    # Step 3: Load tree(s) from DB and verify
    print("\n[3/3] Loading tree(s) from DB into memory")
    roots = _load_forest_from_db(doc_pk, db_path=db_path)
    all_pass &= verify_tree_integrity(roots, expected_nodes)

    # Print preview: show first 5 roots (or the single root expanded)
    print()
    if len(roots) == 1:
        print_tree_preview(roots[0])
    else:
        print(f"  Forest preview (first 5 of {len(roots)} roots):")
        for root in roots[:5]:
            node_count = count_nodes(root)
            print(f"  ├─ {root.title!r} (id={root.node_id}, subtree={node_count})")
        if len(roots) > 5:
            print(f"  └─ ... {len(roots) - 5} more roots")

    print()
    if all_pass:
        print("[PASS] All verifications passed.")
    else:
        print("[FAIL] Some verifications failed.")
    return all_pass


if __name__ == "__main__":
    # parser = argparse.ArgumentParser(description="Verify JSON→DB→Tree round-trip pipeline")
    # parser.add_argument("json_path", help="Path to the extracted JSON file")
    # parser.add_argument("--db-path", default="verify_test.db", help="DB file path (default: verify_test.db)")
    # args = parser.parse_args()

    json_path = "static/Unilever - FY22_20260412_2248.json"
    db_path = "verify_test.db"

    # Remove existing test DB to ensure a fresh start for verification
    if Path(db_path).exists():
        Path(db_path).unlink()

    success = run_verification(json_path=json_path, db_path=db_path)
    sys.exit(0 if success else 1)

