# Input: In-memory TreeNode fixtures, monkeypatched Azure chat batch wrappers, and MCTS query methods.
# Output: Deterministic unit coverage for frontier-batched MCTS selection, batched evaluation, iteration accounting, and explicit failure behavior.
# Position: Stdlib unittest coverage for utils.tree_search_related.mcts_search frontier batching. If modified, update this header and the parent folder's .md index.

from types import MethodType
from unittest import TestCase, main
from unittest.mock import patch

from utils.azure_openai.azure_openai import BatchChatCompletionError, ChatCompletionResult
from utils.tree_search_related.mcts_search import MCTSQuery
from utils.tree_search_related.tree_node import TreeNode


def _make_leaf(*, node_pk: int, title: str, score_seed: float = 0.5) -> TreeNode:
    leaf = TreeNode(
        node_pk=node_pk,
        doc_pk=1,
        node_id=str(node_pk),
        title=title,
        start_index=node_pk,
        end_index=node_pk,
        summary=f"summary for {title}",
        text_content=f"text for {title}",
        depth=1,
        child_order=node_pk,
    )
    leaf.visit_count = 1
    leaf.value_sum = score_seed
    return leaf


def _make_query_with_root(*, leaves: list[TreeNode], max_workers: int = 4) -> MCTSQuery:
    root = TreeNode(
        node_pk=100,
        doc_pk=1,
        node_id="root",
        title="Root",
        start_index=1,
        end_index=10,
        summary="root",
        text_content="root text",
        depth=0,
        child_order=0,
    )
    root.visit_count = 10
    root.value_sum = 10.0
    for index, leaf in enumerate(leaves):
        leaf.parent = root
        leaf.child_order = index
        root.children.append(leaf)

    query = object.__new__(MCTSQuery)
    query.doc_pk = 1
    query.db_path = "unused.db"
    query.num_iterations = 4
    query.top_k = 2
    query.exploration_weight = 1.414
    query.max_eval_chars = 3000
    query.max_workers = max_workers
    query.virtual_visits = 3
    query.verbose = False
    query.roots = [root]
    query._all_nodes = [root, *leaves]
    query._seeded_parent_keys = {query._node_key(root)}
    query._visited_leaf_keys = set()
    return query


