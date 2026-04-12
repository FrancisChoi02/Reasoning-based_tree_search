# Input: Azure AI Search credentials, Azure OpenAI embeddings, and normalized plain-text documents (with company_name and year metadata).
# Output: Azure AI Search index validation, schema synchronization (including company_name/year filterable fields), ingestion, and hybrid/vector query helpers.
# Position: Main search integration layer for Azure AI Search in this repo. If modified, update this header and the parent folder's .md index.

import os
from typing import Any, Dict, List, Optional

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery
from dotenv import load_dotenv

from utils.vector_search_related.azure_ingest_pipeline import build_search_documents
from utils.azure_openai.azure_openai import get_embedding, get_embeddings_batch, get_embedding_dimensions

load_dotenv()

VECTOR_FIELD_NAME = "content_vector"
VECTOR_PROFILE_NAME = "content-vector-profile"
VECTOR_ALGORITHM_NAME = "content-hnsw"


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def get_search_endpoint() -> str:
    return _require_env("AZURE_SEARCH_ENDPOINT")


def get_search_admin_key() -> str:
    return _require_env("AZURE_SEARCH_ADMIN_KEY")


def get_index_name() -> str:
    return _require_env("AZURE_SEARCH_INDEX_NAME")


def get_search_credential() -> AzureKeyCredential:
    return AzureKeyCredential(get_search_admin_key())


def get_search_client() -> SearchClient:
    return SearchClient(
        endpoint=get_search_endpoint(),
        index_name=get_index_name(),
        credential=get_search_credential(),
    )


def get_index_client() -> SearchIndexClient:
    return SearchIndexClient(
        endpoint=get_search_endpoint(),
        credential=get_search_credential(),
    )


def get_vector_dimensions() -> int:
    return get_embedding_dimensions()


def _validate_embedding_dimensions(embedding: List[float]) -> List[float]:
    expected_dimensions = get_vector_dimensions()
    if len(embedding) != expected_dimensions:
        raise ValueError(
            f"Embedding dimensions {len(embedding)} do not match configured dimensions {expected_dimensions}"
        )
    return embedding


def _build_index_definition() -> SearchIndex:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="source_path", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="source_file", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="chunk_index", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
        SimpleField(name="company_name", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="year", type=SearchFieldDataType.Int32, filterable=True),
        SimpleField(name="metadata_json", type=SearchFieldDataType.String),
        SearchField(
            name=VECTOR_FIELD_NAME,
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=get_vector_dimensions(),
            vector_search_profile_name=VECTOR_PROFILE_NAME,
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name=VECTOR_ALGORITHM_NAME)],
        profiles=[
            VectorSearchProfile(
                name=VECTOR_PROFILE_NAME,
                algorithm_configuration_name=VECTOR_ALGORITHM_NAME,
            )
        ],
    )

    return SearchIndex(name=get_index_name(), fields=fields, vector_search=vector_search)


def _find_vector_field(index: SearchIndex) -> Optional[SearchField]:
    return next((field for field in index.fields if field.name == VECTOR_FIELD_NAME), None)


def _validate_existing_index(index: SearchIndex) -> None:
    vector_field = _find_vector_field(index)
    if vector_field is None:
        raise ValueError(
            f"Existing index '{index.name}' is missing required field '{VECTOR_FIELD_NAME}'. "
            "Create a new Azure AI Search index with the current schema, then re-run ingestion."
        )

    if getattr(vector_field, "type", None) != SearchFieldDataType.Collection(SearchFieldDataType.Single):
        raise ValueError(
            f"Existing index '{index.name}' field '{VECTOR_FIELD_NAME}' has the wrong type. "
            "Create a new Azure AI Search index with the current schema, then re-run ingestion."
        )

    if getattr(vector_field, "vector_search_dimensions", None) != get_vector_dimensions():
        raise ValueError(
            f"Existing index '{index.name}' field '{VECTOR_FIELD_NAME}' has incompatible vector dimensions. "
            "Create a new Azure AI Search index with the current schema, then re-run ingestion."
        )

    if getattr(vector_field, "vector_search_profile_name", None) != VECTOR_PROFILE_NAME:
        raise ValueError(
            f"Existing index '{index.name}' field '{VECTOR_FIELD_NAME}' has the wrong vector profile. "
            "Create a new Azure AI Search index with the current schema, then re-run ingestion."
        )


