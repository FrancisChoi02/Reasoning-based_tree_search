# MCTS Search Strategy

## 1. What is MCTS

Monte Carlo Tree Search (MCTS) is a best-first search algorithm that builds a partial search tree by iteratively evaluating the most promising paths. It balances **exploitation** (visiting nodes that previously scored well) and **exploration** (visiting unexplored nodes) through the UCB1 formula.

MCTS runs in a 4-phase loop:

| Phase               | Action                                                   | In This Project                                                          |
| ------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------ |
| **Selection**       | Walk from root to a leaf using a selection policy (UCB1) | Traverse the document tree: root → section → subsection → leaf           |
| **Evaluation**      | Estimate the value of the selected node                  | LLM scores how relevant the leaf's text is to the user's query (0.0–1.0) |
| **Backpropagation** | Update visit counts and value sums up the path to root   | Propagate the score to all ancestors                                     |
| **Best pick**       | After N iterations, return the highest-scoring leaf(es)  | Collect top-K leaves, synthesize answer via LLM                          |

Unlike game trees where children are generated dynamically, our document tree is **pre-built** (171 nodes, 144 leaves, depth 6). The "expansion" phase is unnecessary — all children already exist. MCTS here is purely a **focused evaluation** strategy: instead of scoring all 144 leaves (expensive), it scores only the most promising \~10–20.

**Why MCTS instead of brute-force or flat retrieval:**

| Approach                         | LLM calls  | Quality       | Notes                                  |
| -------------------------------- | ---------- | ------------- | -------------------------------------- |
| Score all 144 leaves             | 144        | Best baseline | Expensive, slow                        |
| BM25/vector similarity on titles | 0 (no LLM) | Poor          | Titles alone don't carry enough signal |
| MCTS (10 iterations)             | \~10       | Near-optimal  | UCB1 focuses on relevant subtrees      |

***

## 2. How to Map MCTS to the JSON Tree

### Current tree structure (Unilever FY22, 241 pages)

```
Root: Document (5 roots)
├── Strategic Report                    [pages 3–78]
│   ├── About Unilever                  [pages 3–9]
│   │   ├── Unilever at a glance        [pages 5–7, leaf, text=6305 chars]
│   │   └── The Unilever Compass        [pages 7–9, leaf, text=11428 chars]
│   ├── Review of the Year              [pages 9–54]
│   │   ├── Chair's statement           [pages 9–11, leaf, text=22787 chars]
│   │   └── CEO's statement             [pages 11–13, leaf, text=25368 chars]
│   └── ...
├── Governance Report                   [pages 80–135]
├── Financial Statements                [pages 136–228]
└── Additional Information              [pages 229–241, leaf]
```

### MCTS mapping

| MCTS Concept           | Mapping                                                                                        |
| ---------------------- | ---------------------------------------------------------------------------------------------- |
| **Game state**         | A node in the document tree                                                                    |
| **Legal moves**        | The children of the current node                                                               |
| **Terminal state**     | A leaf node (no children)                                                                      |
| **Simulation/Rollout** | LLM evaluates: "How relevant is this leaf's text to the query?" → score 0.0–1.0                |
| **Reward**             | The relevance score                                                                            |
| **UCB1 selection**     | `value + C * sqrt(ln(parent.visits) / node.visits)` — already implemented in `TreeNode.ucb1()` |

### What each node provides for evaluation

| Node type                    | Available data                                                                               | Use in MCTS                                |
| ---------------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Internal node (has children) | `title`, `start_index`/`end_index`, `depth`, `summary` (if generated)                        | Selection only — UCB1 picks the best child |
| Leaf node (no children)      | `title`, `start_index`/`end_index`, `text_content` (avg 14k chars), `summary` (if generated) | Evaluation — LLM scores relevance          |

### Cold start

All nodes start with `visit_count=0`, `value_sum=0.0`. UCB1 returns `+inf` for unvisited nodes, so the first iterations explore different branches. After 3–5 iterations, values differentiate and MCTS starts exploiting.

***

## 3. MCTS Search Process for This Project

### Architecture

