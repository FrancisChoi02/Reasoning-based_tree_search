# utils/azure_openai index

| File | Purpose |
|---|---|
| `azure_openai.py` | Shared Azure OpenAI client factory, chat completion request/result wrappers, single/batch chat completion helpers, and embedding functions. |
| `ai_search.py` | Azure AI Search index creation (with `company_name`/`year` filterable fields), schema sync, document ingestion, and hybrid/vector query helpers. Depends on `azure_openai.py` and `vector_search_related/azure_ingest_pipeline.py`. |
| `content_understanding.py` | Azure Content Understanding client, default model deployment, markdown-block extraction for local PDFs. Splits large PDFs into 50-page batches. Injects `company_name`/`year` metadata. |

If folder contents change, update this index.
