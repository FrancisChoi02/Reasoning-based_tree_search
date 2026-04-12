# Lessons Learned

## 2026-04-12: end_index < start_index in tree construction

**Root cause**: When adjacent TOC entries share the same physical page and `appear_start == "yes"`, `post_process_toc_to_tree` computed `end_index = next_physical_index - 1`, which can equal `start_index - 1`. Same issue in `subdivide_large_nodes` when adjusting parent boundaries after subdivision.

**Fix**: Clamp with `max(computed_end, start_index)` in both `post_process_toc_to_tree` and `subdivide_large_nodes`.

**Prevention**: Always validate `end_index >= start_index` after any arithmetic on page boundaries. The DB CHECK constraint caught this — good design.

---

## 2026-04-08: Flat extraction produces no hierarchy

**Root cause**: The prompt schema showed `nodes: []` (empty array) with no hierarchy instruction. The LLM correctly treated every section as a leaf. No post-processing step existed to reconstruct parent-child relationships.

**Fix**: Complete architectural rewrite to TOC-first multi-pass extraction. The hierarchy now comes from the document's actual Table of Contents structure (or LLM-inferred structure when no TOC exists), not from asking the LLM to invent it per chunk.

**Prevention**: When the desired output is a tree, the extraction strategy must be tree-aware from the start. Flat extraction + post-hoc grouping is fundamentally weaker than structural extraction.
