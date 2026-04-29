# MVP: Reasoning-based Tree Search PoC

## Goal

Build a pipeline that converts PDF documents into hierarchical tree structures stored in SQLite, enabling tree-based search (MCTS) over document content.

---

## Milestone 1: Flat PDF Extraction (DONE)

Single-pass flat extraction: chunk PDF into 6-page blocks, extract section records per chunk, concatenate.

| Component | Status | Notes |
|---|---|---|
| `pdf_json_pipeline.py` — flat chunk extraction | Done | Fixed 6-page chunks, per-chunk LLM call, flat concatenation |
| `pdf_json_prompt.py` — extraction prompt | Done | Single prompt schema with `nodes: []` |
| `db_manager.py` — SQLite schema + loader | Done | documents/nodes/node_chunks tables, `_insert_nodes_recursive` |
| `tree_node.py` — TreeNode + MCTS | Done | Parent/child pointers, UCB1, `load_tree_from_db` |
| `verify_pipeline.py` — round-trip test | Done | JSON→DB→Tree verification with diagnostics |
| Azure OpenAI client factory | Done | Cached client, deployment name helpers |

**Result**: Extracts content but produces flat forest (295 roots, depth 1).

---

## Milestone 2: TOC-First Hierarchical Extraction (DONE)

Multi-pass TOC-driven extraction producing deep hierarchical trees.

| Component | Status | Notes |
|---|---|---|
| TOC detection — scan first N pages | Done | `find_toc_pages()` via LLM |
| TOC transformation — raw text → structured JSON | Done | `_transform_toc()` with continuation loop |
| TOC page mapping — map entries to physical indices | Done | `process_toc_with_page_numbers()`, `process_toc_no_page_numbers()` |
| No-TOC fallback — LLM-generated structure | Done | `process_no_toc()` with token-aware chunking |
| Tree construction — flat `structure` list → nested tree | Done | `list_to_tree()` using dot-notation parent matching |
| Recursive subdivision — split large leaf nodes | Done | `subdivide_large_nodes()` with depth limit |
| Node enrichment — text + summaries | Done | `enrich_tree_with_text()`, `generate_summaries()` |
| Token-aware chunking | Done | `build_token_aware_chunks()` with `tiktoken` |
| Robust JSON extraction | Done | `extract_json_from_llm()` handles fences, None, commas |

**Verification** (Unilever FY22, 241 pages):

| Metric | Before (M1) | After (M2) |
|---|---|---|
| Root nodes | 295 | 5 |
| Total nodes | 338 | 171 |
| Max depth | 1 | 6 |
| Leaves | 330 | 144 |
| verify_pipeline.py | PASS | PASS |

---

## Milestone 3: Tree Search (IN PROGRESS)

Use the hierarchical tree for reasoning-based search over document content.

| Component | Status | Notes |
|---|---|---|
| MCTS node selection via UCB1 | Done | `TreeNode.ucb1()`, `best_child_ucb1()` in `tree_node.py`; used by `mcts_search.py` |
| Tree traversal + value backpropagation | Done | Implemented in `utils/tree_search_related/mcts_search.py` |
| LLM-based node evaluation at leaves | Done | Relevance scoring from path, summary, and head/tail text excerpts |
| Query → tree search → answer pipeline | Done | `MCTSQuery.search(...)` + root-level `test_mcts_search.py` smoke test |
| Multi-document search | Pending | Search across multiple PDF trees |

---

## Milestone 4: Vector Search Integration (PLANNED)

Hybrid tree + vector search for improved retrieval.

| Component | Status | Notes |
|---|---|---|
| Azure AI Search index + hybrid query | Done | `ai_search.py` — vector + text hybrid |
| PDF → Content Understanding → AI Search | Done | `azure_ingest_pipeline.py` |
| Tree node → chunk → vector embedding | Pending | Embed leaf nodes, store in node_chunks |
| Tree-guided vector search | Pending | Use tree structure to scope vector queries |
| Cross-reference tree search + vector results | Pending | Merge/rank results from both paths |

---

## Dependencies

```
openai==1.101.0
pypdf
tiktoken==0.12.0
pyyaml==6.0.2
python-dotenv
azure-ai-contentunderstanding
azure-identity
azure-search-documents==11.5.2
pymupdf==1.26.4
PyPDF2==3.0.1
```
