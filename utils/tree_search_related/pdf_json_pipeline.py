# Input: Local PDF path, extraction model name, and runtime pipeline controls (TOC-first strategy, chunking, concurrency, retries, persistence flags).
# Output: Processed JSON extraction result with hierarchical tree structure, timing/token statistics, and optional persisted JSON file.
# Position: Core PDF→JSON extraction pipeline orchestrator using multi-pass TOC-first hierarchical extraction. If modified, update this header and the parent folder's .md index.

import copy
import json
import math
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import APIError
from pypdf import PdfReader
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.azure_openai.azure_openai import get_azure_openai_client, get_chat_deployment_name
from utils.tree_search_related.pdf_json_prompt import (
    build_toc_detection_prompt,
    build_toc_extraction_prompt,
    build_toc_page_index_prompt,
    build_toc_page_index_detection_prompt,
    build_toc_transform_completeness_prompt,
    build_toc_transform_prompt,
    build_add_page_number_prompt,
    build_generate_toc_continue_prompt,
    build_generate_toc_init_prompt,
    build_summary_prompt,
)

import tiktoken


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1: Utility Functions (pure logic, no LLM)
# ═══════════════════════════════════════════════════════════════════════════

def extract_pdf_page_tokens(
    pdf_path: str, encoding_name: str = "cl100k_base"
) -> List[Tuple[str, int]]:
    """Extract per-page text and token count from a PDF."""
    local_path = Path(pdf_path)
    if not local_path.is_file():
        raise ValueError(f"PDF file not found: {pdf_path}")

    reader = PdfReader(str(local_path))
    enc = tiktoken.get_encoding(encoding_name)
    pages: List[Tuple[str, int]] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        token_count = len(enc.encode(text))
        pages.append((text, token_count))

    if not pages:
        raise ValueError(f"No pages available in PDF: {pdf_path}")
    return pages


def extract_pdf_text_pages(pdf_path: str) -> List[str]:
    """Backward-compatible wrapper: returns page text only (no token counts)."""
    return [text for text, _ in extract_pdf_page_tokens(pdf_path)]


def build_token_aware_chunks(
    page_list: List[Tuple[str, int]],
    max_tokens: int = 20000,
    overlap_page: int = 1,
    start_index: int = 1,
) -> List[str]:
    """Group pages into token-bounded chunks with overlap, tagged with physical indices."""
    page_contents: List[str] = []
    token_lengths: List[int] = []

    for page_index in range(start_index, start_index + len(page_list)):
        page_text = page_list[page_index - start_index][0]
        wrapped = f"<physical_index_{page_index}>\n{page_text}\n<physical_index_{page_index}>\n\n"
        page_contents.append(wrapped)
        token_lengths.append(page_list[page_index - start_index][1])

    num_tokens = sum(token_lengths)
    if num_tokens <= max_tokens:
        return ["".join(page_contents)]

    subsets: List[str] = []
    current_subset: List[str] = []
    current_token_count = 0

    expected_parts = math.ceil(num_tokens / max_tokens)
    average_tokens = math.ceil(((num_tokens / expected_parts) + max_tokens) / 2)

    for i, (content, tokens) in enumerate(zip(page_contents, token_lengths)):
        if current_token_count + tokens > average_tokens:
            subsets.append("".join(current_subset))
            overlap_start = max(i - overlap_page, 0)
            current_subset = page_contents[overlap_start:i]
            current_token_count = sum(token_lengths[overlap_start:i])

        current_subset.append(content)
        current_token_count += tokens

    if current_subset:
        subsets.append("".join(current_subset))
    return subsets


