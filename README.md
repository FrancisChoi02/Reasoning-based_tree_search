# Reasoning-based Tree Search PoC

Multi-pass, TOC-first PDF extraction pipeline that converts documents into hierarchical JSON trees stored in SQLite, with MCTS-based tree search.

## Pipeline

```
PDF → TOC Detection → Hierarchical Extraction → Nested JSON Tree → SQLite DB → MCTS Search
```

1. **TOC Detection** — Scan first N pages for Table of Contents
2. **Extraction** — Transform TOC into structured entries with page indices (fallback: LLM-generated)
3. **Tree Construction** — Convert flat entries into nested tree using dot-notation hierarchy
4. **Recursive Subdivision** — Split any leaf node exceeding page/token thresholds
5. **Enrichment** — Fill each node with text content and optional summaries
6. **Storage** — Persist to SQLite with parent-child foreign keys

## Usage

```bash
# Extract PDF to hierarchical JSON
python run_pdf_json_pipeline.py --pdf "static/Unilever - FY22.pdf" --model gpt-5.4 --persist

# Verify JSON → DB → Tree round-trip
python verify_pipeline.py
```

## Project Structure

| Directory | Purpose |
|---|---|
| `utils/tree_search_related/` | Multi-pass TOC-first extraction pipeline, prompts, TreeNode + MCTS |
| `utils/database/` | SQLite schema init, JSON-to-DB loader, document queries |
| `utils/azure_openai/` | Azure OpenAI client, AI Search integration, Content Understanding |
| `utils/vector_search_related/` | End-to-end PDF ingest into Azure AI Search |
| `.agent/design/pageindex_sample/` | Reference: original pageindex hierarchical extraction |

## Verification Results (Unilever FY22, 241 pages)

| Metric | Value |
|---|---|
| Root nodes | 5 |
| Total nodes | 171 |
| Max depth | 6 |
| Leaves | 144 |
| Round-trip test | PASS |
