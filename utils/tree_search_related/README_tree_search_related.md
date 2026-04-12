# utils/tree_search_related index

| File | Purpose |
|---|---|
| `pdf_json_prompt.py` | Prompt templates for multi-pass TOC-first extraction: TOC detection, transformation, continuation, page mapping, hierarchy generation, and summarization. |
| `pdf_json_pipeline.py` | Multi-pass TOC-first PDF→JSON extraction pipeline. Detects TOC, builds hierarchical tree, recursively subdivides large nodes, enriches with text/summaries. Depends on `azure_openai/azure_openai.py`, `pdf_json_prompt.py`, and `database/db_manager.py`. |
| `tree_node.py` | TreeNode class (in-memory graph with parent/children pointers, UCB1 for MCTS selection), `load_tree_from_db` builder, and tree utilities (count, leaves, depth). |

If folder contents change, update this index.
