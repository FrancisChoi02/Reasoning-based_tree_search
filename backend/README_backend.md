# backend/ — Financial Spreading FastAPI Backend

**Input:** HTTP requests from the SCT frontend, `metric_definitions.yaml`, SQLite DB
**Output:** JSON responses (`/api/ingest`) and SSE event streams (`/api/spread`)
**Position:** Service layer bridging the frontend to the PDF extraction pipeline,
  MCTS engine, and financial-spreading workflow. If modified, update this index.

---

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, CORS middleware, `/api/ingest` and `/api/spread` endpoints |
| `tree_verifier.py` | Pre-flight check: verify 5 document trees exist and are searchable |
| `mcts_search_factory.py` | Create per-year MCTS search functions for the workflow |

## API Reference

### POST /api/ingest

Ingest a PDF into the SQLite document tree.

```
Body: { file_path, company_name, year_period }
Response: { status, doc_pk, doc_name, node_count, processing_time_seconds }
```

### POST /api/spread

Stream financial spreading results via SSE.

```
Body: { company_name, year_periods[], metrics[{row_index, metric_name}] }
Response: text/event-stream

SSE Events:
  { event: "tree_verification", results: { FY21: {...}, ... } }
  { canonical_name, year, row_index, value, status, formula, error }
  { event: "complete" }
```

## Running

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

## Dependencies

- FastAPI + uvicorn (web framework)
- Existing project packages (azure_openai, database, tree_search_related, financial_spreading)

If folder contents change, update this index.
