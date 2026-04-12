# utils/tree_search_related index

| File | Purpose |
|---|---|
| `pdf_json_prompt.py` | Prompt templates for page-index-style PDF text chunk extraction with strict JSON output requirements. |
| `pdf_json_pipeline.py` | PDF-to-JSON extraction pipeline with concurrent chunk processing, token/timing stats, optional JSON persistence, and optional DB storage. Depends on `azure_openai/azure_openai.py`, `pdf_json_prompt.py`, and `database/db_manager.py`. |
| `tree_node.py` | TreeNode class (in-memory graph with parent/children pointers, UCB1 for MCTS selection), `load_tree_from_db` builder, and tree utilities (count, leaves, depth). |

If folder contents change, update this index.