def list_to_tree(flat_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert a flat list with 'structure' dot-notation into a nested tree with 'nodes'.

    Each item must have a 'structure' field like "1", "1.1", "1.2.1".
    Parent of "1.2.3" is "1.2". Items with no dots are roots.
    """
    def _get_parent_structure(structure: Optional[str]) -> Optional[str]:
        if not structure:
            return None
        parts = str(structure).split(".")
        return ".".join(parts[:-1]) if len(parts) > 1 else None

    nodes: Dict[Optional[str], Dict[str, Any]] = {}
    root_nodes: List[Dict[str, Any]] = []

    for item in flat_list:
        structure = item.get("structure")
        node: Dict[str, Any] = {"title": item.get("title"), "nodes": []}
        if "start_index" in item:
            node["start_index"] = item["start_index"]
        if "end_index" in item:
            node["end_index"] = item["end_index"]

        nodes[structure] = node
        parent_structure = _get_parent_structure(structure)

        if parent_structure and parent_structure in nodes:
            nodes[parent_structure]["nodes"].append(node)
        else:
            root_nodes.append(node)

    def _clean_empty_nodes(node: Dict[str, Any]) -> Dict[str, Any]:
        if not node["nodes"]:
            del node["nodes"]
        else:
            for child in node["nodes"]:
                _clean_empty_nodes(child)
        return node

    return [_clean_empty_nodes(n) for n in root_nodes]


def post_process_toc_to_tree(
    flat_list: List[Dict[str, Any]], total_pages: int
) -> List[Dict[str, Any]]:
    """Convert flat TOC list (with physical_index, appear_start) into nested tree.

    Computes start_index/end_index from physical_index neighbors, then calls list_to_tree.
    """
    if not flat_list:
        return []

    for i, item in enumerate(flat_list):
        item["start_index"] = item.get("physical_index")
        if i < len(flat_list) - 1:
            next_appear_start = flat_list[i + 1].get("appear_start", "no")
            if next_appear_start == "yes":
                item["end_index"] = max(flat_list[i + 1]["physical_index"] - 1, item["start_index"])
            else:
                item["end_index"] = max(flat_list[i + 1]["physical_index"], item["start_index"])
        else:
            item["end_index"] = max(total_pages, item["start_index"])

    tree = list_to_tree(flat_list)
    if tree:
        return tree

    # Fallback: strip helper fields and return flat
    for node in flat_list:
        node.pop("appear_start", None)
        node.pop("physical_index", None)
    return flat_list


def enrich_tree_with_text(
    tree: List[Dict[str, Any]], page_list: List[Tuple[str, int]]
) -> None:
    """Walk tree in-place, fill each node's 'text' from page content."""
    for node in tree:
        start = node.get("start_index")
        end = node.get("end_index")
        if start is not None and end is not None:
            parts: List[str] = []
            for page_num in range(start - 1, end):
                if 0 <= page_num < len(page_list):
                    parts.append(page_list[page_num][0])
            node["text"] = "\n".join(parts)
        children = node.get("nodes", [])
        if children:
            enrich_tree_with_text(children, page_list)


def extract_json_from_llm(content: str) -> Any:
    """Robust JSON extraction from LLM response. Handles fences, None, trailing commas."""
    try:
        start_idx = content.find("```json")
        if start_idx != -1:
            start_idx += 7
            end_idx = content.rfind("```")
            json_content = content[start_idx:end_idx].strip()
        else:
            start_idx = content.find("```")
            if start_idx != -1:
                end_idx = content.rfind("```", start_idx + 3)
                json_content = content[start_idx + 3:end_idx].strip()
            else:
                json_content = content.strip()

        json_content = json_content.replace("None", "null")
        json_content = " ".join(json_content.split())

        try:
            return json.loads(json_content)
        except json.JSONDecodeError:
            json_content = json_content.replace(",]", "]").replace(",}", "}")
            return json.loads(json_content)
    except (json.JSONDecodeError, Exception) as e:
        raise ValueError(f"Failed to extract JSON from LLM response: {e}") from e


def assign_node_ids(tree: List[Dict[str, Any]], start_id: int = 0) -> int:
    """Assign zero-padded 4-digit node_id in depth-first order. Returns next available id."""
    for node in tree:
        node["node_id"] = str(start_id).zfill(4)
        start_id += 1
        children = node.get("nodes", [])
        if children:
            start_id = assign_node_ids(children, start_id)
    return start_id


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: LLM Wrappers
# ═══════════════════════════════════════════════════════════════════════════

def _get_model() -> str:
    return "gpt-5.4"


def call_llm_raw(
    *,
    prompt: str,
    system_instruction: Optional[str] = None,
    max_retries: int = 3,
    temperature: float = 0.0,
    verbose: bool = True,
) -> Tuple[str, Dict[str, int], str]:
    """Call LLM and return (raw_content, usage_dict, finish_reason).

    Does NOT use response_format=json_object so the model can return plain text.
    """
    client = get_azure_openai_client()
    messages: List[Dict[str, str]] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=_get_model(),
                messages=messages,
                temperature=temperature,
            )
            content = response.choices[0].message.content or ""
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
            }
            finish_reason = response.choices[0].finish_reason or "unknown"
            return content, usage, finish_reason
        except (APIError, ValueError, IndexError, KeyError) as exc:
            if verbose:
                print(f"[RETRY] LLM call attempt {attempt}/{max_retries} failed: {exc}")
            if attempt == max_retries:
                raise
            time.sleep(1)

    raise RuntimeError("Unreachable retry state")