```
User Query
    │
    ▼
┌──────────────┐
│  Load Tree   │  ← load_tree_from_db(doc_pk, db_path) → TreeNode root
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  MCTS Loop   │  × N iterations (default: 10)
│  ┌──────────┐│
│  │ Select   ││  root → ... → leaf via UCB1
│  ├──────────┤│
│  │ Evaluate ││  LLM(query, leaf.text_content) → score
│  ├──────────┤│
│  │ Backprop ││  leaf → root: visit_count++, value_sum += score
│  └──────────┘│
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Collect TopK │  Sort leaves by (value × visit_count), pick top-K
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Synthesize  │  LLM(query, top-K leaf texts) → final answer
└──────────────┘
```

### Phase A: Selection

```python
def _select(self, node: TreeNode) -> TreeNode:
    """Walk from node to a leaf using UCB1."""
    while not node.is_leaf:
        node = node.best_child_ucb1(exploration_weight=1.414)
    return node
```

- Already implemented: `TreeNode.best_child_ucb1()` (line 74 of tree\_node.py)
- `exploration_weight=1.414` (sqrt(2)) is the standard UCB1 constant
- At internal nodes with unvisited children, UCB1 returns `+inf` for those children, ensuring full exploration before exploitation

### Phase B: Leaf Evaluation

```python
def _evaluate(self, leaf: TreeNode, query: str) -> float:
    """Score leaf relevance to query. Returns 0.0–1.0."""
    prompt = build_relevance_prompt(query, leaf.title, leaf.text_content)
    response = call_llm_raw(prompt=prompt, temperature=0.0)
    score = parse_relevance_score(response)
    return score
```

**Prompt design** (new prompt to add to `pdf_json_prompt.py`):

```
You are a relevance scoring engine.

Given a user question and a document section, score how relevant the section is
to answering the question.

Question: {query}

Section title: {title}
Section text (excerpt, first 3000 chars):
{text_content[:3000]}

Reply with ONLY a JSON object:
{"thinking": "<brief reasoning>", "score": <float between 0.0 and 1.0>}
```

**Key design decision — text truncation**: Leaf text ranges from 2k to 95k chars. For evaluation, we truncate to the first \~3000 chars (roughly 750 tokens). This keeps LLM calls cheap and fast. If needed, a follow-up "deep read" on the top-K leaves can use the full text during synthesis.

### Phase C: Backpropagation

```python
def _backpropagate(self, leaf: TreeNode, score: float) -> None:
    """Propagate score up to root."""
    node = leaf
    while node is not None:
        node.visit_count += 1
        node.value_sum += score
        node = node.parent
```

Already supported: `TreeNode.visit_count`, `TreeNode.value_sum`, `TreeNode.parent`.

### Phase D: Collect Results and Synthesize Answer

After N MCTS iterations, collect leaves sorted by value (average score):

```python
def _collect_top_k(self, root: TreeNode, k: int = 3) -> List[TreeNode]:
    """Find the K leaves with the highest average relevance score."""
    all_leaves = collect_leaves(root)
    scored = [(leaf, leaf.value) for leaf in all_leaves if leaf.visit_count > 0]
    scored.sort(key=lambda x: -x[1])
    return [leaf for leaf, _ in scored[:k]]
```

Then pass the top-K leaves' full text to an LLM for answer synthesis:

```
Answer the question based on the following document sections.

Question: {query}

Section 1 — {title1} (pages {start1}–{end1}):
{text_content_1}

Section 2 — {title2} (pages {start2}–{end2}):
{text_content_2}

Section 3 — {title3} (pages {start3}–{end3}):
{text_content_3}

Provide a comprehensive answer. Cite page numbers where relevant.
```

### Cost analysis

| Component        | LLM calls      | Approximate tokens per call                       |
| ---------------- | -------------- | ------------------------------------------------- |
| Selection (UCB1) | 0              | Pure computation, no LLM                          |
| Leaf evaluation  | N (default 10) | \~800 prompt + \~50 response                      |
| Answer synthesis | 1              | \~(K × avg\_leaf\_tokens) prompt + \~500 response |
| **Total**        | N + 1 (\~11)   | \~8,500 + K × leaf\_text                          |

***

## 4. Minimally Runnable Version (MVP)

### What to build

One new file: `utils/tree_search_related/mcts_search.py`

This file contains:

1. `MCTSQuery` class — orchestrates the search loop
2. Two new prompts in `pdf_json_prompt.py` — relevance scoring + answer synthesis

### File layout

