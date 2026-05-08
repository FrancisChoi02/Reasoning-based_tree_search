
Please develope based on the following requirements and edit the existing code to fix the gaps.
Give me a test script in tests for each gap accordingly.



# Requirement

## frontend
For all the SCT Table, add one more column named 'YoY Change'. This column should display the year-over-year change in the metric value in lastest two years for each metric(e.g 2025 and 2024).

## run_pdf_json_pipeline()
- I want the sqlite DB be situated in the 'static' directory.
- When we process file to DB, I want to add two parameters: 'company' and 'year_period' to be stored in the DB.

## MCTSQuery
## _load_forest_from_db()
When we initialize MCTSQuery, I want to load the forest from DB based on the company and year_period.
So that I can query the specific forest for every metric.



# Gaps
Gap analysis                                                             
                                                                           
  Gap 1 (High): _resolve_aggregations() — no progress callback             
                                                                           
  financial_spreading_workflow.py:417-488 — When Equity, Reserves, Short   
  Term Debt, and Long Term Debt are computed from their sub-items in Phase 
  2, no _progress_callback fires. The frontend never hears about these 4   
  aggregation metrics until the entire run() returns.       

  Gap 2 (High): No multi-year resolution                                   
  
  The frontend has 5 year columns (FY21–FY25). The workflow resolves one   
  snapshot at a time — you'd have to call run() 5 times sequentially, each
  re-doing the topological sort, definition loading, and all 5 resolution  
  phases. There's no shared cache across years.

  Gap 3 (Medium): Synchronous batch return                                 
  
  run() returns the complete assembled SCT table at the end. The frontend  
  integration doc (Section 6) explicitly calls for SSE or WebSocket
  streaming: { rowIndex, year, value, formula, source, error? }. The       
  progress_callback is the right hook, but it's not wired to any streaming
  transport.

  Gap 4 (Low): is_mentioned: false noise                                   
  
  _resolve_and_store() fires the progress callback for every metric —      
  including 23 intermediate/component metrics with is_mentioned: false. The
   frontend only has cells for the 26 mentioned metrics. It would have to  
  filter out noise.                                         

  ---                                                                      
                                                                           
  1. Add _progress_callback to _resolve_aggregations()      
  2. Add a run_for_years(years: list[str]) method that resolves multiple   
  years with a shared MCTS cache                                           
  3. Add an as_sse_event() serialization method on Metric for the streaming
   transport                                                               
  4. Filter progress callbacks to only fire for is_mentioned: true metrics
  (or let the frontend filter by checking a flag)                          


