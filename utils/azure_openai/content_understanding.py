# Input: Local PDF paths, Azure Content Understanding credentials, Azure OpenAI deployment names, Content Understanding environment variables, and optional company_name/year metadata.
# Output: Structured Content Understanding analysis results and Azure AI Search-ready document dicts (including company_name and year).
# Position: Azure Content Understanding utility layer for turning local PDFs into structured text blocks and configuring required service defaults. Splits large PDFs into page batches to stay within API limits. If modified, update this header and the parent folder's .md index.

import io
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from azure.ai.contentunderstanding import ContentUnderstandingClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv
from pypdf import PdfReader, PdfWriter

load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def get_content_understanding_endpoint() -> str:
    return _require_env("AZURE_CONTENT_UNDERSTANDING_ENDPOINT")


def get_content_understanding_api_key() -> str:
    return _require_env("AZURE_CONTENT_UNDERSTANDING_API_KEY")


def get_content_understanding_analyzer_id() -> str:
    return _require_env("AZURE_CONTENT_UNDERSTANDING_PREBUILT_IDENTIFIER")


def get_content_understanding_chat_deployment_name() -> str:
    return _require_env("AZURE_OPENAI_DEPLOYMENT_NAME")


def get_content_understanding_embedding_deployment_name() -> str:
    return _require_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME")


@lru_cache(maxsize=1)
def get_content_understanding_client() -> ContentUnderstandingClient:
    return ContentUnderstandingClient(
        endpoint=get_content_understanding_endpoint(),
        credential=AzureKeyCredential(get_content_understanding_api_key()),
    )


@lru_cache(maxsize=1)
def configure_content_understanding_defaults() -> None:
    get_content_understanding_client().update_defaults(
        model_deployments={
            "gpt-5.4": get_content_understanding_chat_deployment_name(),
            "text-embedding-3-large": get_content_understanding_embedding_deployment_name(),
        }
    )


MAX_PAGES_PER_BATCH = 50


def _split_pdf_into_batches(pdf_path: Path) -> List[bytes]:
    """Split a PDF into byte chunks of at most MAX_PAGES_PER_BATCH pages each."""
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)

    if total_pages <= MAX_PAGES_PER_BATCH:
        return [pdf_path.read_bytes()]

    batches: List[bytes] = []
    for start in range(0, total_pages, MAX_PAGES_PER_BATCH):
        writer = PdfWriter()
        for page_index in range(start, min(start + MAX_PAGES_PER_BATCH, total_pages)):
            writer.add_page(reader.pages[page_index])
        buffer = io.BytesIO()
        writer.write(buffer)
        batches.append(buffer.getvalue())

    return batches


def _merge_batch_results(batch_results: List[Any]) -> Any:
    """Merge multiple Content Understanding results into a single result object.

    Concatenates the `contents` lists from each batch result so downstream
    code sees one unified result regardless of how many batches were needed.
    """
    if len(batch_results) == 1:
        return batch_results[0]

    merged = batch_results[0]
    for subsequent in batch_results[1:]:
        subsequent_contents = getattr(subsequent, "contents", [])
        if subsequent_contents:
            merged.contents.extend(subsequent_contents)

    return merged


def analyze_local_pdf(pdf_path: str) -> Any:
    local_path = Path(pdf_path)
    if not local_path.is_file():
        raise ValueError(f"PDF file not found: {pdf_path}")

    configure_content_understanding_defaults()
    client = get_content_understanding_client()
    analyzer_id = get_content_understanding_analyzer_id()

    batches = _split_pdf_into_batches(local_path)
    batch_results: List[Any] = []

    for batch_index, batch_bytes in enumerate(batches):
        print(f"[*] Analyzing batch {batch_index + 1}/{len(batches)} ...")
        poller = client.begin_analyze_binary(
            analyzer_id=analyzer_id,
            binary_input=batch_bytes,
            content_type="application/pdf",
        )
        batch_results.append(poller.result())

    return _merge_batch_results(batch_results)


def save_analysis_to_local_txt(pdf_path: str, result: Any, output_dir: str = "output") -> str:
    """Save the Content Understanding analysis result to a local txt file for inspection."""
    os.makedirs(output_dir, exist_ok=True)
    
    pdf_name = Path(pdf_path).stem
    output_path = Path(output_dir) / f"{pdf_name}_analysis.txt"
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"=== Content Understanding Analysis for: {pdf_path} ===\n\n")
        
        for i, content in enumerate(getattr(result, "contents", [])):
            f.write(f"--- Content Index: {i} ---\n")
            markdown = getattr(content, "markdown", "")
            f.write(f"[Markdown Content]:\n{markdown}\n\n")
            
            raw_fields = getattr(content, "fields", {})
            if raw_fields:
                f.write("[Extracted Fields]:\n")
                for field_name, field_value in raw_fields.items():
                    val = _serialize_field_value(field_value)
                    f.write(f"  - {field_name}: {val}\n")
                f.write("\n")
            
            f.write("-" * 40 + "\n\n")
            
    print(f"[*] Analysis results saved to: {output_path}")
    return str(output_path)


def _serialize_field_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_serialize_field_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_field_value(item) for key, item in value.items()}
    if hasattr(value, "as_dict"):
        return _serialize_field_value(value.as_dict())
    if hasattr(value, "value"):
        return _serialize_field_value(value.value)
    return str(value)


def extract_content_understanding_documents(
    pdf_path: str,
    result: Any,
    company_name: str = "",
    year: int = 0,
) -> List[Dict[str, Any]]:
    local_path = Path(pdf_path)
    documents: List[Dict[str, Any]] = []
    
    # Simple chunking to avoid exceeding token limits (8192 tokens)
    # Approx 4000 characters per chunk is safe for text-embedding-3-large
    CHUNK_SIZE = 4000
    CHUNK_OVERLAP = 200

    for content_index, content in enumerate(getattr(result, "contents", [])):
        markdown = str(getattr(content, "markdown", "") or "").strip()
        if not markdown:
            continue

        raw_fields = getattr(content, "fields", None)
        serialized_fields: Dict[str, Any] = {}
        if raw_fields:
            for field_name, field_value in raw_fields.items():
                serialized_fields[str(field_name)] = _serialize_field_value(field_value)

        # Split markdown into smaller chunks
        if len(markdown) > CHUNK_SIZE:
            start = 0
            sub_index = 0
            while start < len(markdown):
                end = start + CHUNK_SIZE
                chunk_text = markdown[start:end]
                
                documents.append(
                    {
                        "title": local_path.name,
                        "content": chunk_text,
                        "source_path": str(local_path.resolve()),
                        "source_file": local_path.name,
                        "chunk_index": f"{content_index}_{sub_index}",
                        "company_name": company_name,
                        "year": year,
                        "metadata": {
                            "analyzer_id": get_content_understanding_analyzer_id(),
                            "content_index": content_index,
                            "sub_index": sub_index,
                            "fields": serialized_fields,
                        },
                    }
                )
                start += (CHUNK_SIZE - CHUNK_OVERLAP)
                sub_index += 1
        else:
            documents.append(
                {
                    "title": local_path.name,
                    "content": markdown,
                    "source_path": str(local_path.resolve()),
                    "source_file": local_path.name,
                    "chunk_index": str(content_index),
                    "company_name": company_name,
                    "year": year,
                    "metadata": {
                        "analyzer_id": get_content_understanding_analyzer_id(),
                        "content_index": content_index,
                        "fields": serialized_fields,
                    },
                }
            )

    if not documents:
        raise ValueError(f"No markdown content extracted from PDF: {pdf_path}")

    return documents
