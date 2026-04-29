# Input: SQLite document tree, Azure chat wrappers, and MCTS search prompts.
# Output: Forest-aware MCTS query engine that batch-evaluates same-frontier leaves concurrently and returns a synthesized answer with ranked source sections.
# Position: Query-time retrieval layer over the stored document tree. If modified, update this header and the parent folder's .md index.

import json
import sqlite3
from typing import Dict, List, Optional, Sequence, Set, Tuple

from utils.azure_openai.azure_openai import (
    ChatCompletionRequest,
    ChatCompletionResult,
    call_chat_completion,
    call_chat_completions_batch,
)
from utils.tree_search_related.pdf_json_prompt import (
    build_leaf_eval_prompt,
    build_prior_scoring_prompt,
    build_synthesis_prompt,
)
from utils.tree_search_related.tree_node import TreeNode, collect_leaves


def _load_forest_from_db(doc_pk: int, db_path: str = "tree_poc.db") -> List[TreeNode]:
    """Load all root nodes for a document from the SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM nodes WHERE doc_pk = ? ORDER BY depth, child_order, node_pk",
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
        parent_node_pk = row["parent_node_pk"]
        if parent_node_pk is None:
            roots.append(node)
            continue
        parent = nodes_by_pk.get(parent_node_pk)
        if parent is None:
            raise ValueError(
                f"Parent node missing for node_pk={node.node_pk}, parent_node_pk={parent_node_pk}"
            )
        node.parent = parent
        parent.children.append(node)

    if not roots:
        raise ValueError(f"No root nodes found for doc_pk={doc_pk}")

    roots.sort(key=lambda node: (node.child_order, node.node_pk))
    return roots


class MCTSQuery:
    """Run forest-aware MCTS over a stored document tree to answer one question."""

    def __init__(
        self,
        doc_pk: int,
        db_path: str = "tree_poc.db",
        num_iterations: int = 10,
        top_k: int = 3,
        exploration_weight: float = 1.414,
        max_eval_chars: int = 3000,
        max_workers: int = 4,
        virtual_visits: int = 3,
        verbose: bool = False,
    ):
        if num_iterations <= 0:
            raise ValueError("num_iterations must be greater than 0")
        if top_k <= 0:
            raise ValueError("top_k must be greater than 0")
        if exploration_weight < 0.0:
            raise ValueError("exploration_weight must be greater than or equal to 0")
        if max_eval_chars <= 0:
            raise ValueError("max_eval_chars must be greater than 0")
        if max_workers <= 0:
            raise ValueError("max_workers must be greater than 0")
        if virtual_visits <= 0:
            raise ValueError("virtual_visits must be greater than 0")

        self.doc_pk = doc_pk
        self.db_path = db_path
        self.num_iterations = num_iterations
        self.top_k = top_k
        self.exploration_weight = exploration_weight
        self.max_eval_chars = max_eval_chars
        self.max_workers = max_workers
        self.virtual_visits = virtual_visits
        self.verbose = verbose

        self.roots: List[TreeNode] = _load_forest_from_db(doc_pk=doc_pk, db_path=db_path)
        self._all_nodes: List[TreeNode] = []
        self._seeded_parent_keys: Set[str] = set()
        self._visited_leaf_keys: Set[str] = set()
        self._index_nodes()

    def search(self, query: str) -> Dict[str, object]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")

        self._reset_tree_state()
        self._seed_priors_for_roots(normalized_query)

        completed_iterations = 0
        while completed_iterations < self.num_iterations:
            frontier_batch = self._select_frontier_batch(
                normalized_query,
                remaining_iterations=self.num_iterations - completed_iterations,
            )
            scored_leaves = self._evaluate_frontier_batch(frontier_batch, normalized_query)
            self._commit_frontier_batch(scored_leaves)
            completed_iterations += len(scored_leaves)

            if self.verbose:
                batch_titles = [leaf.title for leaf, _ in scored_leaves]
                print(
                    f"[MCTS] batch_complete iterations={completed_iterations}/{self.num_iterations} "
                    f"batch_size={len(scored_leaves)} leaves={batch_titles}"
                )

        top_leaves = self._collect_top_k_leaves()
        answer = self._synthesize_answer(normalized_query, top_leaves)
        sources = [self._build_source_payload(leaf) for leaf in top_leaves]

        return {
            "query": normalized_query,
            "answer": answer,
            "sources": sources,
            "iterations": self.num_iterations,
            "visited_leaf_count": len(self._visited_leaf_keys),
        }

    def _index_nodes(self) -> None:
        self._all_nodes = []

        def _walk(node: TreeNode) -> None:
            self._all_nodes.append(node)
            for child in node.children:
                _walk(child)

        for root in self.roots:
            _walk(root)

    def _reset_tree_state(self) -> None:
        self._seeded_parent_keys.clear()
        self._visited_leaf_keys.clear()
        for node in self._all_nodes:
            node.visit_count = 0
            node.value_sum = 0.0

    def _seed_priors_for_roots(self, query: str) -> None:
        if len(self.roots) == 1:
            root = self.roots[0]
            root.visit_count = self.virtual_visits
            root.value_sum = float(self.virtual_visits)
            return
        self._seed_children(query, self.roots, parent_key="__forest__")

    def _select_leaf(self, query: str, reserved_leaf_keys: Optional[Set[str]] = None) -> Optional[TreeNode]:
        current = self._select_root(reserved_leaf_keys=reserved_leaf_keys)
        if current is None:
            return None
        while not current.is_leaf:
            parent_key = self._node_key(current)
            if parent_key not in self._seeded_parent_keys:
                self._seed_children(query, current.children, parent_key=parent_key)
            next_child = self._select_child_for_batch(
                current.children,
                reserved_leaf_keys=reserved_leaf_keys,
            )
            if next_child is None:
                return None
            current = next_child
        return current

    def _select_frontier_batch(
        self,
        query: str,
        *,
        remaining_iterations: int,
    ) -> List[TreeNode]:
        batch_size = min(self.max_workers, remaining_iterations)
        frontier_batch: List[TreeNode] = []
        reserved_leaf_keys: Set[str] = set()

        for _ in range(batch_size):
            leaf = self._select_leaf(query, reserved_leaf_keys=reserved_leaf_keys)
            if leaf is None:
                break
            leaf_key = self._node_key(leaf)
            if leaf_key in reserved_leaf_keys:
                raise ValueError(f"Duplicate leaf selected in frontier batch: {leaf_key}")
            reserved_leaf_keys.add(leaf_key)
            frontier_batch.append(leaf)

        if not frontier_batch:
            raise ValueError("Could not select any leaf for frontier batch")
        return frontier_batch

    def _select_child_for_batch(
        self,
        children: Sequence[TreeNode],
        *,
        reserved_leaf_keys: Optional[Set[str]] = None,
    ) -> Optional[TreeNode]:
        if not children:
            return None

        selectable_children = [
            child for child in children
            if not self._subtree_fully_reserved(child, reserved_leaf_keys)
        ]
        if not selectable_children:
            return None
        return max(selectable_children, key=lambda child: child.ucb1(self.exploration_weight))

    def _select_root(
        self,
        reserved_leaf_keys: Optional[Set[str]] = None,
    ) -> Optional[TreeNode]:
        if not self.roots:
            raise ValueError("No roots available for search")
        selectable_roots = [
            root for root in self.roots
            if not self._subtree_fully_reserved(root, reserved_leaf_keys)
        ]
        if not selectable_roots:
            return None
        if len(selectable_roots) == 1:
            return selectable_roots[0]
        return max(selectable_roots, key=lambda node: node.ucb1(self.exploration_weight))

    def _seed_children(self, query: str, children: Sequence[TreeNode], parent_key: str) -> None:
        if not children:
            raise ValueError(f"Cannot seed empty child list for parent_key={parent_key}")

        sibling_payload = [
            {
                "title": child.title,
                "path": self._node_path_text(child),
                "pages": self._format_pages(child),
            }
            for child in children
        ]
        prompt = build_prior_scoring_prompt(query, sibling_payload)
        response = call_chat_completion(
            ChatCompletionRequest(prompt=prompt, temperature=0.0),
            request_index=0,
            verbose=self.verbose,
        )
        raw_scores = self._parse_prior_scores(response.content)

        for child in children:
            prior_score = self._clamp_score(raw_scores.get(child.title, 0.0))
            child.visit_count += self.virtual_visits
            child.value_sum += prior_score * self.virtual_visits

        self._seeded_parent_keys.add(parent_key)

    def _evaluate_leaf(self, leaf: TreeNode, query: str) -> float:
        request = self._build_leaf_eval_request(leaf, query)
        response = call_chat_completion(
            request,
            request_index=0,
            verbose=self.verbose,
        )
        return self._parse_leaf_score(response)

    def _evaluate_frontier_batch(
        self,
        leaves: Sequence[TreeNode],
        query: str,
    ) -> List[Tuple[TreeNode, float]]:
        if not leaves:
            return []

        requests = [self._build_leaf_eval_request(leaf, query) for leaf in leaves]
        results = call_chat_completions_batch(
            requests,
            max_workers=min(self.max_workers, len(requests)),
            verbose=self.verbose,
        )
        if len(results) != len(leaves):
            raise ValueError(
                f"Frontier batch result count mismatch: expected {len(leaves)}, got {len(results)}"
            )

        scored_leaves: List[Tuple[TreeNode, float]] = []
        for expected_index, (leaf, result) in enumerate(zip(leaves, results)):
            if result.request_index != expected_index:
                raise ValueError(
                    "Frontier batch result order mismatch: "
                    f"expected request_index={expected_index}, got {result.request_index}"
                )
            scored_leaves.append((leaf, self._parse_leaf_score(result)))
        return scored_leaves

    def _commit_frontier_batch(
        self,
        scored_leaves: Sequence[Tuple[TreeNode, float]],
    ) -> None:
        for leaf, score in scored_leaves:
            self._backpropagate(leaf, score)
            self._visited_leaf_keys.add(self._node_key(leaf))
            if self.verbose:
                print(
                    f"[MCTS] committed leaf={leaf.title!r} score={score:.3f} "
                    f"visits={leaf.visit_count}"
                )

    def _build_leaf_eval_request(self, leaf: TreeNode, query: str) -> ChatCompletionRequest:
        text_head, text_tail = self._split_text_for_evaluation(leaf.text_content or "")
        prompt = build_leaf_eval_prompt(
            query=query,
            path=self._node_path_text(leaf),
            title=leaf.title,
            text_head=text_head,
            text_tail=text_tail,
            summary=leaf.summary,
        )
        return ChatCompletionRequest(prompt=prompt, temperature=0.0)

    def _parse_leaf_score(self, response: ChatCompletionResult) -> float:
        payload = self._parse_json_object(response.content)
        score = payload.get("score")
        if score is None:
            raise ValueError(f"Leaf evaluation response missing score: {response.content}")
        if isinstance(score, bool):
            raise ValueError(f"Leaf evaluation score must be numeric, got boolean: {response.content}")
        return self._clamp_score(float(score))

    def _backpropagate(self, leaf: TreeNode, score: float) -> None:
        current: Optional[TreeNode] = leaf
        while current is not None:
            current.visit_count += 1
            current.value_sum += score
            current = current.parent

    def _collect_top_k_leaves(self) -> List[TreeNode]:
        visited_leaves: List[TreeNode] = []
        for root in self.roots:
            for leaf in collect_leaves(root):
                if self._node_key(leaf) in self._visited_leaf_keys:
                    visited_leaves.append(leaf)

        if not visited_leaves:
            raise ValueError("MCTS completed without visiting any leaf")

        visited_leaves.sort(
            key=lambda leaf: (
                -leaf.value,
                -leaf.visit_count,
                leaf.start_index,
                leaf.node_pk,
            )
        )
        return visited_leaves[: self.top_k]

    def _synthesize_answer(self, query: str, top_leaves: Sequence[TreeNode]) -> str:
        if not top_leaves:
            raise ValueError("Cannot synthesize answer without source leaves")

        sections = []
        for leaf in top_leaves:
            full_text = (leaf.text_content or "").strip()
            if not full_text:
                full_text = leaf.summary or ""
            sections.append(
                {
                    "path": self._node_path_text(leaf),
                    "pages": self._format_pages(leaf),
                    "summary": leaf.summary or "",
                    "text": full_text,
                }
            )

        prompt = build_synthesis_prompt(query, sections)
        response = call_chat_completion(
            ChatCompletionRequest(prompt=prompt, temperature=0.0),
            request_index=0,
            verbose=self.verbose,
        )
        answer = (response.content or "").strip()
        if not answer:
            raise ValueError("Synthesis returned an empty answer")
        return answer

    def _build_source_payload(self, leaf: TreeNode) -> Dict[str, object]:
        return {
            "node_pk": leaf.node_pk,
            "title": leaf.title,
            "pages": self._format_pages(leaf),
            "score": round(leaf.value, 4),
            "visits": leaf.visit_count,
            "path": self._node_path(leaf),
        }

    def _node_path(self, node: Optional[TreeNode] = None) -> List[str]:
        if node is None:
            return []
        return [path_node.title for path_node in reversed(node.path_to_root())]

    def _node_path_text(self, node: TreeNode) -> str:
        return " > ".join(self._node_path(node))

    def _format_pages(self, node: TreeNode) -> str:
        return f"{node.start_index}-{node.end_index}"

    def _split_text_for_evaluation(self, text: str) -> Tuple[str, str]:
        normalized_text = text.strip()
        if not normalized_text:
            return "", ""

        if len(normalized_text) <= self.max_eval_chars:
            return normalized_text, ""

        head_chars = max(1, int(self.max_eval_chars * (2 / 3)))
        tail_chars = max(1, self.max_eval_chars - head_chars)
        return normalized_text[:head_chars], normalized_text[-tail_chars:]

    def _subtree_fully_reserved(
        self,
        node: TreeNode,
        reserved_leaf_keys: Optional[Set[str]],
    ) -> bool:
        if not reserved_leaf_keys:
            return False
        if node.is_leaf:
            return self._node_key(node) in reserved_leaf_keys
        return all(
            self._subtree_fully_reserved(child, reserved_leaf_keys)
            for child in node.children
        )

    def _parse_prior_scores(self, raw_text: str) -> Dict[str, float]:
        payload = self._parse_json_array(raw_text)
        prior_scores: Dict[str, float] = {}
        for item in payload:
            title = item.get("title")
            if not title:
                continue
            prior_score = item.get("prior_score")
            if prior_score is None:
                continue
            prior_scores[str(title)] = float(prior_score)
        return prior_scores

    def _parse_json_object(self, raw_text: str) -> Dict[str, object]:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON object response: {raw_text}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object response, got: {type(payload).__name__}")
        return payload

    def _parse_json_array(self, raw_text: str) -> List[Dict[str, object]]:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON array response: {raw_text}") from exc
        if not isinstance(payload, list):
            raise ValueError(f"Expected JSON array response, got: {type(payload).__name__}")
        normalized_items: List[Dict[str, object]] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError(f"Expected JSON object inside array, got: {type(item).__name__}")
            normalized_items.append(item)
        return normalized_items

    def _clamp_score(self, score: float) -> float:
        return max(0.0, min(1.0, score))

    def _node_key(self, node: TreeNode) -> str:
        return f"{node.doc_pk}:{node.node_pk}"
