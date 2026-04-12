# Input: Local PDF path, extraction model name, and runtime pipeline controls (chunking, concurrency, retries, persistence flags).
# Output: Processed JSON extraction result with timing/token statistics and optional persisted JSON file.
# Position: Core PDF->JSON extraction pipeline orchestrator with concurrent chunk processing. If modified, update this header and the parent folder's .md index.

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import APIError
from pypdf import PdfReader
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.azure_openai.azure_openai import get_azure_openai_client, get_chat_deployment_name
from utils.tree_search_related.pdf_json_prompt import build_extraction_prompt, get_system_instruction


def extract_pdf_text_pages(pdf_path: str) -> List[str]:
    local_path = Path(pdf_path)
    if not local_path.is_file():
        raise ValueError(f"PDF file not found: {pdf_path}")

    reader = PdfReader(str(local_path))
    pages: List[str] = []
    for page in reader.pages:
        pages.append((page.extract_text() or "").strip())

    if not pages:
        raise ValueError(f"No pages available in PDF: {pdf_path}")

    return pages


def build_text_chunks(pages: List[str], chunk_pages: int = 6) -> List[str]:
    if not pages:
        raise ValueError("pages must not be empty")
    if chunk_pages <= 0:
        raise ValueError("chunk_pages must be greater than 0")

    chunks: List[str] = []
    for offset in range(0, len(pages), chunk_pages):
        page_slice = pages[offset : offset + chunk_pages]
        chunk_text = []
        for index, page_text in enumerate(page_slice, start=offset + 1):
            chunk_text.append(f"<page_{index}>\n{page_text}\n</page_{index}>")
        chunks.append("\n".join(chunk_text).strip())

    return chunks


def extract_json_payload(raw_response: str) -> Dict[str, Any]:
    content = raw_response.strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model response is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Model response must be a JSON object")
    if "records" not in parsed:
        raise ValueError('Model response must include top-level key "records"')
    if not isinstance(parsed["records"], list):
        raise ValueError('Model response key "records" must be a list')

    return parsed


def call_extraction_llm(
    *,
    model: str,
    prompt: str,
    system_instruction: Optional[str] = None,
    max_retries: int = 3,
    temperature: float = 0.0,
    verbose: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    # selected_model = model.strip() or get_chat_deployment_name()
    selected_model = "gpt-5.4"
    client = get_azure_openai_client()
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    if max_retries <= 0:
        raise ValueError("max_retries must be greater than 0")

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=selected_model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            raw_content = response.choices[0].message.content or ""
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
            }
            return extract_json_payload(raw_content), usage
        except (APIError, ValueError, IndexError, KeyError) as exc:
            if verbose:
                print(f"[RETRY] LLM extraction attempt {attempt}/{max_retries} failed: {exc}")
            if attempt == max_retries:
                raise
            time.sleep(1)

    raise RuntimeError("Unreachable retry state")


def normalize_extraction_results(chunk_results: List[Dict[str, Any]], pdf_path: str, model: str) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    for chunk_result in chunk_results:
        records.extend(chunk_result.get("records", []))

    return {
        "pdf_name": Path(pdf_path).name,
        "source_path": str(Path(pdf_path).resolve()),
        "model": model,
        "processed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chunks_processed": len(chunk_results),
        "records": records,
        "saved_path": None,
    }


def persist_processed_json(processed: Dict[str, Any], pdf_path: str, output_dir: str = "static") -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    file_name = f"{Path(pdf_path).stem}_{timestamp}.json"
    destination = output_path / file_name

    with destination.open("w", encoding="utf-8") as file_obj:
        json.dump(processed, file_obj, ensure_ascii=False, indent=2)

    return str(destination.resolve())


def run_pdf_json_pipeline(
    pdf_path: str,
    *,
    model: str,
    persist: bool = False,
    output_dir: str = "static",
    chunk_pages: int = 6,
    max_retries: int = 3,
    temperature: float = 0.0,
    max_workers: int = 1,
    store_to_db: bool = False,
    db_path: str = "tree_poc.db",
    verbose: bool = True,
) -> Dict[str, Any]:
    if verbose:
        print(f"[PIPELINE] Starting PDF->JSON extraction for: {pdf_path}")
        print("[1/5] Validating input")

    if not model.strip():
        raise ValueError("model must not be empty")

    if verbose:
        print("[2/5] Extracting text from PDF pages")
    pages = extract_pdf_text_pages(pdf_path)

    if verbose:
        print(f"      Extracted {len(pages)} pages")
        print(f"[3/5] Building chunks (chunk_pages={chunk_pages})")
    chunks = build_text_chunks(pages, chunk_pages=chunk_pages)

    if verbose:
        print(f"      Built {len(chunks)} chunks")

    max_workers = max(1, min(max_workers, 10))
    system_instruction = get_system_instruction()

    if verbose:
        print(f"[4/5] Extracting JSON from chunks (max_workers={max_workers})")

    token_usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    indexed_results: List[Tuple[int, Dict[str, Any]]] = []
    extraction_start = time.perf_counter()

    def _process_chunk(chunk_index: int, chunk_text: str) -> Tuple[int, Dict[str, Any], Dict[str, int]]:
        prompt = build_extraction_prompt(
            chunk_text=chunk_text,
            chunk_index=chunk_index,
            total_chunks=len(chunks),
        )
        result, usage = call_extraction_llm(
            model=model,
            prompt=prompt,
            system_instruction=system_instruction,
            max_retries=max_retries,
            temperature=temperature,
            verbose=verbose,
        )
        return chunk_index, result, usage

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_chunk, idx, text): idx
            for idx, text in enumerate(chunks)
        }
        for future in as_completed(futures):
            idx, result, usage = future.result()
            indexed_results.append((idx, result))
            for key in token_usage_total:
                token_usage_total[key] += usage.get(key, 0)
            if verbose:
                done_count = len(indexed_results)
                print(f"      [*] Chunk {idx + 1}/{len(chunks)} done ({done_count}/{len(chunks)} completed)")

    extraction_elapsed = time.perf_counter() - extraction_start
    indexed_results.sort(key=lambda pair: pair[0])
    chunk_results = [result for _, result in indexed_results]

    if verbose:
        print("[5/5] Normalizing results")

    processed = normalize_extraction_results(chunk_results, pdf_path=pdf_path, model=model)
    processed["processing_time_seconds"] = round(extraction_elapsed, 3)
    processed["token_usage"] = token_usage_total

    if persist:
        if verbose:
            print(f"[SAVE] Persisting processed JSON to {output_dir}/")
        saved_path = persist_processed_json(processed, pdf_path=pdf_path, output_dir=output_dir)
        processed["saved_path"] = saved_path
        if verbose:
            print(f"[SAVE] Wrote: {saved_path}")

    if store_to_db:
        from utils.database.db_manager import load_json_to_db

        if verbose:
            print(f"[DB] Storing results to database: {db_path}")
        db_result = load_json_to_db(processed, db_path=db_path, verbose=verbose)
        processed["db_doc_pk"] = db_result["doc_pk"]
        processed["db_node_count"] = db_result["node_count"]

    if verbose:
        print(
            f"[DONE] records={len(processed['records'])} "
            f"chunks={processed['chunks_processed']} "
            f"model={processed['model']} "
            f"time={processed['processing_time_seconds']}s "
            f"tokens={processed['token_usage']['total_tokens']}"
        )

    return processed
