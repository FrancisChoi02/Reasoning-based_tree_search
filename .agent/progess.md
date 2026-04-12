# Progress Log

## 2026-04-12: TOC-First Extractor Upgrade (Milestone 2)

**What**: Refactored `pdf_json_pipeline.py` from flat single-pass extraction to multi-pass TOC-first hierarchical extraction, integrating logic from the pageindex sample (`.agent/design/pageindex_sample/`).

**Before → After** (Unilever FY22, 241 pages):

| Metric | Before | After |
|---|---|---|
| Root nodes | 295 | 5 |
| Total nodes | 338 | 171 |
| Max depth | 1 | 6 |
| verify_pipeline.py | PASS | PASS |

**Files modified**:
- `utils/tree_search_related/pdf_json_pipeline.py` — Full rewrite with 7 utility functions, 2 LLM wrappers, 10+ orchestration functions
- `utils/tree_search_related/pdf_json_prompt.py` — Added 10 new prompts for TOC detection, extraction, transformation, continuation, page mapping, summarization
- `run_pdf_json_pipeline.py` — Fixed stale import, removed unused `tabnanny`
- `verify_pipeline.py` — Updated default JSON path

**Key design decisions**:
- Synchronous (ThreadPoolExecutor) not async — matches existing pipeline pattern
- Fallback chain: TOC with pages → TOC without pages → LLM-generated structure
- Recursive subdivision capped at depth 3 to prevent infinite loops
- `end_index >= start_index` enforced via `max()` clamp

**Bug found and fixed**: `post_process_toc_to_tree` and `subdivide_large_nodes` could produce `end_index < start_index` when adjacent items share the same page. Fixed by clamping with `max(value, start_index)`.

---

## 2026-04-08: Initial Flat Extraction + DB Pipeline (Milestone 1)

**What**: Built the initial PDF→JSON flat extraction pipeline with SQLite storage and round-trip verification.

**Files created**:
- `utils/tree_search_related/pdf_json_pipeline.py`
- `utils/tree_search_related/pdf_json_prompt.py`
- `utils/tree_search_related/tree_node.py`
- `utils/database/db_manager.py`
- `verify_pipeline.py`
- `run_pdf_json_pipeline.py`

**Result**: Pipeline works but produces flat output (295 roots, depth 1).
