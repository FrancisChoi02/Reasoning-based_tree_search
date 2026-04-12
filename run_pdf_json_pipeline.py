# Input: CLI args for PDF path, model, and pipeline runtime controls.
# Output: Executes the PDF->JSON pipeline and prints extraction summary plus resulting JSON.
# Position: Root-level manual test runner for utils.pdf_json_pipeline. If modified, update this header and the parent folder's .md index.

import argparse
import json
from tabnanny import verbose

from utils.pdf_json_pipeline import run_pdf_json_pipeline


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
    parser = argparse.ArgumentParser(description="Run PDF to JSON extraction pipeline")
    parser.add_argument("--pdf", required=True, help="Local PDF path")
    parser.add_argument("--model", required=True, help="Model name for extraction")
    parser.add_argument("--persist", action="store_true", help="Persist output JSON to local static directory")
    parser.add_argument("--output-dir", default="static", help="Output directory for persisted JSON")
    parser.add_argument("--chunk-pages", type=_positive_int, default=6, help="Number of PDF pages per extraction chunk")
    parser.add_argument("--max-retries", type=_positive_int, default=3, help="Max retries for each model extraction call")
    parser.add_argument("--temperature", type=_temperature, default=0.0, help="Model temperature")
    parser.add_argument("--quiet", action="store_true", help="Reduce command line logs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model ="gpt-5.4"
    persist = True
    output_dir = "static"
    chunk_pages = 6
    max_retries = 3
    temperature = 0.0
    verbose = not args.quiet
    
    result = run_pdf_json_pipeline(
        pdf_path=args.pdf,
        model=model,
        persist=persist,
        output_dir=output_dir,
        chunk_pages=chunk_pages,
        max_retries=max_retries,
        temperature=temperature,
        verbose=verbose,
    )

    print("\n=== Pipeline Result Summary ===")
    print(f"pdf_name: {result['pdf_name']}")
    print(f"model: {result['model']}")
    print(f"chunks_processed: {result['chunks_processed']}")
    print(f"records: {len(result['records'])}")
    print(f"saved_path: {result['saved_path']}")
    print("\n=== Full JSON Output ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
