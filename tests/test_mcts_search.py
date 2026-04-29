# Input: Query text, document identifier, SQLite DB path, and MCTS search configuration.
# Output: Runs a root-level MCTS document search smoke test and prints answer/source diagnostics with basic pass/fail checks.
# Position: Root-level manual smoke test runner for utils.tree_search_related.mcts_search. If modified, update this header and the parent folder's .md index.

import argparse
import sys
import time
from typing import Optional

from utils.database.db_manager import get_document
from utils.tree_search_related.mcts_search import MCTSQuery

#  Run it from the repo root with:        
                                 
#   python test_mcts_search.py --db-path verify_test.db --doc-pk 1 --query "What was Unilever's revenue in 2022?" --iterations 10 --top-k 3
#   --verbose                                        
                                                                                                                                             
#   Yes, the last failure looked like an external deployment/runtime issue, not a Python wiring issue.                                                                                                                                                      
#   

def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError("value must be greater than or equal to 0")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a root-level MCTS document search smoke test"
    )
    parser.add_argument(
        "--db-path",
        default="verify_test.db",
        help="SQLite database path",
    )
    parser.add_argument(
        "--doc-pk",
        type=_positive_int,
        help="Document primary key to search",
    )
    parser.add_argument(
        "--doc-name",
        help="Document name to search when doc_pk is not provided",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Question to ask against the document tree",
    )
    parser.add_argument(
        "--iterations",
        type=_positive_int,
        default=10,
        help="Number of MCTS iterations",
    )
    parser.add_argument(
        "--top-k",
        type=_positive_int,
        default=3,
        help="Number of top leaves to use for synthesis",
    )
    parser.add_argument(
        "--max-workers",
        type=_positive_int,
        default=4,
        help="Maximum number of concurrent workers used for same-frontier leaf evaluation",
    )
    parser.add_argument(
        "--exploration-weight",
        type=_non_negative_float,
        default=1.414,
        help="UCB1 exploration weight",
    )
    parser.add_argument(
        "--max-eval-chars",
        type=_positive_int,
        default=3000,
        help="Maximum total characters used when scoring a leaf",
    )
    parser.add_argument(
        "--virtual-visits",
        type=_positive_int,
        default=3,
        help="Virtual visits used for prior seeding",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra result details",
    )
    return parser.parse_args()


def resolve_doc_pk(*, db_path: str, doc_pk: Optional[int], doc_name: Optional[str]) -> int:
    if doc_pk is not None:
        get_document(doc_pk, db_path=db_path)
        return doc_pk

    if not doc_name:
        raise ValueError("Either --doc-pk or --doc-name must be provided")

    document = get_document(doc_name, db_path=db_path)
    return int(document["doc_pk"])


def main() -> int:
    args = parse_args()

    try:
        doc_pk = resolve_doc_pk(
            db_path=args.db_path,
            doc_pk=args.doc_pk,
            doc_name=args.doc_name,
        )
    except Exception as exc:
        print(f"[FAIL] Document lookup failed: {exc}")
        return 1

    searcher = MCTSQuery(
        doc_pk=doc_pk,
        db_path=args.db_path,
        num_iterations=args.iterations,
        top_k=args.top_k,
        exploration_weight=args.exploration_weight,
        max_eval_chars=args.max_eval_chars,
        max_workers=args.max_workers,
        virtual_visits=args.virtual_visits,
        verbose=args.verbose,
    )

    print("=== MCTS Search Smoke Test ===")
    print(f"db_path: {args.db_path}")
    print(f"doc_pk: {doc_pk}")
    print(f"iterations: {args.iterations}")
    print(f"top_k: {args.top_k}")
    print(f"max_workers: {args.max_workers}")
    print(f"query: {args.query}")

    started_at = time.perf_counter()
    try:
        result = searcher.search(args.query)
    except Exception as exc:
        print(f"[FAIL] MCTS search crashed: {exc}")
        return 1
    elapsed_seconds = time.perf_counter() - started_at

    answer = (result.get("answer") or "").strip()
    sources = result.get("sources") or []
    visited_leaf_count = int(result.get("visited_leaf_count") or 0)
    iterations = int(result.get("iterations") or 0)

    print("\n=== Answer ===")
    print(answer)

    print("\n=== Sources ===")
    for index, source in enumerate(sources, start=1):
        print(
            f"[{index}] title={source.get('title')!r} "
            f"pages={source.get('pages')} score={source.get('score')} "
            f"visits={source.get('visits')} path={source.get('path')}"
        )

    print("\n=== Summary ===")
    print(f"elapsed_seconds: {elapsed_seconds:.3f}")
    print(f"iterations: {iterations}")
    print(f"visited_leaf_count: {visited_leaf_count}")
    print(f"source_count: {len(sources)}")

    if args.verbose:
        print("\n=== Full Result ===")
        print(result)

    errors = []
    if not answer:
        errors.append("Answer is empty")
    if iterations != args.iterations:
        errors.append(
            f"Iteration mismatch: expected {args.iterations}, got {iterations}"
        )
    if visited_leaf_count <= 0:
        errors.append("No leaves were visited")
    if not sources:
        errors.append("No sources returned")

    if errors:
        print("\n=== Errors ===")
        for error in errors:
            print(f"- {error}")
        print("\n[FAIL] MCTS search smoke test failed.")
        return 1

    print("\n[PASS] MCTS search smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