class TestMCTSConcurrency(TestCase):
    def test_frontier_batch_selects_unique_leaves_per_iteration(self) -> None:
        first_leaf = _make_leaf(node_pk=1, title="Leaf A", score_seed=0.9)
        second_leaf = _make_leaf(node_pk=2, title="Leaf B", score_seed=0.8)
        query = _make_query_with_root(leaves=[first_leaf, second_leaf], max_workers=2)

        frontier_batch = query._select_frontier_batch(
            "Which leaf is relevant?",
            remaining_iterations=2,
        )

        self.assertEqual([leaf.node_pk for leaf in frontier_batch], [1, 2])
        self.assertEqual(len({query._node_key(leaf) for leaf in frontier_batch}), 2)

    def test_frontier_batch_updates_iteration_accounting_once_per_leaf(self) -> None:
        first_leaf = _make_leaf(node_pk=1, title="Leaf A", score_seed=0.2)
        second_leaf = _make_leaf(node_pk=2, title="Leaf B", score_seed=0.3)
        query = _make_query_with_root(leaves=[first_leaf, second_leaf], max_workers=2)

        scored_leaves = [
            (first_leaf, 0.6),
            (second_leaf, 0.4),
        ]

        query._commit_frontier_batch(scored_leaves)

        root = query.roots[0]
        self.assertEqual(root.visit_count, 12)
        self.assertAlmostEqual(root.value_sum, 11.0)
        self.assertEqual(first_leaf.visit_count, 2)
        self.assertAlmostEqual(first_leaf.value_sum, 0.8)
        self.assertEqual(second_leaf.visit_count, 2)
        self.assertAlmostEqual(second_leaf.value_sum, 0.7)
        self.assertEqual(
            query._visited_leaf_keys,
            {query._node_key(first_leaf), query._node_key(second_leaf)},
        )

    def test_frontier_batch_with_max_workers_one_uses_batched_path(self) -> None:
        leaf = _make_leaf(node_pk=1, title="Leaf A")
        query = _make_query_with_root(leaves=[leaf], max_workers=1)
        captured_request_counts: list[int] = []
        captured_worker_counts: list[int] = []

        def fake_batch(requests, *, max_workers, verbose):
            captured_request_counts.append(len(requests))
            captured_worker_counts.append(max_workers)
            return [
                ChatCompletionResult(
                    content='{"thinking": "ok", "score": 0.75}',
                    usage={},
                    finish_reason="stop",
                    request_index=0,
                )
            ]

        with patch(
            "utils.tree_search_related.mcts_search.call_chat_completions_batch",
            fake_batch,
        ):
            scored_leaves = query._evaluate_frontier_batch([leaf], "What matters?")

        self.assertEqual(captured_request_counts, [1])
        self.assertEqual(captured_worker_counts, [1])
        self.assertEqual(scored_leaves, [(leaf, 0.75)])

    def test_frontier_batch_preserves_leaf_result_mapping(self) -> None:
        first_leaf = _make_leaf(node_pk=1, title="Leaf A")
        second_leaf = _make_leaf(node_pk=2, title="Leaf B")
        query = _make_query_with_root(leaves=[first_leaf, second_leaf], max_workers=2)

        def fake_batch(requests, *, max_workers, verbose):
            return [
                ChatCompletionResult(
                    content='{"thinking": "first", "score": 0.25}',
                    usage={},
                    finish_reason="stop",
                    request_index=0,
                ),
                ChatCompletionResult(
                    content='{"thinking": "second", "score": 0.75}',
                    usage={},
                    finish_reason="stop",
                    request_index=1,
                ),
            ]

        with patch(
            "utils.tree_search_related.mcts_search.call_chat_completions_batch",
            fake_batch,
        ):
            scored_leaves = query._evaluate_frontier_batch(
                [first_leaf, second_leaf],
                "What matters?",
            )

        self.assertEqual(scored_leaves, [(first_leaf, 0.25), (second_leaf, 0.75)])

    def test_frontier_batch_rejects_result_order_mismatch(self) -> None:
        first_leaf = _make_leaf(node_pk=1, title="Leaf A")
        second_leaf = _make_leaf(node_pk=2, title="Leaf B")
        query = _make_query_with_root(leaves=[first_leaf, second_leaf], max_workers=2)

        def fake_batch(requests, *, max_workers, verbose):
            return [
                ChatCompletionResult(
                    content='{"thinking": "second", "score": 0.75}',
                    usage={},
                    finish_reason="stop",
                    request_index=1,
                ),
                ChatCompletionResult(
                    content='{"thinking": "first", "score": 0.25}',
                    usage={},
                    finish_reason="stop",
                    request_index=0,
                ),
            ]

        with patch(
            "utils.tree_search_related.mcts_search.call_chat_completions_batch",
            fake_batch,
        ):
            with self.assertRaisesRegex(ValueError, "request_index"):
                query._evaluate_frontier_batch([first_leaf, second_leaf], "What matters?")

    def test_frontier_batch_rejects_boolean_scores(self) -> None:
        leaf = _make_leaf(node_pk=1, title="Leaf A")
        query = _make_query_with_root(leaves=[leaf], max_workers=1)
        response = ChatCompletionResult(
            content='{"thinking": "bad", "score": true}',
            usage={},
            finish_reason="stop",
            request_index=0,
        )

        with self.assertRaisesRegex(ValueError, "boolean"):
            query._parse_leaf_score(response)

    def test_frontier_batch_failure_is_explicit(self) -> None:
        leaf = _make_leaf(node_pk=1, title="Leaf A")
        query = _make_query_with_root(leaves=[leaf], max_workers=1)

        def fail_batch(requests, *, max_workers, verbose):
            raise BatchChatCompletionError("batched request failed")

        with patch(
            "utils.tree_search_related.mcts_search.call_chat_completions_batch",
            fail_batch,
        ):
            with self.assertRaises(BatchChatCompletionError):
                query._evaluate_frontier_batch([leaf], "What matters?")

    def test_search_consumes_iterations_by_evaluated_leaf_count(self) -> None:
        leaf_a = _make_leaf(node_pk=1, title="Leaf A")
        leaf_b = _make_leaf(node_pk=2, title="Leaf B")
        query = _make_query_with_root(leaves=[leaf_a, leaf_b], max_workers=2)
        query.num_iterations = 3

        frontier_calls: list[int] = []
        committed_batch_sizes: list[int] = []

        def fake_reset_tree_state(self) -> None:
            self._visited_leaf_keys.clear()

        def fake_seed_priors_for_roots(self, query_text: str) -> None:
            return None

        def fake_select_frontier_batch(self, query_text: str, *, remaining_iterations: int):
            frontier_calls.append(remaining_iterations)
            if remaining_iterations == 3:
                return [leaf_a, leaf_b]
            return [leaf_a]

        def fake_evaluate_frontier_batch(self, leaves, query_text: str):
            return [(leaf, 0.5) for leaf in leaves]

        def fake_commit_frontier_batch(self, scored_leaves) -> None:
            committed_batch_sizes.append(len(scored_leaves))
            for leaf, _ in scored_leaves:
                self._visited_leaf_keys.add(self._node_key(leaf))

        def fake_collect_top_k_leaves(self):
            return [leaf_a]

        def fake_synthesize_answer(self, query_text: str, top_leaves):
            return "answer"

        query._reset_tree_state = MethodType(fake_reset_tree_state, query)
        query._seed_priors_for_roots = MethodType(fake_seed_priors_for_roots, query)
        query._select_frontier_batch = MethodType(fake_select_frontier_batch, query)
        query._evaluate_frontier_batch = MethodType(fake_evaluate_frontier_batch, query)
        query._commit_frontier_batch = MethodType(fake_commit_frontier_batch, query)
        query._collect_top_k_leaves = MethodType(fake_collect_top_k_leaves, query)
        query._synthesize_answer = MethodType(fake_synthesize_answer, query)

        result = query.search("What matters?")

        self.assertEqual(frontier_calls, [3, 1])
        self.assertEqual(committed_batch_sizes, [2, 1])
        self.assertEqual(result["iterations"], 3)
        self.assertEqual(result["visited_leaf_count"], 2)


if __name__ == "__main__":
    main()
