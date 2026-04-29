# Lessons Learned

## 2026-04-30: Batch leaf evaluation, not MCTS state mutation

**Root cause**: It is tempting to parallelize MCTS by updating node visit/value statistics from multiple worker threads at the same time, but the current tree state lives directly on mutable `TreeNode` instances. That would make selection and backpropagation race-prone and hard to reason about.

**Fix**: Keep frontier selection and score commits serialized, and only parallelize the independent LLM leaf evaluation calls through the shared `call_chat_completions_batch(...)` transport. Reserve leaves inside each batch so one frontier step does not evaluate the same leaf twice.

**Prevention**: When adding concurrency to tree search, first isolate which phase is pure I/O and which phase mutates canonical search state. Only the pure I/O phase should run concurrently unless the state model is redesigned first.

---

## 2026-04-17: Keep a root-level MCTS search smoke test for document-tree querying

**Root cause**: The repo had extraction verification and direct Azure chat transport verification, but no narrow root-level runner for the actual MCTS query path. That made search-layer debugging slower because tree traversal, scoring prompts, and synthesis could only be reasoned about indirectly.

**Fix**: Keep `test_mcts_search.py` at the repo root so document-tree MCTS search can be exercised directly with one question, one document, and explicit pass/fail checks.

**Prevention**: Whenever a new orchestration layer is introduced on top of shared transport utilities, add one root-level smoke test that validates the orchestration path directly before relying on larger end-to-end flows.

---


**Root cause**: The previous manual validation path depended on the full PDF pipeline, which mixes extraction flow concerns with Azure chat transport concerns. That makes concurrency debugging slower and noisier.

**Fix**: Add `test_call_chat_completions_batch.py` at the repo root so the shared `call_chat_completions_batch(...)` wrapper can be tested directly for ordered concurrent execution.

**Prevention**: When introducing shared transport primitives, always add one narrow root-level smoke test that exercises the primitive directly before validating it through larger pipelines.

---

## 2026-04-17: Centralize Azure OpenAI chat calling before adding MCTS concurrency

**Root cause**: The codebase duplicated Azure chat completion logic inside `pdf_json_pipeline.py`, while concurrency lived only at the caller layer. That would have forced MCTS to add another custom calling path, making retries, ordering, and rate-limit handling inconsistent.

**Fix**: Move chat completion transport into `utils/azure_openai/azure_openai.py` with one normalized single-call wrapper and one ordered concurrent batch wrapper built on top of it. Then refactor pipeline helpers to consume that shared path.

**Prevention**: Before adding LLM-heavy features like MCTS, centralize request transport first. Retrieval logic should not own SDK wiring, retry math, or concurrency primitives.

---

## 2026-04-12: end_index < start_index in tree construction

**Root cause**: When adjacent TOC entries share the same physical page and `appear_start == "yes"`, `post_process_toc_to_tree` computed `end_index = next_physical_index - 1`, which can equal `start_index - 1`. Same issue in `subdivide_large_nodes` when adjusting parent boundaries after subdivision.

**Fix**: Clamp with `max(computed_end, start_index)` in both `post_process_toc_to_tree` and `subdivide_large_nodes`.

**Prevention**: Always validate `end_index >= start_index` after any arithmetic on page boundaries. The DB CHECK constraint caught this — good design.

---

## 2026-04-08: Flat extraction produces no hierarchy

**Root cause**: The prompt schema showed `nodes: []` (empty array) with no hierarchy instruction. The LLM correctly treated every section as a leaf. No post-processing step existed to reconstruct parent-child relationships.

**Fix**: Complete architectural rewrite to TOC-first multi-pass extraction. The hierarchy now comes from the document's actual Table of Contents structure (or LLM-inferred structure when no TOC exists), not from asking the LLM to invent it per chunk.

**Prevention**: When the desired output is a tree, the extraction strategy must be tree-aware from the start. Flat extraction + post-hoc grouping is fundamentally weaker than structural extraction.