```
utils/tree_search_related/
├── mcts_search.py        ← NEW: MCTS orchestration + answer synthesis
├── pdf_json_prompt.py    ← MODIFY: add 2 prompts (relevance + synthesis)
├── pdf_json_pipeline.py  ← NO CHANGE
├── tree_node.py          ← NO CHANGE (already has UCB1, visits, values)
└── README_tree_search_related.md  ← UPDATE: add mcts_search.py entry
```

### `mcts_search.py` — Class design

```python
class MCTSQuery:
    """Query a document tree using MCTS to find relevant sections."""

    def __init__(
        self,
        doc_pk: int,
        db_path: str = "tree_poc.db",
        model: str = "gpt-5.4",
        num_iterations: int = 10,
        top_k: int = 3,
        exploration_weight: float = 1.414,
        max_eval_tokens: int = 3000,
    ):
        # Load tree from DB, store config

    def search(self, query: str) -> dict:
        """Run MCTS and return top-K results with synthesized answer."""
        self._reset_tree()          # Zero out visit_count/value_sum
        for _ in range(self.num_iterations):
            leaf = self._select()   # UCB1 traversal
            score = self._evaluate(leaf, query)  # LLM scores relevance
            self._backpropagate(leaf, score)      # Update ancestors
        top_leaves = self._collect_top_k()
        answer = self._synthesize(query, top_leaves)  # LLM generates answer
        return {
            "query": query,
            "answer": answer,
            "sources": [
                {
                    "title": leaf.title,
                    "pages": f"{leaf.start_index}-{leaf.end_index}",
                    "score": leaf.value,
                    "visits": leaf.visit_count,
                }
                for leaf in top_leaves
            ],
            "iterations": self.num_iterations,
        }
```

### New prompts in `pdf_json_prompt.py`

```python
def build_relevance_prompt(query: str, title: str, text_excerpt: str) -> str:
    """Prompt for scoring a leaf node's relevance to a query."""

def build_synthesis_prompt(query: str, sections: list[dict]) -> str:
    """Prompt for synthesizing an answer from top-K relevant sections."""
```

### Runner: `run_mcts_search.py` (new CLI entry point)

```python
# Usage:
python run_mcts_search.py --db tree_poc.db --doc "Unilever - FY22.pdf" \
    --query "What was Unilever's revenue in 2022?" --iterations 10
```

### Dependency graph

```
run_mcts_search.py
  └── mcts_search.py
        ├── tree_node.py          (load_tree_from_db, collect_leaves, TreeNode)
        ├── pdf_json_prompt.py    (build_relevance_prompt, build_synthesis_prompt)
        ├── db_manager.py         (get_document — lookup doc_pk by name)
        └── azure_openai.py       (get_azure_openai_client, get_chat_deployment_name)
```

### Test plan

| Test                              | Method                                                                                          | Expected                                                  |
| --------------------------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| MCTS converges on correct subtree | Query "What was revenue in 2022?" → check that top leaves are in "Financial Statements" subtree | Top-3 leaves under `Financial Statements` root            |
| Answer quality                    | Query "Who is the CEO?" → answer mentions the CEO by name                                       | Correct name from "Strategic Report > Review of the Year" |
| Cold start exploration            | First 5 iterations visit 5 different subtrees                                                   | visit\_count distributed across >3 roots                  |
| Empty query handling              | Pass empty string                                                                               | Raise ValueError                                          |
| Single-iteration fallback         | num\_iterations=1                                                                               | Returns exactly 1 source, answer still valid              |

### What this MVP does NOT include (future milestones)

| Feature                                 | Milestone | Why deferred                                                                     |
| --------------------------------------- | --------- | -------------------------------------------------------------------------------- |
| Summary-based pruning at internal nodes | M3+       | Requires summaries to be generated first (currently 0/144 leaves have summaries) |
| Multi-document search                   | M3+       | Needs cross-document root, not just single doc\_pk                               |
| Vector embedding of leaves              | M4        | Hybrid tree + vector search                                                      |
| Adaptive iteration count                | M3+       | Stop early if value converges                                                    |
| Parallel leaf evaluation                | M3+       | ThreadPoolExecutor for batch scoring                                             |

### Implementation order

1. Add `build_relevance_prompt()` and `build_synthesis_prompt()` to `pdf_json_prompt.py`
2. Create `mcts_search.py` with `MCTSQuery` class
3. Create `run_mcts_search.py` CLI entry point
4. Test on Unilever FY22 with 3 queries covering different document areas
5. Update README and architecture docs

