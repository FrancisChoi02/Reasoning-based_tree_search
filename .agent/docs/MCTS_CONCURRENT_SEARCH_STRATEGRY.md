# MCTS Concurrent Search Strategy

Reference: [MCTS_SEARCH_STRATEGY.md](MCTS_SEARCH_STRATEGY.md) for the base MCTS flow and [MCTS_REWARD_AND_EVALUATION.md](MCTS_REWARD_AND_EVALUATION.md) for scoring details.

---

## 1. Goal

This document records the **current concurrency strategy** for MCTS search in this project.

The goal was to enable:

1. **Concurrent LLM calls inside one MCTS search**
2. Safe MCTS state handling while doing that

This document reflects the **current implemented progress**, not a future redesign.

---

## 2. Current conclusion

| Question | Current answer |
|---|---|
| Can one MCTS search issue concurrent LLM calls? | **Yes** |
| Is the concurrency applied to the whole tree update flow? | **No** |
| What runs concurrently? | **Leaf evaluation calls within one selected frontier batch** |
| What stays serialized? | **Selection, backpropagation, and visited-state updates** |
| Is this safe with the current mutable `TreeNode` design? | **Yes, only because tree-state mutation is kept serialized** |
| Does this already make multiple searches share one mutable tree safely? | **No** |

The key rule is simple:

> Only parallelize the pure LLM I/O phase. Do not parallelize canonical MCTS state mutation.

---

## 3. Implemented concurrency model

### Phase split

The current search loop is effectively split into three hard phases:

| Phase | Behavior | Concurrency |
|---|---|---|
| **A. Frontier selection** | Select up to `min(max_workers, remaining_iterations)` leaves from the same frontier | Serialized |
| **B. Leaf evaluation** | Send one LLM request per selected leaf through `call_chat_completions_batch(...)` | Concurrent |
| **C. Score commit** | Backpropagate scores and update visited-leaf tracking | Serialized |

This is the current safe boundary.

### Why this is safe

The current `TreeNode` model stores mutable search statistics directly on nodes:

- `visit_count`
- `value_sum`

That means concurrent writes would corrupt:

- UCB1 selection
- iteration accounting
- leaf ranking
- reproducibility of search behavior

So the current implementation does **not** allow worker threads to update `TreeNode` statistics directly.

---

## 4. Current runtime behavior

### 4.1 Frontier batching

Inside one search, the engine now selects a **same-frontier batch** instead of exactly one leaf per loop step.

The batch size is:

```python
min(self.max_workers, remaining_iterations)
```

### 4.2 Duplicate prevention inside one batch

A temporary reservation set is used during batch selection so the same leaf is not selected twice in the same frontier step.

This matters because selection happens before any score commit. Without reservation, the same leaf could be evaluated more than once in the same batch.

### 4.3 Concurrent evaluation transport

The current implementation reuses the shared ordered batch transport:

- `utils/azure_openai/azure_openai.py::call_chat_completions_batch(...)`

That transport already guarantees:

| Guarantee | Why it matters |
|---|---|
| Concurrent request execution | Enables faster same-frontier scoring |
| Stable `request_index` mapping | Preserves leaf-to-result alignment |
| Explicit batch failure | Prevents hidden partial success behavior |

### 4.4 Serialized score commit

After all batch results return, scores are committed one-by-one.

That commit step updates:

- leaf and ancestor `visit_count`
- leaf and ancestor `value_sum`
- visited-leaf tracking

This is intentionally serialized.

---

## 5. What exactly is implemented

| Area | Current status |
|---|---|
| Same-frontier concurrent leaf evaluation | Implemented |
| Ordered batch result mapping | Implemented |
| Explicit failure on batch transport failure | Implemented |
| Explicit failure on request/result order mismatch | Implemented |
| Explicit rejection of boolean `score` values | Implemented |
| Iteration accounting by evaluated leaf count | Implemented |
| Shared-tree-safe parallel multi-search runtime isolation | **Not implemented** |

