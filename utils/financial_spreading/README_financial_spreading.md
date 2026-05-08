# utils/financial_spreading index

| File | Purpose |
|---|---|
| `resolve_metric.py` | `FormulaEvaluator` — safe recursive-descent arithmetic parser that substitutes metric names with values. `MetricResolver` — resolves a single MetricDefinition via direct (MCTS search), derived (formula evaluation), or fallback strategies. |
| `financial_spreading_workflow.py` | `FinancialSpreadingWorkflow` — orchestrates the full spreading pipeline: loads YAML definitions, topologically sorts by dependency, resolves in 5 phases (direct → aggregations → derived_else_direct → derived → fallback), assembles SCT table grouped by statement_type. Exposes `progress_callback` for frontend live updates. |
| `__init__.py` | Re-exports: `FormulaEvaluator`, `MetricResolver`, `FinancialSpreadingWorkflow`. |

If folder contents change, update this index.