def call_llm_json(
    *,
    prompt: str,
    system_instruction: Optional[str] = None,
    max_retries: int = 3,
    temperature: float = 0.0,
    verbose: bool = True,
) -> Tuple[Any, Dict[str, int]]:
    """Call LLM and parse response as JSON. Returns (parsed_json, usage_dict)."""
    content, usage, _ = call_llm_raw(
        prompt=prompt,
        system_instruction=system_instruction,
        max_retries=max_retries,
        temperature=temperature,
        verbose=verbose,
    )
    parsed = extract_json_from_llm(content)
    return parsed, usage


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3 helpers: JSON extraction utilities (kept from old pipeline)
# ═══════════════════════════════════════════════════════════════════════════

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
    """Legacy direct-JSON extraction call (kept for backward compatibility)."""
    selected_model = _get_model()
    client = get_azure_openai_client()
    messages: List[Dict[str, str]] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

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


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4: Pipeline Orchestration — TOC-First Multi-Pass
# ═══════════════════════════════════════════════════════════════════════════

def _convert_physical_index_to_int(data: Any) -> Any:
    """Convert physical_index values from '<physical_index_N>' strings to ints."""
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "physical_index" in item:
                val = item["physical_index"]
                if isinstance(val, str):
                    match = re.search(r"(\d+)", val)
                    if match:
                        item["physical_index"] = int(match.group(1))
        return data
    return data


def _convert_page_to_int(data: List[Dict]) -> List[Dict]:
    """Convert 'page' values to int where possible."""
    for item in data:
        if "page" in item and isinstance(item["page"], str):
            try:
                item["page"] = int(item["page"])
            except ValueError:
                pass
    return data


def _add_preface_if_needed(data: List[Dict]) -> List[Dict]:
    """Insert a synthetic 'Preface' node if the first TOC entry starts after page 1."""
    if not data:
        return data
    first_index = data[0].get("physical_index")
    if first_index is not None and first_index > 1:
        data.insert(0, {"structure": "0", "title": "Preface", "physical_index": 1})
    return data


def _check_title_appearance_in_start(
    title: str, page_text: str, verbose: bool = True
) -> str:
    """Check if a section title starts at the beginning of the given page text."""
    prompt = f"""
You will be given the current section title and the current page_text.
Your job is to check if the current section starts in the beginning of the given page_text.
If there are other contents before the current section title, then the current section does not start in the beginning.
If the current section title is the first content in the given page_text, then the current section starts in the beginning.

Note: do fuzzy matching, ignore any space inconsistency in the page_text.

The given section title is {title}.
The given page_text is {page_text}.

Reply format:
{{
    "thinking": "<why do you think the section starts at the beginning>",
    "start_begin": "yes or no"
}}
Directly return the final JSON structure. Do not output anything else."""
    try:
        result, _ = call_llm_json(prompt=prompt, verbose=verbose)
        return result.get("start_begin", "no")
    except Exception:
        return "no"


def _check_start_appearances(
    flat_list: List[Dict], page_list: List[Tuple[str, int]], verbose: bool = True
) -> List[Dict]:
    """Set 'appear_start' on each item by checking if its title starts at the page beginning."""
    for item in flat_list:
        if item.get("physical_index") is None:
            item["appear_start"] = "no"
            continue
        page_idx = item["physical_index"] - 1
        if 0 <= page_idx < len(page_list):
            page_text = page_list[page_idx][0]
            item["appear_start"] = _check_title_appearance_in_start(
                item["title"], page_text, verbose=verbose
            )
        else:
            item["appear_start"] = "no"
    return flat_list


