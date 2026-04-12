# Input: SQLite database path and document primary key.
# Output: In-memory TreeNode graph with parent/children pointers and MCTS-ready state.
# Position: Tree data structure loaded from DB, used by MCTS engine. If modified, update this header and the parent folder's .md index.

import math
import sqlite3
from typing import Any, Dict, List, Optional


class TreeNode:
    """In-memory node with parent/children pointers and MCTS statistics."""

    __slots__ = (
        "node_pk", "doc_pk", "node_id", "title",
        "start_index", "end_index", "summary", "prefix_summary",
        "text_content", "depth", "child_order",
        "parent", "children",
        "visit_count", "value_sum",
    )

    def __init__(
        self,
        node_pk: int,
        doc_pk: int,
        node_id: str,
        title: str,
        start_index: int,
        end_index: int,
        summary: Optional[str] = None,
        prefix_summary: Optional[str] = None,
        text_content: Optional[str] = None,
        depth: int = 0,
        child_order: int = 0,
    ):
        self.node_pk = node_pk
        self.doc_pk = doc_pk
        self.node_id = node_id
        self.title = title
        self.start_index = start_index
        self.end_index = end_index
        self.summary = summary
        self.prefix_summary = prefix_summary
        self.text_content = text_content
        self.depth = depth
        self.child_order = child_order

        self.parent: Optional["TreeNode"] = None
        self.children: List["TreeNode"] = []

        # MCTS state
        self.visit_count: int = 0
        self.value_sum: float = 0.0

    @property
    def value(self) -> float:
        if self.visit_count == 0:
            return 0.0
        return self.value_sum / self.visit_count

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def ucb1(self, exploration_weight: float = 1.414) -> float:
        """Upper Confidence Bound 1 score for MCTS selection."""
        if self.visit_count == 0:
            return float("inf")
        if self.parent is None:
            return self.value
        return self.value + exploration_weight * math.sqrt(
            math.log(self.parent.visit_count) / self.visit_count
        )

    def best_child_ucb1(self, exploration_weight: float = 1.414) -> Optional["TreeNode"]:
        if not self.children:
            return None
        return max(self.children, key=lambda c: c.ucb1(exploration_weight))

    def best_child_value(self) -> Optional["TreeNode"]:
        if not self.children:
            return None
        return max(self.children, key=lambda c: c.value)

    def path_to_root(self) -> List["TreeNode"]:
        path: List["TreeNode"] = []
        node: Optional[TreeNode] = self
        while node is not None:
            path.append(node)
            node = node.parent
        return path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_pk": self.node_pk,
            "node_id": self.node_id,
            "title": self.title,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "summary": self.summary,
            "depth": self.depth,
            "child_order": self.child_order,
            "visit_count": self.visit_count,
            "value": round(self.value, 4),
            "children": [child.to_dict() for child in self.children],
        }

    def __repr__(self) -> str:
        return (
            f"TreeNode(pk={self.node_pk}, id={self.node_id}, "
            f"title={self.title!r}, children={len(self.children)})"
        )


def load_tree_from_db(
    doc_pk: int,
    db_path: str = "tree_poc.db",
) -> TreeNode:
    """
    Load all nodes for a document from DB and build an in-memory tree.

    Returns the root TreeNode. All nodes have parent/children pointers set.
    Children are ordered by child_order.
    """
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

    root: Optional[TreeNode] = None
    for row in rows:
        node = nodes_by_pk[row["node_pk"]]
        parent_pk = row["parent_node_pk"]
        if parent_pk is None:
            root = node
        elif parent_pk in nodes_by_pk:
            parent = nodes_by_pk[parent_pk]
            node.parent = parent
            parent.children.append(node)

    if root is None:
        raise ValueError(f"No root node (parent_node_pk=NULL) found for doc_pk={doc_pk}")

    return root


def count_nodes(root: TreeNode) -> int:
    """Count total nodes in the subtree."""
    total = 1
    for child in root.children:
        total += count_nodes(child)
    return total


def collect_leaves(root: TreeNode) -> List[TreeNode]:
    """Collect all leaf nodes from the subtree."""
    leaves: List[TreeNode] = []

    def _walk(node: TreeNode) -> None:
        if node.is_leaf:
            leaves.append(node)
        for child in node.children:
            _walk(child)

    _walk(root)
    return leaves


def max_depth(root: TreeNode) -> int:
    """Return the maximum depth in the tree."""
    if root.is_leaf:
        return root.depth
    return max(max_depth(child) for child in root.children)
