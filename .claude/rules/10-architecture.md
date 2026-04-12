```
.
├── .agent/
│   ├── design/                          # Reference designs and sample code
│   │   ├── DB_table_schema.sql          # SQLite schema for documents/nodes/node_chunks
│   │   ├── output_json_format.json      # Expected JSON output format
│   │   ├── recommanded_metadata_json.json
│   │   └── pageindex_sample/            # Reference: pageindex hierarchical extraction
│   │       ├── pageindex/
│   │       │   ├── page_index.py        # Multi-pass TOC-first extraction logic
│   │       │   ├── page_index_md.py     # Markdown-to-tree extraction
│   │       │   ├── utils.py             # LLM wrappers, tree utilities, token counting
│   │       │   └── config.yaml          # Extraction thresholds
│   │       └── tests/                   # Sample PDFs + expected JSON results
│   ├── docs/
│   │   ├── MVP.md                       # MVP scope and current progress tracker
│   │   ├── TDD.md                       # Test-driven development checklist
│   │   └── EXTRACTOR_UPGRADE_PLAN.md    # Archived: flat→TOC-first upgrade analysis
│   ├── lession.md                       # Lessons learned from user corrections
│   └── progess.md                       # Milestone progress log
├── .claude/
│   └── rules/
│       ├── 00-api.md                    # API design conventions
│       ├── 01-backend.md                # Backend engineering rules
│       └── 10-architecture.md           # This file: project structure
├── .claudeignore
├── .env                                 # Azure credentials (never commit)
├── .gitignore
├── CLAUDE.md                            # Project instructions and persona
├── LICENSE
├── README.md
├── requirements.txt                     # Python dependencies
├── run_pdf_json_pipeline.py             # CLI runner for PDF→JSON extraction
├── verify_pipeline.py                   # JSON→DB→Tree round-trip verification
│
├── static/                              # PDF inputs and persisted JSON outputs
│   ├── Unilever - FY22.pdf
│   └── Unilever - FY22_*.json           # Extracted JSON (timestamped versions)
│
├── utils/
│   ├── __init__.py
│   ├── azure_ingest_pipeline.py         # Legacy: Azure Content Understanding ingest
│   ├── README_utils.md                  # utils/ folder index
│   │
│   ├── azure_openai/
│   │   ├── __init__.py
│   │   ├── azure_openai.py              # Azure OpenAI client factory, embedding helpers
│   │   ├── ai_search.py                 # Azure AI Search: index mgmt, ingest, hybrid query
│   │   ├── content_understanding.py     # Azure Content Understanding PDF extraction
│   │   └── README_azure_openai.md
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── db_manager.py                # SQLite: schema init, JSON→DB, document queries
│   │   ├── cosmosdb.py                  # Placeholder for Cosmos DB
│   │   └── README_database.md
│   │
│   ├── tree_search_related/
│   │   ├── __init__.py
│   │   ├── pdf_json_pipeline.py         # Multi-pass TOC-first PDF→JSON pipeline
│   │   ├── pdf_json_prompt.py           # Prompts: TOC detect/transform/continue/summarize
│   │   ├── tree_node.py                 # TreeNode class, MCTS selection, tree utilities
│   │   └── README_tree_search_related.md
│   │
│   └── vector_search_related/
│       ├── __init__.py
│       ├── README_vector_search_related.md
│       └── azure_ingest_pipeline.py     # End-to-end PDF→Azure AI Search ingest
```
