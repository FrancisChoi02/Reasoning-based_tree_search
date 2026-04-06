# Input: Local PDF paths, optional company_name/year metadata, or plain-text document dictionaries for Azure AI Search ingestion.
# Output: Normalized Azure AI Search document payloads (including company_name and year) and end-to-end PDF ingest results.
# Position: Orchestrates Content Understanding output into Azure AI Search ingestion. If modified, update this header and the parent folder's .md index.

import hashlib
import json
from typing import Any, Dict, List

from utils.content_understanding import analyze_local_pdf, extract_content_understanding_documents, save_analysis_to_local_txt


def _build_document_id(document: Dict[str, Any]) -> str:
    source_path = str(document.get("source_path") or document.get("source_file") or "")
    title = str(document.get("title") or "")
    content = str(document.get("content") or "")
    chunk_index = int(document.get("chunk_index", 0))
    raw_id = f"{source_path}|{title}|{chunk_index}|{content}"
    return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()


def build_search_documents(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not documents:
        raise ValueError("documents must not be empty")

    normalized_documents: List[Dict[str, Any]] = []
    for chunk_index, document in enumerate(documents):
        content = str(document.get("content") or "").strip()
        if not content:
            raise ValueError(f"document at index {chunk_index} is missing content")

        effective_chunk_index = int(document.get("chunk_index", chunk_index))
        metadata = document.get("metadata")
        normalized_document = {
            "id": str(document.get("id") or _build_document_id({**document, "content": content, "chunk_index": effective_chunk_index})),
            "title": str(document.get("title") or ""),
            "content": content,
            "source_path": str(document.get("source_path") or ""),
            "source_file": str(document.get("source_file") or ""),
            "chunk_index": effective_chunk_index,
            "company_name": str(document.get("company_name") or ""),
            "year": int(document.get("year") or 0),
            "metadata_json": json.dumps(metadata, ensure_ascii=False) if metadata is not None else "",
        }
        normalized_documents.append(normalized_document)

    return normalized_documents


def build_documents_from_pdf(
    pdf_path: str,
    company_name: str = "",
    year: int = 0,
    save_to_txt: bool = False,
) -> List[Dict[str, Any]]:
    analysis_result = analyze_local_pdf(pdf_path)

    if save_to_txt:
        save_analysis_to_local_txt(pdf_path, analysis_result)

    return extract_content_understanding_documents(
        pdf_path, analysis_result, company_name=company_name, year=year
    )


def ingest_local_pdf(
    pdf_path: str,
    company_name: str = "",
    year: int = 0,
    save_to_txt: bool = False,
) -> Dict[str, Any]:
    from utils.ai_search import ingest_documents

    print(f"\n[PIPELINE] Starting ingestion for PDF: {pdf_path}")
    print("[1/2] Analyzing PDF and extracting content...")
    documents = build_documents_from_pdf(
        pdf_path, company_name=company_name, year=year, save_to_txt=save_to_txt
    )
    print(f"      Extracted {len(documents)} chunks from PDF.")

    print("[2/2] Ingesting documents into Azure AI Search...")
    ingest_results = ingest_documents(documents)
    
    print(f"[PIPELINE] Finished ingestion for {pdf_path}.\n")
    return {
        "pdf_path": pdf_path,
        "document_count": len(documents),
        "documents": documents,
        "ingest_results": ingest_results,
    }