# ── TOC Detection ────────────────────────────────────────────────────────

def find_toc_pages(
    page_list: List[Tuple[str, int]], max_check_pages: int = 20, verbose: bool = True
) -> List[int]:
    """Scan first N pages for Table of Contents. Returns list of page indices (0-based)."""
    toc_pages: List[int] = []
    last_was_toc = False

    for i in range(min(max_check_pages, len(page_list))):
        prompt = build_toc_detection_prompt(page_list[i][0])
        try:
            result, _ = call_llm_json(prompt=prompt, verbose=verbose)
            detected = result.get("toc_detected", "no")
        except Exception:
            detected = "no"

        if detected == "yes":
            toc_pages.append(i)
            last_was_toc = True
        elif detected == "no" and last_was_toc:
            break

    return toc_pages


def _detect_page_index_in_toc(toc_content: str, verbose: bool = True) -> str:
    """Check if the TOC content includes page numbers/indices."""
    prompt = build_toc_page_index_detection_prompt(toc_content)
    try:
        result, _ = call_llm_json(prompt=prompt, verbose=verbose)
        return result.get("page_index_given_in_toc", "no")
    except Exception:
        return "no"


# ── TOC Extraction & Transformation ──────────────────────────────────────

def _transform_dots(text: str) -> str:
    text = re.sub(r"\.{5,}", ": ", text)
    text = re.sub(r"(?:\. ){5,}\.?", ": ", text)
    return text


def _extract_toc_content(
    toc_pages: List[int], page_list: List[Tuple[str, int]], verbose: bool = True
) -> Dict[str, Any]:
    """Extract raw TOC text from detected pages and check for page indices."""
    toc_text = ""
    for page_idx in toc_pages:
        toc_text += page_list[page_idx][0]
    toc_text = _transform_dots(toc_text)

    has_page_index = _detect_page_index_in_toc(toc_text, verbose=verbose)
    return {"toc_content": toc_text, "page_index_given_in_toc": has_page_index}


def _check_toc_completeness(
    raw_toc: str, transformed: str, verbose: bool = True
) -> str:
    """Check if a TOC transformation captured all entries."""
    prompt = build_toc_transform_completeness_prompt(raw_toc, transformed)
    try:
        result, _ = call_llm_json(prompt=prompt, verbose=verbose)
        return result.get("completed", "no")
    except Exception:
        return "no"


def _transform_toc(toc_content: str, verbose: bool = True) -> List[Dict]:
    """Convert raw TOC text into structured JSON with structure/title/page fields.

    Handles continuation if the LLM output is truncated.
    """
    prompt = build_toc_transform_prompt(toc_content)
    response, _, finish_reason = call_llm_raw(prompt=prompt, verbose=verbose)
    is_complete = _check_toc_completeness(toc_content, response, verbose=verbose)

    if is_complete == "yes" and finish_reason == "finished":
        parsed = extract_json_from_llm(response)
        return _convert_page_to_int(parsed.get("table_of_contents", []))

    # Continuation loop
    accumulated = response
    continuation_attempts = 0
    max_continuations = 5

    while not (is_complete == "yes" and finish_reason == "finished"):
        continuation_attempts += 1
        if continuation_attempts > max_continuations:
            if verbose:
                print("[WARN] TOC transformation continuation limit reached")
            break

        prompt = f"""Your task is to continue the table of contents json structure, directly output the remaining part of the json structure.

The raw table of contents json structure is:
{toc_content}

The incomplete transformed table of contents json structure is:
{accumulated}

Please continue the json structure, directly output the remaining part of the json structure."""

        new_response, _, finish_reason = call_llm_raw(prompt=prompt, verbose=verbose)
        accumulated += new_response
        is_complete = _check_toc_completeness(toc_content, accumulated, verbose=verbose)

    try:
        parsed = extract_json_from_llm(accumulated)
        return _convert_page_to_int(parsed.get("table_of_contents", []))
    except Exception:
        if verbose:
            print("[WARN] Failed to parse continued TOC, using initial parse")
        parsed = extract_json_from_llm(response)
        return _convert_page_to_int(parsed.get("table_of_contents", []))


# ── TOC Processing Paths ─────────────────────────────────────────────────

