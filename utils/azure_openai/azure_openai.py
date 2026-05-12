# Input: os, random, time, concurrent futures, dotenv, openai AzureOpenAI client, Azure OpenAI environment variables.
# Output: Shared Azure OpenAI client, deployment helpers, embedding functions, and normalized single/batch chat completion wrappers.
# Position: Shared utility for Azure OpenAI calls used by ingest/query and extraction pipelines. If modified, update this header and the parent folder's .md index.

import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import APIError, AzureOpenAI

load_dotenv()

DEFAULT_API_VERSION = "2024-02-01"
DEFAULT_CHAT_MAX_RETRIES = 3
DEFAULT_CHAT_MAX_WORKERS = 4
DEFAULT_CHAT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_CHAT_BACKOFF_MAX_SECONDS = 8.0

# Thread-safe accumulator for total token consumption across all LLM calls.
# Reset before each workflow run; read after completion for the summary footer.
_token_lock = threading.Lock()
_token_total = 0


def reset_token_counter() -> None:
    global _token_total
    with _token_lock:
        _token_total = 0


def read_token_counter() -> int:
    with _token_lock:
        return _token_total


def _add_tokens(usage: dict) -> None:
    global _token_total
    total = usage.get("total_tokens", 0) or 0
    if total > 0:
        with _token_lock:
            _token_total += total


@dataclass(frozen=True)
class ChatCompletionRequest:
    prompt: str
    system_instruction: Optional[str] = None
    temperature: float = 0.0
    max_retries: int = DEFAULT_CHAT_MAX_RETRIES
    response_format: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ChatCompletionResult:
    content: str
    usage: Dict[str, int]
    finish_reason: str
    request_index: int


class BatchChatCompletionError(RuntimeError):
    """Raised when a batched chat completion request fails."""


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _get_openai_api_key() -> str:
    api_key = os.getenv("AZURE_OPENAI_API_KEY_FORMAL") or os.getenv("AZURE_OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "Missing Azure OpenAI API key. Set AZURE_OPENAI_API_KEY_FORMAL or AZURE_OPENAI_API_KEY"
        )
    return api_key


@lru_cache(maxsize=1)
def get_azure_openai_client() -> AzureOpenAI:
    endpoint = _require_env("AZURE_OPENAI_ENDPOINT")
    api_key = _get_openai_api_key()
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION)
    return AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)


@lru_cache(maxsize=1)
def get_embedding_client() -> AzureOpenAI:
    return get_azure_openai_client()


def get_chat_deployment_name() -> str:
    return _require_env("AZURE_OPENAI_DEPLOYMENT_NAME")


def get_embedding_deployment_name() -> str:
    return _require_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME")


def get_embedding_dimensions() -> int:
    value = _require_env("AZURE_OPENAI_EMBEDDING_DIMENSIONS")
    return int(value)


def _build_messages(prompt: str, system_instruction: Optional[str] = None) -> List[Dict[str, str]]:
    if not prompt.strip():
        raise ValueError("prompt must not be empty")

    messages: List[Dict[str, str]] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})
    return messages


def _extract_usage(response: Any) -> Dict[str, int]:
    return {
        "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
    }


def _sleep_with_backoff(attempt: int) -> None:
    delay_seconds = min(
        DEFAULT_CHAT_BACKOFF_BASE_SECONDS * (2 ** max(attempt - 1, 0)),
        DEFAULT_CHAT_BACKOFF_MAX_SECONDS,
    )
    jitter_seconds = random.uniform(0.0, 0.25)
    time.sleep(delay_seconds + jitter_seconds)


def _call_chat_completion_once(request: ChatCompletionRequest) -> ChatCompletionResult:
    client = get_azure_openai_client()
    response = client.chat.completions.create(
        model=get_chat_deployment_name(),
        messages=_build_messages(
            prompt=request.prompt,
            system_instruction=request.system_instruction,
        ),
        temperature=request.temperature,
        response_format=request.response_format,
    )
    return ChatCompletionResult(
        content=response.choices[0].message.content or "",
        usage=_extract_usage(response),
        finish_reason=response.choices[0].finish_reason or "unknown",
        request_index=-1,
    )


def call_chat_completion(
    request: ChatCompletionRequest,
    *,
    request_index: int = 0,
    verbose: bool = True,
) -> ChatCompletionResult:
    for attempt in range(1, request.max_retries + 1):
        try:
            result = _call_chat_completion_once(request)
            _add_tokens(result.usage)
            return ChatCompletionResult(
                content=result.content,
                usage=result.usage,
                finish_reason=result.finish_reason,
                request_index=request_index,
            )
        except (APIError, ValueError, IndexError, KeyError) as exc:
            if verbose:
                print(
                    f"[RETRY] Chat completion attempt {attempt}/{request.max_retries} failed "
                    f"for request_index={request_index}: {exc}"
                )
            if attempt == request.max_retries:
                raise
            _sleep_with_backoff(attempt)

    raise RuntimeError("Unreachable retry state")


def call_chat_completions_batch(
    requests: List[ChatCompletionRequest],
    *,
    max_workers: int = DEFAULT_CHAT_MAX_WORKERS,
    verbose: bool = True,
) -> List[ChatCompletionResult]:
    if not requests:
        return []

    ordered_results: List[Optional[ChatCompletionResult]] = [None] * len(requests)

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(requests)))) as executor:
        future_to_index = {
            executor.submit(
                call_chat_completion,
                request,
                request_index=index,
                verbose=verbose,
            ): index
            for index, request in enumerate(requests)
        }

        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                ordered_results[index] = future.result()
            except Exception as exc:
                raise BatchChatCompletionError(
                    f"Batched chat completion failed for request_index={index}: {exc}"
                ) from exc

    return [result for result in ordered_results if result is not None]


def get_embedding(text: str) -> List[float]:
    normalized_text = text.strip()
    if not normalized_text:
        raise ValueError("text must not be empty")

    client = get_azure_openai_client()
    response = client.embeddings.create(
        model=get_embedding_deployment_name(),
        input=normalized_text,
    )
    return list(response.data[0].embedding)


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Get embeddings for a batch of texts to improve performance and avoid rate limits."""
    if not texts:
        return []

    client = get_azure_openai_client()
    response = client.embeddings.create(
        model=get_embedding_deployment_name(),
        input=texts,
    )
    return [list(data.embedding) for data in response.data]