---

## 6. Current file-level strategy

| File | Current role in concurrency design |
|---|---|
| `utils/tree_search_related/mcts_search.py` | Owns frontier batching, batch evaluation, serialized commit, and result synthesis |
| `utils/azure_openai/azure_openai.py` | Provides ordered concurrent chat batching transport |
| `utils/tree_search_related/tree_node.py` | Still holds mutable MCTS statistics on the node objects |
| `tests/test_mcts_search_concurrency.py` | Covers deterministic batch-selection, batch-evaluation, and iteration-accounting behavior |
| `tests/test_mcts_search.py` | Keeps the smoke-test path for end-to-end MCTS querying |

---

## 7. Current correctness rules

| Rule | Reason |
|---|---|
| Never mutate `TreeNode` search stats from parallel workers | Prevent state corruption |
| Never mix selection and commit in the same concurrent phase | Avoid stale or inconsistent frontier decisions |
| Reserve leaves during batch selection | Prevent duplicate leaf evaluation in one batch |
| Treat one evaluated leaf as one consumed iteration | Keep iteration semantics exact |
| Fail loudly on transport or ordering errors | Match the project's let-it-crash rule |

---

## 8. What this design supports today

### Supported today

| Scenario | Supported? | Notes |
|---|---|---|
| One search, `max_workers=1` | Yes | Uses the same batch path with batch size 1 |
| One search, `max_workers>1` | Yes | Evaluates same-frontier leaves concurrently |
| Multiple independent searches with separate `MCTSQuery` instances | Mostly yes | Safe as long as they do not share mutable node-state in the same in-memory tree object |

### Not supported as a guaranteed-safe shared-state model

| Scenario | Supported? | Why not |
|---|---|---|
| Multiple searches sharing one mutable in-memory `TreeNode` graph and mutating node stats concurrently | No | `TreeNode` still owns mutable search state |
| True parallel MCTS backpropagation on the same tree | No | Would race on `visit_count` and `value_sum` |
| Shared-tree parallel multi-metric search with isolated per-search statistics | No | Needs a separate runtime-state architecture |

---

## 9. Test coverage already aligned with this strategy

The current regression coverage for the concurrency change is centered on `tests/test_mcts_search_concurrency.py`.

| Test focus | Why it matters |
|---|---|
| Unique leaves per frontier batch | Confirms reservation logic works |
| Iteration accounting after batch commit | Confirms one leaf = one consumed iteration |
| `max_workers=1` still uses the batched path | Confirms one code path, not two divergent flows |
| Result-to-leaf order preservation | Confirms safe mapping from batch transport back to tree nodes |
| Order mismatch failure | Confirms no silent corruption |
| Boolean score rejection | Confirms strict parsing |
| Batch failure propagation | Confirms explicit failure behavior |
| Search loop accounting with multi-leaf batches | Confirms total iteration math remains correct |

---

## 10. Practical guidance

If you are working on MCTS concurrency in this repo, follow these rules:

| Do | Do not |
|---|---|
| Batch leaf evaluation requests | Do not batch tree-state mutation |
| Keep `TreeNode` mutation in one serialized commit phase | Do not let worker threads call backpropagation directly |
| Reuse `call_chat_completions_batch(...)` | Do not add a second parallel chat path for the same purpose |
| Validate result ordering explicitly | Do not assume returned order is always correct without checks |
| Keep failure explicit and immediate | Do not add graceful degradation or silent fallback logic |

---

## 11. Bottom line

The current progress is:

- **Done:** single MCTS search with concurrent LLM calls inside one frontier batch
- **Done:** serialized state commit to keep mutable-tree MCTS behavior correct
- **Not done:** safe shared-tree parallel search across multiple metrics using isolated per-search runtime state

So the current strategy is best described as:

> **Frontier-batched concurrent leaf evaluation with serialized MCTS state mutation.**

That is the correct concurrency model for the current codebase.
