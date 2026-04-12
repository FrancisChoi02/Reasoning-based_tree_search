# Input: Chunked PDF text blocks and chunk position metadata from the PDF JSON pipeline.
# Output: System/user prompts that force strict JSON extraction output from the selected LLM model.
# Position: Prompt construction layer for PDF->JSON extraction workflow. If modified, update this header and the parent folder's .md index.

from typing import Any, Dict


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
4) Always return a JSON object with key \"records\".
5) If no section can be extracted, return {{\"records\": []}}.

Reply format:
{schema}

Given text chunk:
{chunk_text}

Directly return the final JSON structure. Do not output anything else.
""".strip()