def _add_page_numbers_to_toc(
    page_text: str, structure: List[Dict], verbose: bool = True
) -> List[Dict]:
    """Ask LLM to locate each TOC entry in the given page text and assign physical_index."""
    prompt = build_add_page_number_prompt(page_text, structure)
    try:
        result, _ = call_llm_json(prompt=prompt, verbose=verbose)
        if isinstance(result, list):
            for item in result:
                item.pop("start", None)
            return result
        return structure
    except Exception:
        return structure


def _process_none_page_numbers(
    toc_items: List[Dict], page_list: List[Tuple[str, int]],
    start_index: int = 1, verbose: bool = True,
) -> List[Dict]:
    """Fill in missing physical_index values for TOC entries by scanning nearby pages."""
    for i, item in enumerate(toc_items):
        if "physical_index" not in item or item.get("physical_index") is None:
            prev_physical = 0
            for j in range(i - 1, -1, -1):
                if toc_items[j].get("physical_index") is not None:
                    prev_physical = toc_items[j]["physical_index"]
                    break

            next_physical = len(page_list) + start_index
            for j in range(i + 1, len(toc_items)):
                if toc_items[j].get("physical_index") is not None:
                    next_physical = toc_items[j]["physical_index"]
                    break

            page_contents: List[str] = []
            for page_index in range(prev_physical, next_physical + 1):
                list_index = page_index - start_index
                if 0 <= list_index < len(page_list):
                    wrapped = f"<physical_index_{page_index}>\n{page_list[list_index][0]}\n<physical_index_{page_index}>\n\n"
                    page_contents.append(wrapped)

            if page_contents:
                item_copy = copy.deepcopy(item)
                item_copy.pop("page", None)
                result = _add_page_numbers_to_toc(
                    "".join(page_contents), [item_copy], verbose=verbose
                )
                if result and isinstance(result[0], dict):
                    phys_val = result[0].get("physical_index")
                    if phys_val is not None:
                        if isinstance(phys_val, str):
                            match = re.search(r"(\d+)", phys_val)
                            if match:
                                item["physical_index"] = int(match.group(1))
                        else:
                            item["physical_index"] = int(phys_val)
                        item.pop("page", None)
    return toc_items


def _calculate_page_offset(pairs: List[Dict]) -> Optional[int]:
    """Calculate most common offset between logical page numbers and physical indices."""
    differences: List[int] = []
    for pair in pairs:
        try:
            diff = pair["physical_index"] - pair["page"]
            differences.append(diff)
        except (KeyError, TypeError):
            continue

    if not differences:
        return None

    counts: Dict[int, int] = {}
    for d in differences:
        counts[d] = counts.get(d, 0) + 1
    return max(counts.items(), key=lambda x: x[1])[0]


def _add_page_offset(data: List[Dict], offset: int) -> List[Dict]:
    """Convert logical page numbers to physical indices using offset."""
    for item in data:
        if item.get("page") is not None and isinstance(item["page"], int):
            item["physical_index"] = item["page"] + offset
            del item["page"]
    return data


def _extract_matching_pairs(
    toc_with_pages: List[Dict], toc_with_physical: List[Dict], start_index: int
) -> List[Dict]:
    """Match TOC entries by title to find page-to-physical-index pairs."""
    pairs: List[Dict] = []
    for phys_item in toc_with_physical:
        for page_item in toc_with_pages:
            if phys_item.get("title") == page_item.get("title"):
                physical_index = phys_item.get("physical_index")
                if physical_index is not None and int(physical_index) >= start_index:
                    pairs.append({
                        "title": phys_item.get("title"),
                        "page": page_item.get("page"),
                        "physical_index": physical_index,
                    })
    return pairs


