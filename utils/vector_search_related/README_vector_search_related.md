# utils/vector_search_related index

| File | Purpose |
|---|---|
| `azure_ingest_pipeline.py` | End-to-end local PDF ingest pipeline from Content Understanding into Azure AI Search. Normalizes documents (with `company_name`/`year` metadata), generates document IDs, and orchestrates ingestion. Depends on `azure_openai/content_understanding.py` and `azure_openai/ai_search.py`. |

If folder contents change, update this index.
