# MCTS TPM Consumption & Concurrent Threshold Analysis

Reference: [MCTS_CONCURRENT_SEARCH_STRATEGRY.md](MCTS_CONCURRENT_SEARCH_STRATEGRY.md) for the base concurrency model.

---

## 1. Concurrency Hierarchy (3-tier)

```
Tier 1: Cross-year ThreadPoolExecutor  (max_workers = len(valid_years), typically 5)
 |
 |-- Year 2021 → FinancialSpreadingWorkflow.run()  (sequential phases within year)
 |-- Year 2022 → ...
 |-- Year 2023 → ...
 |-- Year 2024 → ...
 |-- Year 2025 → ...
      |
      Tier 2: MCTSQuery.search()  (num_iterations=10 leaf evaluations, batched)
           |
           Tier 3: call_chat_completions_batch(max_workers)  ← the configurable knob
                |
                ThreadPoolExecutor(max_workers) → concurrent call_chat_completion()
```

---

## 2. Full SCT Table Worst-Case LLM Call Count

### Metric counts (metric_definitions.yaml)

| Category | Count |
|---|---|
| `is_mentioned: true` (displayed) | 26 |
| Non-mentioned direct sub-items | 23 |
| Aggregation sub-items (injected as direct) | 19 |
| **Total metrics resolved** | **68** |

### Per-year MCTS searches (all-resolution-fails worst case)

| Phase | Input type | MCTS Searches |
|---|---|---|
| Phase 1 | 48 direct × 2 attempts (direct + fallback) | 96 |
| Phase 3 | 11 derived_else_direct (direct + 35 components + fallback) | 57 |
| Phase 5 | 48 direct + 11 ded still unresolved | 59 |
| **Total per year** | | **212** |

### LLM calls per single MCTS search (~31)

| Component | Count | Tokens/call (est.) |
|---|---|---|
| Prior seeding (tree descent, metadata only) | ~20 | ~500-1K |
| Leaf evaluation (query + ~3K chars section text) | 10 | ~3K-6K |
| Synthesis (query + full text of top-3 leaves) | 1 | ~6K-15K |
| **Total per MCTS search** | **~31** | |

### Grand total

```
212 MCTS searches/year × ~31 LLM calls = ~6,572 LLM calls/year
~6,572 × 5 years = ~32,860 LLM calls total (full run)
```

---

## 3. Peak TPM Calculation

### Peak concurrent calls by max_workers

| max_workers | Peak concurrent calls | Formula |
|---|---|---|
| 1 | **5** | 5 years × 1 |
| 2 | **10** | 5 years × 2 |
| 3 | **15** | 5 years × 3 (current default) |
| 4 | **20** | 5 years × 4 |

### Peak TPM at typical latencies (per-call ~4K-8K tokens)

| max_workers | 2s latency | 3s latency | 5s latency |
|---|---|---|---|
| 1 | **~750K** ✓ | **~500K** ✓ | **~300K** ✓ |
| 2 | **~1.5M** ✗ | **~1.0M** ⚠ | **~600K** ✓ |
| 3 (current) | **~2.3M** ✗ | **~1.5M** ✗ | **~900K** ⚠ |

✓ = under 1M TPM, ⚠ = borderline, ✗ = exceeds 1M TPM

**Conclusion**: With `max_workers=3` (current default) and 2-3s API latency, peak TPM hits **1.5M-2.3M**, well above the 1M TPM threshold. This is why 429 errors occur.

---

## 4. Why Retries Compound the Problem

`call_chat_completion` retries up to 3× with exponential backoff (1s → 2s → 4s). A 429 from rate limiting triggers a retry, which itself adds to the concurrent call count. With `max_workers=3` and 5 years:

- 15 concurrent calls fire → some get 429 → each retries after 1s
- Those retries overlap with the next batch's calls
- Effective concurrency briefly spikes above 15

This creates a cascade: more calls → more 429s → more retries → even more calls.

---

## 5. Recommended Settings

### For 1M TPM with 5 concurrent years

| Setting | Value | Reason |
|---|---|---|
| `max_workers` | **1** | Peak ~750K TPM at 2s latency. Safe margin. |
| `num_iterations` | 10 (unchanged) | Affects accuracy more than throughput |
| Year concurrency | 5 (unchanged) | Required for 5-year analysis |

### Runtime impact of max_workers=1 vs max_workers=3

- Leaf evaluation batches are 3× smaller → MCTS leaf eval phase is ~3× slower
- Prior seeding (~20 sync calls/search) and synthesis are unaffected
- **Total runtime increase: ~30-50%** (leaf evals are ~30% of total LLM calls)
- Trade-off: slower but no 429s = net faster than retries

---

## 6. Configuration Surface

| Layer | Parameter | Where to set |
|---|---|---|
| API request | `max_workers` | `POST /api/spread` body (default 1) |
| Factory default | `max_workers` | `mcts_search_factory.py` default_kwargs |
| Frontend | Workers input | Header number input (default 1) |

The API request value takes precedence over the factory default (via `setdefault`).

---

## 7. Request Rate (RPM) Not the Bottleneck

At 10K RPM (166 req/s):

| max_workers | Peak req/s | % of limit |
|---|---|---|
| 1 | ~2.5 | 1.5% |
| 3 | ~7.5 | 4.5% |
| 5 | ~12.5 | 7.5% |

RPM is never the constraint. **TPM is the binding limit.** Azure OpenAI's token-based rate limiting triggers 429s long before the request-rate limit is reached.