def process_toc_with_page_numbers(
    toc_content: str,
    toc_pages: List[int],
    page_list: List[Tuple[str, int]],
    toc_check_pages: int = 20,
    verbose: bool = True,
) -> List[Dict]:
    """Full path for documents whose TOC includes page numbers."""
    toc_with_page_number = _transform_toc(toc_content, verbose=verbose)
    toc_no_page_number = copy.deepcopy(toc_with_page_number)
    for item in toc_no_page_number:
        item.pop("page", None)

    start_page_index = toc_pages[-1] + 1
    main_content = ""
    for page_index in range(
        start_page_index,
        min(start_page_index + toc_check_pages, len(page_list)),
    ):
        main_content += f"<physical_index_{page_index + 1}>\n{page_list[page_index][0]}\n<physical_index_{page_index + 1}>\n\n"

    prompt = build_toc_page_index_prompt(json.dumps(toc_no_page_number), main_content)
    toc_with_physical, _ = call_llm_json(prompt=prompt, verbose=verbose)
    toc_with_physical = _convert_physical_index_to_int(toc_with_physical)

    matching_pairs = _extract_matching_pairs(
        toc_with_page_number, toc_with_physical, start_page_index + 1
    )
    offset = _calculate_page_offset(matching_pairs)

    if offset is not None:
        toc_with_page_number = _add_page_offset(toc_with_page_number, offset)
    else:
        for item in toc_with_page_number:
            if "page" in item:
                item["physical_index"] = item.pop("page")

    toc_with_page_number = _process_none_page_numbers(
        toc_with_page_number, page_list, verbose=verbose
    )
    return toc_with_page_number


def process_toc_no_page_numbers(
    toc_content: str,
    toc_pages: List[int],
    page_list: List[Tuple[str, int]],
    verbose: bool = True,
) -> List[Dict]:
    """Path for documents whose TOC lacks page numbers."""
    toc_transformed = _transform_toc(toc_content, verbose=verbose)

    chunks = build_token_aware_chunks(page_list)
    toc_with_page_number = copy.deepcopy(toc_transformed)

    for chunk_text in chunks:
        toc_with_page_number = _add_page_numbers_to_toc(
            chunk_text, toc_with_page_number, verbose=verbose
        )

    return _convert_physical_index_to_int(toc_with_page_number)


def process_no_toc(
    page_list: List[Tuple[str, int]],
    start_index: int = 1,
    max_tokens: int = 20000,
    verbose: bool = True,
) -> List[Dict]:
    """No-TOC fallback: ask LLM to generate hierarchical structure from page text."""
    chunks = build_token_aware_chunks(page_list, max_tokens=max_tokens, start_index=start_index)

    if verbose:
        print(f"      No TOC found, generating structure from {len(chunks)} chunk(s)")

    prompt = build_generate_toc_init_prompt(chunks[0])
    toc_list, _ = call_llm_json(prompt=prompt, verbose=verbose)

    for chunk_text in chunks[1:]:
        prompt = build_generate_toc_continue_prompt(toc_list, chunk_text)
        additional, _ = call_llm_json(prompt=prompt, verbose=verbose)
        if isinstance(additional, list):
            toc_list.extend(additional)

    return _convert_physical_index_to_int(toc_list)


def _validate_and_truncate(
    toc_list: List[Dict], total_pages: int, start_index: int = 1, verbose: bool = True
) -> List[Dict]:
    """Remove entries with physical_index beyond document length."""
    max_page = total_pages + start_index - 1
    truncated = 0
    for item in toc_list:
        if item.get("physical_index") is not None and item["physical_index"] > max_page:
            if verbose:
                print(f"      Truncated: '{item.get('title')}' index {item['physical_index']} > max {max_page}")
            item["physical_index"] = None
            truncated += 1
    if truncated and verbose:
        print(f"      Truncated {truncated} entries beyond document length")
    return toc_list


def determine_toc_and_process(
    page_list: List[Tuple[str, int]],
    toc_check_pages: int = 20,
    verbose: bool = True,
) -> List[Dict]:
    """Central router: detect TOC, pick processing path, fallback chain."""
    if verbose:
        print("[3/6] Detecting Table of Contents")

    toc_pages = find_toc_pages(page_list, max_check_pages=toc_check_pages, verbose=verbose)

    if not toc_pages:
        if verbose:
            print("      No TOC detected, using LLM-generated structure")
        return process_no_toc(page_list, verbose=verbose)

    if verbose:
        print(f"      TOC detected on page(s): {[p + 1 for p in toc_pages]}")

    toc_info = _extract_toc_content(toc_pages, page_list, verbose=verbose)

    if toc_info.get("page_index_given_in_toc") == "yes":
        if verbose:
            print("      TOC has page numbers, using full extraction path")
        try:
            return process_toc_with_page_numbers(
                toc_info["toc_content"], toc_pages, page_list,
                toc_check_pages=toc_check_pages, verbose=verbose,
            )
        except Exception as exc:
            if verbose:
                print(f"      [FALLBACK] TOC with page numbers failed: {exc}")

    if toc_info.get("toc_content", "").strip():
        if verbose:
            print("      TOC without page numbers, scanning pages for indices")
        try:
            return process_toc_no_page_numbers(
                toc_info["toc_content"], toc_pages, page_list, verbose=verbose
            )
        except Exception as exc:
            if verbose:
                print(f"      [FALLBACK] TOC without page numbers failed: {exc}")

    if verbose:
        print("      [FALLBACK] All TOC paths failed, generating structure from content")
    return process_no_toc(page_list, verbose=verbose)


