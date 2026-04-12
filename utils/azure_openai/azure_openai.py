# Input: os, dotenv, openai AzureOpenAI client, Azure OpenAI environment variables.
# Output: Shared Azure OpenAI client plus chat/embedding deployment helpers and embedding functions.
# Position: Shared utility for Azure OpenAI calls used by ingest/query and extraction pipelines. If modified, update this header and the parent folder's .md index.

import os
from functools import lru_cache
from typing import List

from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

DEFAULT_API_VERSION = "2024-02-01"


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
