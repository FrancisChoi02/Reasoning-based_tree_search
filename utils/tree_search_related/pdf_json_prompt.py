# Input: Page text, TOC content, chunk text, and extraction parameters from the PDF JSON pipeline.
# Output: Prompt strings for TOC detection, extraction, transformation, continuation, page mapping, and summarization.
# Position: Prompt construction layer for multi-pass TOC-first PDF→JSON extraction. If modified, update this header and the parent folder's .md index.

import json
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Legacy prompts (kept for backward compatibility with call_extraction_llm)
# ---------------------------------------------------------------------------

def get_system_instruction() -> str:
    return (
        "You are an information extraction engine. "
        "Return valid JSON only. "
        "Do not include markdown fences. "
        "Do not add commentary."
    )


def get_output_schema() -> Dict[str, Any]:
    return {
        "records": [
            {
                "title": "<section title>",
                "start_index": 1,
                "end_index": 3,
                "summary": "<concise summary>",
                "text": "<relevant original text>",
                "nodes": [],
            }
        ]
    }


def build_extraction_prompt(chunk_text: str, chunk_index: int, total_chunks: int) -> str:
    schema = get_output_schema()
    return f"""
Your job is to extract structured section records from the given PDF text chunk.

The chunk position is {chunk_index + 1}/{total_chunks}.

Rules:
1) Keep extracted text faithful to the source chunk.
2) Keep summaries concise.
3) Use integer page-like indices where available from context; if not available, infer local range in the chunk.
4) Always return a JSON object with key "records".
5) If no section can be extracted, return {{"records": []}}.

Reply format:
{schema}

Given text chunk:
{chunk_text}

Directly return the final JSON structure. Do not output anything else.
""".strip()


# ---------------------------------------------------------------------------
# TOC-First Prompts
# ---------------------------------------------------------------------------

def build_toc_detection_prompt(page_text: str) -> str:
    return f"""
Your job is to detect if there is a table of content provided in the given text.

Given text: {page_text}

return the following JSON format:
{{
    "thinking": "<why do you think there is a table of content in the given text>",
    "toc_detected": "<yes or no>",
}}

Directly return the final JSON structure. Do not output anything else.
Please note: abstract, summary, notation list, figure list, table list, etc. are not table of contents.""".strip()


def build_toc_extraction_prompt(toc_text: str) -> str:
    return f"""
Your job is to extract the full table of contents from the given text, replace ... with :

Given text: {toc_text}

Directly return the full table of contents content. Do not output anything else.""".strip()


def build_toc_transform_prompt(toc_content: str) -> str:
    return """
You are given a table of contents, You job is to transform the whole table of content into a JSON format included table_of_contents.

structure is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

The response should be in the following JSON format:
{
"table_of_contents": [
    {
        "structure": <structure index, "x.x.x" or None> (string),
        "title": <title of the section>,
        "page": <page number or None>,
    },
    ...
    ],
}
You should transform the full table of contents in one go.
Directly return the final JSON structure, do not output anything else. """ + "\n\n Given table of contents:\n" + toc_content


def build_toc_transform_completeness_prompt(raw_toc: str, transformed_toc: str) -> str:
    return f"""
You are given a raw table of contents and a table of contents.
Your job is to check if the table of contents is complete.

Reply format:
{{
    "thinking": <why do you think the cleaned table of contents is complete or not>,
    "completed": "yes" or "no"
}}
Directly return the final JSON structure. Do not output anything else.

Raw Table of contents:
{raw_toc}

Cleaned Table of contents:
{transformed_toc}"""


def build_toc_page_index_prompt(toc_json: str, page_text: str) -> str:
    return """
You are given a table of contents in a json format and several pages of a document, your job is to add the physical_index to the table of contents in the json format.

The provided pages contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.

The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

The response should be in the following JSON format:
[
    {
        "structure": <structure index, "x.x.x" or None> (string),
        "title": <title of the section>,
        "physical_index": "<physical_index_X>" (keep the format)
    },
    ...
]

Only add the physical_index to the sections that are in the provided pages.
If the section is not in the provided pages, do not add the physical_index to it.
Directly return the final JSON structure. Do not output anything else.""" + f"\n\nTable of contents:\n{toc_json}\n\nDocument pages:\n{page_text}"


def build_generate_toc_init_prompt(page_text: str) -> str:
    return """
You are an expert in extracting hierarchical tree structure, your task is to generate the tree structure of the document.

The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

For the title, you need to extract the original title from the text, only fix the space inconsistency.

The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the start and end of page X.

For the physical_index, you need to extract the physical index of the start of the section from the text. Keep the <physical_index_X> format.

The response should be in the following format.
    [
        {
            "structure": <structure index, "x.x.x"> (string),
            "title": <title of the section, keep the original title>,
            "physical_index": "<physical_index_X> (keep the format)"
        },
    ],

Directly return the final JSON structure. Do not output anything else.""" + f"\n\nGiven text:\n{page_text}"


