# Plan: Add `company_name` and `year` metadata fields for chunk filtering

## Goal
Add `company_name` and `year` as:
1. **Input parameters** when ingesting a PDF (caller provides them)
2. **Top-level filterable fields** in the Azure AI Search index (not buried inside `metadata_json`)
3. **Returned fields** in query results

## Why top-level fields instead of stuffing into `metadata_json`?
Azure AI Search can only filter on top-level `filterable` fields. If we bury them in `metadata_json` (a plain string), downstream `$filter` expressions like `company_name eq 'Unilever' and year eq 2022` won't work. So they must be proper index fields.

---

## Changes (4 files)

### 1. `utils/ai_search.py` — Index schema + query select list
- [x] Add two new fields to `_build_index_definition()`:
  - `company_name`: `SimpleField(type=String, filterable=True)`
  - `year`: `SimpleField(type=Int32, filterable=True)`
- [x] Add `company_name` and `year` to the `select` list in `query_documents()`
- [x] Include `company_name` and `year` in the returned dict in `query_documents()`

### 2. `utils/azure_ingest_pipeline.py` — Document normalization + ingestion entry point
- [x] `build_search_documents()`: propagate `company_name` and `year` from input dicts into the normalized output
- [x] `build_documents_from_pdf()`: accept `company_name: str` and `year: int`, pass them through to every document dict returned by `extract_content_understanding_documents()`
- [x] `ingest_local_pdf()`: accept `company_name: str` and `year: int`, pass to `build_documents_from_pdf()`

### 3. `utils/content_understanding.py` — Chunk extraction
- [x] `extract_content_understanding_documents()`: accept `company_name: str` and `year: int`, inject them into every document dict it builds

### 4. `utils/README_utils.md` — Fractal doc sync
- [x] Update the folder-level index to reflect the new parameters

---

## Edge cases / notes
- **Existing index**: Adding new fields to an existing Azure AI Search index requires either deleting and recreating the index, or using the update API (which supports additive field changes). We'll rely on `ensure_index()` — if the index already exists without these fields, it will pass validation (since we only validate the vector field). The user will need to delete & recreate the index to pick up new fields if the index already exists. I'll add a print warning for this.
- **`year` type**: `Int32` — expects an integer, not a string like "FY22". The caller is responsible for passing the numeric year (e.g., `2022`).
- **Backward compatibility**: Both `company_name` and `year` will default to `""` / `0` in `build_search_documents()` so old code paths that don't supply them won't break.