def ensure_index() -> None:
    index_client = get_index_client()
    index_name = get_index_name()
    try:
        existing_index = index_client.get_index(index_name)
        _validate_existing_index(existing_index)
    except ResourceNotFoundError:
        index_client.create_index(_build_index_definition())


def ingest_documents(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ensure_index()
    print(f"[*] Starting ingestion of {len(documents)} document chunks...")
    normalized_documents = build_search_documents(documents)

    # Batch process embeddings (e.g., 16 documents at a time)
    BATCH_SIZE = 16
    indexed_documents: List[Dict[str, Any]] = []

    total_batches = (len(normalized_documents) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(normalized_documents), BATCH_SIZE):
        current_batch_num = i // BATCH_SIZE + 1
        batch_docs = normalized_documents[i : i + BATCH_SIZE]
        batch_texts = [doc["content"] for doc in batch_docs]
        
        print(f"    [Batch {current_batch_num}/{total_batches}] Generating embeddings for {len(batch_docs)} chunks...")
        
        # Get embeddings for the current batch
        batch_embeddings = get_embeddings_batch(batch_texts)

        for doc, embedding in zip(batch_docs, batch_embeddings):
            indexed_document = dict(doc)
            # Handle mixed type chunk_index (int or str)
            effective_chunk_index = indexed_document.get("chunk_index")
            if effective_chunk_index is not None:
                indexed_document["chunk_index"] = 0 if isinstance(effective_chunk_index, str) else int(effective_chunk_index)
            indexed_document[VECTOR_FIELD_NAME] = _validate_embedding_dimensions(embedding)
            indexed_documents.append(indexed_document)

    print(f"[*] Uploading {len(indexed_documents)} indexed documents to Azure AI Search...")
    results = get_search_client().merge_or_upload_documents(documents=indexed_documents)
    
    normalized_upload_results: List[Dict[str, Any]] = []
    success_count = 0
    for result in results:
        if not result.succeeded:
            print(f"    [ERROR] Ingest failed for key={result.key}: {result.error_message}")
            raise ValueError(
                f"Azure AI Search ingest failed for key={result.key}: {result.error_message}"
            )
        success_count += 1
        normalized_upload_results.append(
            {
                "key": result.key,
                "status_code": result.status_code,
                "succeeded": result.succeeded,
                "error_message": result.error_message,
            }
        )
    print(f"[SUCCESS] Ingestion complete. {success_count} documents indexed.")
    return normalized_upload_results


def query_documents(
    query_text: str,
    top: int = 5,
    filter_expr: Optional[str] = None,
) -> List[Dict[str, Any]]:
    ensure_index()
    normalized_query = query_text.strip()
    if not normalized_query:
        raise ValueError("query_text must not be empty")

    vector_query = VectorizedQuery(
        vector=_validate_embedding_dimensions(get_embedding(normalized_query)),
        k_nearest_neighbors=top,
        fields=VECTOR_FIELD_NAME,
    )

    results = get_search_client().search(
        search_text=normalized_query,
        vector_queries=[vector_query],
        filter=filter_expr,
        top=top,
        select=["id", "title", "content", "source_path", "source_file", "chunk_index", "company_name", "year", "metadata_json"],
    )

    normalized_results: List[Dict[str, Any]] = []
    for result in results:
        normalized_results.append(
            {
                "id": result.get("id"),
                "title": result.get("title"),
                "content": result.get("content"),
                "source_path": result.get("source_path"),
                "source_file": result.get("source_file"),
                "chunk_index": result.get("chunk_index"),
                "company_name": result.get("company_name"),
                "year": result.get("year"),
                "metadata_json": result.get("metadata_json"),
                "score": result.get("@search.score"),
            }
        )
    return normalized_results
