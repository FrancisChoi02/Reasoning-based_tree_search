# utils index

- `utils/ai_search.py` — Azure AI Search index creation (with `company_name`/`year` filterable fields), schema synchronization, document ingestion, and hybrid/vector query helpers.
- `utils/azure_ingest_pipeline.py` — End-to-end local PDF ingest pipeline from Content Understanding into Azure AI Search. Accepts `company_name` and `year` as input parameters for chunk-level metadata.
- `utils/azure_openai.py` — Azure OpenAI embedding client and embedding helper functions.
- `utils/content_understanding.py` — Azure Content Understanding client, default model deployment setup, and markdown-block extraction for local PDFs. Splits large PDFs into 50-page batches to stay within API limits. Injects `company_name` and `year` into every extracted document dict.
- `utils/cosmosdb.py` — Placeholder for Cosmos DB integration.