# ── Recursive Subdivision ────────────────────────────────────────────────

def subdivide_large_nodes(
    node: Dict[str, Any],
    page_list: List[Tuple[str, int]],
    max_pages: int = 10,
    max_tokens: int = 20000,
    max_depth: int = 3,
    current_depth: int = 0,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Recursively subdivide leaf nodes that exceed page/token thresholds."""
    start = node.get("start_index", 1)
    end = node.get("end_index", 1)
    page_range = end - start + 1

    sub_page_list = page_list[start - 1 : end]
    token_count = sum(t for _, t in sub_page_list)

    children = node.get("nodes", [])
    has_large_children = False
    if children:
        for child in children:
            subdivide_large_nodes(
                child, page_list, max_pages, max_tokens,
                max_depth, current_depth + 1, verbose,
            )
        return node

    # Leaf node — check if it needs subdivision
    if current_depth >= max_depth:
        return node
    if page_range <= max_pages or token_count < max_tokens:
        return node

    if verbose:
        print(f"      Subdividing: '{node['title']}' (pages {start}-{end}, ~{token_count} tokens)")

    try:
        sub_toc = process_no_toc(sub_page_list, start_index=start, verbose=verbose)
        sub_toc = _validate_and_truncate(sub_toc, len(sub_page_list), start_index=start, verbose=verbose)
        sub_toc = _check_start_appearances(sub_toc, page_list, verbose=verbose)

        valid_items = [item for item in sub_toc if item.get("physical_index") is not None]
        if not valid_items:
            return node

        # Check if first item duplicates the parent
        if valid_items[0]["title"].strip() == node["title"].strip():
            child_items = valid_items[1:]
        else:
            child_items = valid_items

        if not child_items:
            return node

        child_tree = post_process_toc_to_tree(child_items, end)
        if child_tree:
            node["nodes"] = child_tree
            # Adjust parent end_index
            first_child_start = child_tree[0].get("start_index", start)
            if first_child_start > start:
                node["end_index"] = max(first_child_start - 1, start)

            # Recurse on new children
            for child in node["nodes"]:
                subdivide_large_nodes(
                    child, page_list, max_pages, max_tokens,
                    max_depth, current_depth + 1, verbose,
                )
    except Exception as exc:
        if verbose:
            print(f"      [WARN] Subdivision failed for '{node['title']}': {exc}")

    return node


# ── Summary Generation ───────────────────────────────────────────────────

def _generate_node_summary(node_text: str, verbose: bool = True) -> str:
    prompt = build_summary_prompt(node_text)
    try:
        content, _, _ = call_llm_raw(prompt=prompt, verbose=verbose)
        return content.strip()
    except Exception:
        return ""


def generate_summaries(
    tree: List[Dict[str, Any]], max_workers: int = 4, verbose: bool = True
) -> None:
    """Generate summaries for all nodes in the tree (in-place)."""
    all_nodes: List[Dict[str, Any]] = []

    def _collect(nodes: List[Dict[str, Any]]) -> None:
        for node in nodes:
            all_nodes.append(node)
            if node.get("nodes"):
                _collect(node["nodes"])

    _collect(tree)

    if verbose:
        print(f"      Generating summaries for {len(all_nodes)} node(s)")

    def _summarize(node: Dict[str, Any]) -> None:
        text = node.get("text", "")
        if text:
            node["summary"] = _generate_node_summary(text, verbose=verbose)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        futures = {executor.submit(_summarize, n): n for n in all_nodes}
        for future in as_completed(futures):
            future.result()


# ═══════════════════════════════════════════════════════════════════════════
# Phase 5: Main Pipeline Entry Point
# ═══════════════════════════════════════════════════════════════════════════

def normalize_extraction_results(
    chunk_results: List[Dict[str, Any]], pdf_path: str, model: str
) -> Dict[str, Any]:
    """Legacy: concatenate flat records from multiple chunks (kept for backward compat)."""
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


def persist_processed_json(
    processed: Dict[str, Any], pdf_path: str, output_dir: str = "static"
) -> str:
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
    # New TOC-first parameters
    toc_check_pages: int = 20,
    max_pages_per_node: int = 10,
    max_tokens_per_node: int = 20000,
    chunk_max_tokens: int = 20000,
    add_text: bool = True,
    add_summary: bool = False,
) -> Dict[str, Any]:
    """Run the multi-pass TOC-first PDF→JSON extraction pipeline."""
    if verbose:
        print(f"[PIPELINE] Starting PDF->JSON extraction for: {pdf_path}")
        print("[1/6] Validating input")

    if not model.strip():
        raise ValueError("model must not be empty")

    # Step 1: Extract pages with token counts
    if verbose:
        print("[2/6] Extracting text from PDF pages")
    page_list = extract_pdf_page_tokens(pdf_path)
    total_pages = len(page_list)
    if verbose:
        print(f"      Extracted {total_pages} pages")

    pipeline_start = time.perf_counter()
    token_usage_total: Dict[str, int] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    # Step 2: Detect TOC and build flat structure
    flat_toc = determine_toc_and_process(
        page_list, toc_check_pages=toc_check_pages, verbose=verbose
    )

    # Step 3: Validate, add preface, check start appearances
    if verbose:
        print("[4/6] Building hierarchical tree")
    flat_toc = _validate_and_truncate(flat_toc, total_pages, verbose=verbose)
    flat_toc = [item for item in flat_toc if item.get("physical_index") is not None]
    flat_toc = _add_preface_if_needed(flat_toc)
    flat_toc = _check_start_appearances(flat_toc, page_list, verbose=verbose)

    # Step 4: Convert flat list to nested tree
    tree = post_process_toc_to_tree(flat_toc, total_pages)
    if verbose:
        total_nodes = _count_tree_nodes(tree)
        print(f"      Tree built: {_count_roots(tree)} root(s), {total_nodes} total node(s)")

    # Step 5: Recursively subdivide large leaf nodes
    if verbose:
        print("[5/6] Subdividing large nodes")
    for root_node in tree:
        subdivide_large_nodes(
            root_node, page_list,
            max_pages=max_pages_per_node,
            max_tokens=max_tokens_per_node,
            verbose=verbose,
        )

    # Step 6: Enrichment
    if verbose:
        print("[6/6] Enriching nodes")
    if add_text:
        enrich_tree_with_text(tree, page_list)

    if add_summary:
        generate_summaries(tree, max_workers=max_workers, verbose=verbose)

    assign_node_ids(tree)

    elapsed = time.perf_counter() - pipeline_start

    # Build output envelope (compatible with load_json_to_db)
    processed: Dict[str, Any] = {
        "pdf_name": Path(pdf_path).name,
        "source_path": str(Path(pdf_path).resolve()),
        "model": model,
        "processed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chunks_processed": len(flat_toc),
        "records": tree,
        "saved_path": None,
        "processing_time_seconds": round(elapsed, 3),
        "token_usage": token_usage_total,
    }

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
        total_nodes = _count_tree_nodes(tree)
        print(
            f"[DONE] records={total_nodes} "
            f"roots={_count_roots(tree)} "
            f"model={processed['model']} "
            f"time={processed['processing_time_seconds']}s"
        )

    return processed


# ── Tree statistics helpers ──────────────────────────────────────────────

def _count_tree_nodes(tree: List[Dict[str, Any]]) -> int:
    count = 0
    for node in tree:
        count += 1
        if node.get("nodes"):
            count += _count_tree_nodes(node["nodes"])
    return count


def _count_roots(tree: List[Dict[str, Any]]) -> int:
    return len(tree)
