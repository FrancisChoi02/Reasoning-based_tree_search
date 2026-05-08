# utils/tree_search_related index

| File | Purpose |
|---|---|
| `pdf_json_prompt.py` | Prompt templates for multi-pass TOC-first extraction and MCTS search: TOC detection, transformation, continuation, page mapping, hierarchy generation, summarization, prior scoring, leaf scoring, and answer synthesis. |
| `pdf_json_pipeline.py` | Multi-pass TOC-first PDF→JSON extraction pipeline. Detects TOC, builds hierarchical tree, recursively subdivides large nodes, enriches with text, and generates summaries via batched concurrent LLM calls (`call_chat_completions_batch`). Depends on `azure_openai/azure_openai.py`, `pdf_json_prompt.py`, and `database/db_manager.py`. |
| `tree_node.py` | TreeNode class (in-memory graph with parent/children pointers, UCB1 for MCTS selection), `load_tree_from_db` builder, and tree utilities (count, leaves, depth). |
| `mcts_search.py` | Forest-aware MCTS query engine that seeds title priors, selects a same-frontier batch of leaves, evaluates them concurrently through the shared batch chat wrapper, then commits scores serially before answer synthesis. |

If folder contents change, update this index.
