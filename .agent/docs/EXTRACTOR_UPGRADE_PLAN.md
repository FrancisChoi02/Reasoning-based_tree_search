Aspect: Cross-chunk merging
  Your pdf_json_pipeline: normalize_extraction_results() just concatenates records arrays
  Pageindex page_index: Builds a single global TOC, then maps pages, then recursively
  splits
    large nodes

  Why your output is 295 roots, max depth 1

  The root cause is your prompt in pdf_json_prompt.py:32-53. Three specific problems:

  1. No hierarchy instruction. The prompt says "extract structured section records from the
   given PDF text chunk" — it never asks the LLM to produce nested sections. The output
  schema at line 18-28 shows nodes: [] (an empty array), signaling to the model that each
  record is a leaf.
  2. Chunk-isolated extraction. Each 6-page chunk is processed independently. The LLM has
  no visibility into the document's overall structure (no TOC, no global context). It can
  only see what's in those 6 pages, so it extracts every heading it sees as a top-level
  flat record.
  3. No post-processing to build hierarchy. Your pipeline's normalize_extraction_results()
  simply concatenates all chunk results. There's no step that reconstructs parent-child
  relationships from the flat records.

  What the pageindex sample does differently (the multi-pass architecture)

  The pageindex pipeline is fundamentally different — it's a multi-pass, TOC-driven
  approach:

  ┌────────────────┬───────────────────────────────────────────────────────────────────┐
  │      Pass      │                           What happens                            │
  ├────────────────┼───────────────────────────────────────────────────────────────────┤
  │ 1. TOC         │ check_toc() scans the first N pages using LLM to find a Table of  │
  │ detection      │ Contents                                                          │
  ├────────────────┼───────────────────────────────────────────────────────────────────┤
  │ 2. TOC         │ toc_transformer() converts raw TOC text → flat list with          │
  │ extraction     │ structure field ("1", "1.1", "1.2.1", etc.)                       │
  ├────────────────┼───────────────────────────────────────────────────────────────────┤
  │ 3. Page        │ Maps TOC entries to physical page numbers using the document's    │
  │ mapping        │ page indices, or by scanning pages with LLM                       │
  ├────────────────┼───────────────────────────────────────────────────────────────────┤
  │ 4.             │ verify_toc() checks random samples: does the section title        │
  │ Verification + │ actually appear on the mapped page? If accuracy < 60%, it falls   │
  │  fix           │ back to a different mode                                          │
  ├────────────────┼───────────────────────────────────────────────────────────────────┤
  │ 5. Tree        │ post_processing() + list_to_tree() converts the flat              │
  │ construction   │ structure-annotated list into a nested tree using the dot         │
  │                │ notation (parent of "1.2.3" is "1.2")                             │
  ├────────────────┼───────────────────────────────────────────────────────────────────┤
  │ 6. Recursive   │ process_large_node_recursively() — for any leaf node spanning >   │
  │ splitting      │ 10 pages / > 20k tokens, it recursively runs the whole extraction │
  │                │  pipeline on just those pages to discover sub-sections            │
  ├────────────────┼───────────────────────────────────────────────────────────────────┤
  │ 7. Enrichment  │ Optionally adds node_id, text (page content per node), summary,   │
  │                │ prefix_summary, doc_description                                   │
  └────────────────┴───────────────────────────────────────────────────────────────────┘

  What determines depth: the structure field in the TOC ("1" → depth 0, "1.1" → depth 1,
  "1.1.1" → depth 2). For documents without a TOC, generate_toc_init() /
  generate_toc_continue() ask the LLM to invent the hierarchy, and
  process_large_node_recursively() expands deep nodes on demand.

  What determines leaf nodes: any node where process_large_node_recursively() decides it
  doesn't need further splitting (either the page range or token count is below the
  threshold in config.yaml: max_page_num_each_node: 10, max_token_num_each_node: 20000).

  Bottom line

  Your pipeline is a single-pass flat extractor. The pageindex sample is a multi-pass
  hierarchical builder that treats the TOC as the primary structural source. To get deeper
  trees, you'd need to either:
  - Switch to a TOC-first extraction strategy (like pageindex)