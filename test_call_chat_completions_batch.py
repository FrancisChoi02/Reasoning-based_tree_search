# Input: CLI args for batch size, worker count, temperature, prefix, and Azure OpenAI environment-backed chat wrapper.
# Output: Executes a direct concurrent batch chat smoke test and prints pass/fail summary with ordered result checks.
# Position: Root-level manual test runner for utils.azure_openai.azure_openai.call_chat_completions_batch. If modified, update this header and the parent folder's .md index.

import argparse
import sys
import time
from typing import List, Tuple

from utils.azure_openai.azure_openai import (
    ChatCompletionRequest,
    ChatCompletionResult,
    call_chat_completions_batch,
)


DEFAULT_PREFIX = "BATCH_TEST_OK"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def _temperature(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0 or parsed > 2.0:
        raise argparse.ArgumentTypeError("temperature must be between 0.0 and 2.0")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a direct concurrent batch chat completion test"
    )
    parser.add_argument(
        "--count",
        type=_positive_int,
        default=8,
        help="Number of chat requests to send",
    )
    parser.add_argument(
        "--max-workers",
        type=_positive_int,
        default=4,
        help="Maximum number of concurrent workers",
    )
    parser.add_argument(
        "--temperature",
        type=_temperature,
        default=0.0,
        help="Chat completion temperature",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help="Expected response prefix",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each request/result pair",
    )
    return parser.parse_args()


def build_requests(
    *,
    count: int,
    prefix: str,
    temperature: float,
) -> List[Tuple[str, ChatCompletionRequest]]:
    requests: List[Tuple[str, ChatCompletionRequest]] = []
    system_instruction = "Return exactly one line with no extra words."

    for index in range(count):
        expected_text = f"{prefix} IDX={index}"
        prompt = (
            "Reply with exactly this text and nothing else: "
            f"{expected_text}"
        )
        request = ChatCompletionRequest(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
        )
        requests.append((expected_text, request))

    return requests


def run_batch(
    requests: List[Tuple[str, ChatCompletionRequest]],
    *,
    max_workers: int,
    verbose: bool,
) -> Tuple[List[ChatCompletionResult], float]:
    batch_requests = [request for _, request in requests]
    start_time = time.perf_counter()
    results = call_chat_completions_batch(
        batch_requests,
        max_workers=max_workers,
        verbose=verbose,
    )
    elapsed_seconds = time.perf_counter() - start_time
    return results, elapsed_seconds


def verify_results(
    requests: List[Tuple[str, ChatCompletionRequest]],
    results: List[ChatCompletionResult],
) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    if len(results) != len(requests):
        errors.append(
            f"Result count mismatch: expected {len(requests)}, got {len(results)}"
        )
        return False, errors

    for index, ((expected_text, _), result) in enumerate(zip(requests, results)):
        actual_text = (result.content or "").strip()
        if result.request_index != index:
            errors.append(
                f"Order mismatch at position {index}: request_index={result.request_index}"
            )
        if actual_text != expected_text:
            errors.append(
                f"Content mismatch at position {index}: expected {expected_text!r}, got {actual_text!r}"
            )

    return len(errors) == 0, errors


def main() -> int:
    args = parse_args()
    requests = build_requests(
        count=args.count,
        prefix=args.prefix,
        temperature=args.temperature,
    )

    print("=== Batch Chat Completion Test ===")
    print(f"request_count: {args.count}")
    print(f"max_workers: {args.max_workers}")
    print(f"temperature: {args.temperature}")
    print(f"prefix: {args.prefix}")

    try:
        results, elapsed_seconds = run_batch(
            requests,
            max_workers=args.max_workers,
            verbose=args.verbose,
        )
    except Exception as exc:
        print(f"[FAIL] Batch execution crashed: {exc}")
        return 1

    passed, errors = verify_results(requests, results)

    print("\n=== Summary ===")
    print(f"elapsed_seconds: {elapsed_seconds:.3f}")
    print(f"result_count: {len(results)}")
    print(f"order_preserved: {passed}")

    if args.verbose:
        print("\n=== Results ===")
        for index, result in enumerate(results):
            print(
                f"[{index}] request_index={result.request_index} "
                f"finish_reason={result.finish_reason} "
                f"content={result.content!r} usage={result.usage}"
            )

    if not passed:
        print("\n=== Errors ===")
        for error in errors:
            print(f"- {error}")
        print("\n[FAIL] Batch concurrency test failed.")
        return 1

    print("\n[PASS] Batch concurrency test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