def build_generate_toc_continue_prompt(previous_toc: List[Dict], page_text: str) -> str:
    return """
You are an expert in extracting hierarchical tree structure.
You are given a tree structure of the previous part and the text of the current part.
Your task is to continue the tree structure from the previous part to include the current part.

The structure variable is the numeric system which represents the index of the hierarchy section in the table of contents. For example, the first section has structure index 1, the first subsection has structure index 1.1, the second subsection has structure index 1.2, etc.

For the title, you need to extract the original title from the text, only fix the space inconsistency.

The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the start and end of page X.

For the physical_index, you need to extract the physical index of the start of the section from the text. Keep the <physical_index_X> format.

The response should be in the following format.
    [
        {
            "structure": <structure index, "x.x.x"> (string),
            "title": <title of the section, keep the original title>,
            "physical_index": "<physical_index_X> (keep the format)"
        },
        ...
    ]

Directly return the additional part of the final JSON structure. Do not output anything else.""" + f"\n\nGiven text:\n{page_text}\n\nPrevious tree structure:\n{json.dumps(previous_toc, indent=2)}"


def build_add_page_number_prompt(page_text: str, structure: List[Dict]) -> str:
    return """
You are given an JSON structure of a document and a partial part of the document. Your task is to check if the title that is described in the structure is started in the partial given document.

The provided text contains tags like <physical_index_X> and <physical_index_X> to indicate the physical location of the page X.

If the full target section starts in the partial given document, insert the given JSON structure with the "start": "yes", and "start_index": "<physical_index_X>".

If the full target section does not start in the partial given document, insert "start": "no",  "start_index": None.

The response should be in the following format.
    [
        {
            "structure": <structure index, "x.x.x" or None> (string),
            "title": <title of the section>,
            "start": "<yes or no>",
            "physical_index": "<physical_index_X> (keep the format)" or None
        },
        ...
    ]
The given structure contains the result of the previous part, you need to fill the result of the current part, do not change the previous result.
Directly return the final JSON structure. Do not output anything else.""" + f"\n\nCurrent Partial Document:\n{page_text}\n\nGiven Structure\n{json.dumps(structure, indent=2)}"


def build_toc_page_index_detection_prompt(toc_content: str) -> str:
    return f"""
You will be given a table of contents.

Your job is to detect if there are page numbers/indices given within the table of contents.

Given text: {toc_content}

Reply format:
{{
    "thinking": <why do you think there are page numbers/indices given within the table of contents>,
    "page_index_given_in_toc": "<yes or no>"
}}
Directly return the final JSON structure. Do not output anything else."""


def build_summary_prompt(node_text: str) -> str:
    return f"""You are given a part of a document, your task is to generate a description of the partial document about what are main points covered in the partial document.

Partial Document Text: {node_text}

Directly return the description, do not include any other text."""


# ---------------------------------------------------------------------------
# MCTS Search Prompts
# ---------------------------------------------------------------------------


def build_prior_scoring_prompt(query: str, siblings: List[Dict[str, str]]) -> str:
    items = "\n".join(
        f'{index + 1}. {sibling["title"]} (pages {sibling["pages"]}, path: {sibling["path"]})'
        for index, sibling in enumerate(siblings)
    )
    return f"""Your job is to estimate which document sections are likely relevant to the given question.

Question: {query}

Sections:
{items}

Scoring rubric:
1.0 — Likely contains the direct answer
0.8 — Likely contains significant relevant information
0.5 — May contain useful context
0.2 — Unlikely to be relevant
0.0 — Definitely not relevant

Reply as JSON array:
[
  {{"title": "<exact title>", "prior_score": <float>}},
  ...
]
Directly return the JSON. Do not output anything else.""".strip()


def build_leaf_eval_prompt(
    query: str,
    path: str,
    title: str,
    text_head: str,
    text_tail: str,
    summary: Optional[str] = None,
) -> str:
    summary_section = f"\nSection summary: {summary}" if summary else ""
    tail_section = f"\n\nText (ending):\n{text_tail}" if text_tail else ""

    return f"""Your job is to score how relevant a document section is to the given question.

Question: {query}

Section path: {path}
Section title: {title}{summary_section}

Text (beginning):
{text_head}{tail_section}

Scoring rubric — be strict:
1.0 — Contains the direct, complete answer
0.8 — Contains significant information that partially answers the question
0.6 — Contains related information that provides useful context
0.4 — Topically related but does not directly help answer the question
0.2 — Only tangentially related
0.0 — Completely unrelated

Reply as JSON:
{{"thinking": "<1-2 sentences explaining your reasoning>", "score": <float>}}
Directly return the JSON. Do not output anything else.""".strip()


def build_synthesis_prompt(query: str, sections: List[Dict[str, str]]) -> str:
    parts = []
    for index, section in enumerate(sections, start=1):
        section_summary = f"\nSummary: {section['summary']}" if section.get("summary") else ""
        parts.append(
            f"--- Section {index}: {section['path']} (pages {section['pages']}) ---{section_summary}\n{section['text']}"
        )
    combined_sections = "\n\n".join(parts)

    return f"""Answer the question based on the document sections below.
If the sections do not contain enough information, say so.

Question: {query}

{combined_sections}

Instructions:
- Answer directly and concisely.
- Cite page numbers in parentheses when referencing specific data, e.g. (page 159).
- If multiple sections provide conflicting information, note the discrepancy.
- Do not fabricate information not present in the sections.""".strip()

