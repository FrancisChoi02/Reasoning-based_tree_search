First, a metric-definition class is required to load metric definitions from `metric_definitions.yaml`.  
It must expose the following mandatory fields:  
- `metric_type` – e.g. `direct`, `derived`, `derived_else_direct`  
- `statement_type` – the SCT-table section the metric belongs to (`Balance sheet`, `Income statement`, `Cash flow`, `Others`)  
- `is_mentioned` – `True` if the metric must be explicitly shown in the SCT table; `False` if it is only an intermediate value  
- `component_metrics` – list of the metric’s building-block metrics, e.g. for Net Funded Debt: `[Total Ext. Funded Debt, Cash + Mkt Securities]`  
- `formula_note` – string formula used to derive the metric, e.g. `Total Ext. Funded Debt - (Cash + Mkt Securities)`  
- `synonyms` – list of synonymous expressions that help the MCTS search locate the correct figure  

`metric_definitions.yaml` stores every metric used during financial spreading; its content can be harvested from  
`Excel Financial Data Extraction.xlsx`, `SCT_Table_missing_aggregation_items.xlsx` and `SCT_Table_missing_items.xlsx`.

Financial-spreading workflow:
1. Load `metric_definitions.yaml` to obtain all metric definitions, aggregation-item compositions and calculation rules.  
2. Resolve metrics in the order below, calling `resolve_metric()` for each.  
3. Assemble the final SCT table from the resolved values.

Metric resolution order:
1. Directly retrieve `direct` metrics via MCTS search on `json_pdf` (query built with synonyms).  
   - Covers both `is_mentioned = True` metrics and component metrics whose `is_mentioned = False`.  
2. Compute `derived_else_direct` and `derived` metrics from their component metrics using the supplied formulas.  
3. If any metric remains unresolved because its components are missing, perform an MCTS search on `json_pdf` for the metric itself (again using synonyms).  
4. If still unavailable, set the metric value to `NA`.

`resolve_metric()` relies on a robust evaluator that can parse string formulas and compute the metric value.

Front-end behaviour:
- After a metric is calculated, its cell in the UI should update immediately; no need to wait for the remaining metrics.  
- When hovering over a metric after spreading completes, the tooltip should display:  
  – metric type  
  – derivation formula (if derived)  
  – the actual values of its component metrics  
  – the file name & location where the metric (and each component) was found




