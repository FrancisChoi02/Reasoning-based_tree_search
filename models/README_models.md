# models index

| File | Purpose |
|---|---|
| `MetricDefinition.py` | Immutable dataclass: canonical_name, input_type, metric_type, statement_type, is_mentioned, component_metrics, formula_note, synonyms, derivation_code. Loaded from `metric_definitions.yaml` via `from_dict()`. |
| `Metric.py` | Resolved metric value object: value, status (pending/resolved/partial/unresolved), resolution_method, formula_used, additional_context (ComponentDetail list + status_note). Also exports `ComponentDetail` and `AdditionalContext` TypedDict-like dataclasses. |
| `__init__.py` | Re-exports: `MetricDefinition`, `Metric`, `ComponentDetail`, `AdditionalContext`. |

If folder contents change, update this index.
