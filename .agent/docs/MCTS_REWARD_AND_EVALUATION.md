# MCTS Reward Mechanism & LLM Evaluation Design

Reference: [MCTS_SEARCH_STRATEGY.md](MCTS_SEARCH_STRATEGY.md) — overall search architecture.

---

## 1. Reward Overview

MCTS needs a reward signal at two moments:

| Moment | Method | Input | Cost | Purpose |
|---|---|---|---|---|
| **Prior** (before MCTS loop) | Batch title scoring | Query + sibling titles per parent | ~3–4 calls total | Seed UCB1 so first iterations aren't random |
| **Leaf** (each MCTS iteration) | Text relevance scoring | Query + path + text head+tail | 1 call per iteration | Actual reward signal for backpropagation |
| **Synthesis** (after MCTS loop) | Answer generation | Query + top-K full texts | 1 call | Produce the final answer |

The reward flows through UCB1 via **standard average propagation**:

```
node.value = node.value_sum / node.visit_count
```

No custom propagation (max, discounted, etc.). Average propagation is the only strategy with UCB1 convergence guarantees. The cold-start problem is addressed by priors, not by changing the propagation math.

---

## 2. Prior Evaluation (Title-Based Routing)

### Purpose

Without priors, all nodes start at `visit_count=0`, `value_sum=0`. UCB1 returns `+inf` for every unvisited child, so the first N iterations just round-robin through siblings. For the 43-child "Notes to the consolidated financial statements" node, that's 43 wasted iterations.

Priors inject a "soft guess" per child so UCB1 has a signal from iteration 1.

### Method

Batch all children of a single parent into **one LLM call**. The LLM compares siblings against each other, which is more reliable than absolute scoring.

Initialize each child with **virtual visits** (AlphaZero pattern):

```python
VIRTUAL_VISITS = 3  # how strongly priors influence early selection

for child, prior_score in zip(children, priors):
    child.visit_count = VIRTUAL_VISITS
    child.value_sum = prior_score * VIRTUAL_VISITS
```

After 3–5 real MCTS evaluations, actual scores override the priors naturally because `visit_count` grows and `value_sum` accumulates real rewards.

### Tree structure that matters

```
Internal nodes (sibling groups for prior scoring):

Depth 0: 3 nodes  — children counts: [4, 8, 8]
Depth 1: 7 nodes  — children counts: [2, 6, 2, 1, 16, 43, 11]
Depth 2: 8 nodes  — children counts: [5, 2, 3, 4, 3, 2, 18, 1]
Depth 3: 6 nodes  — children counts: [2, 1, 2, 3, 1, 8]
Depth 4: 2 nodes  — children counts: [3, 4]
Depth 5: 1 node   — children counts: [3]
```

Total: 27 sibling groups. But MCTS only traverses **1 path per iteration** through ~6 depth levels, so only ~6 groups are ever visited. In practice: **3–4 prior calls** (score root children, then score children of the top 1–2 roots).

### Prior scoring prompt

```python
def build_prior_scoring_prompt(query: str, siblings: list[dict]) -> str:
    """
    siblings: [{"title": "...", "path": "Financial Statements > ...", "pages": "157-209"}]

    Returns: prompt string for batch title scoring.
    """
    items = "\n".join(
        f'{i+1}. {s["title"]} (pages {s["pages"]}, path: {s["path"]})'
        for i, s in enumerate(siblings)
    )
    return f"""Your job is to estimate which document sections are likely relevant to the given question.

Question: {query}

Sections:
{items}

Scoring rubric:
1.0 — Likely contains the direct answer
0.8 — Likely contains significant relevant information
0.5 — May contain useful context
0.2 — Unlikely to be relevant
0.0 — Definitely not relevant

Reply as JSON array:
[
  {{"title": "<exact title>", "prior_score": <float>}},
  ...
]
Directly return the JSON. Do not output anything else.""".strip()
```

### Example: prior scoring call for root children

**Input** (query: "What was Unilever's revenue in 2022?"):

```
Sections:
1. Preface (pages 1-2, path: Preface)
2. Strategic Report (pages 3-78, path: Strategic Report)
3. Governance Report (pages 80-135, path: Governance Report)
4. Financial Statements (pages 136-228, path: Financial Statements)
5. Additional Information for US Listing Purposes (pages 229-241, path: Additional Information)
```

**Expected output**:

```json
[
  {"title": "Preface", "prior_score": 0.0},
  {"title": "Strategic Report", "prior_score": 0.5},
  {"title": "Governance Report", "prior_score": 0.1},
  {"title": "Financial Statements", "prior_score": 0.9},
  {"title": "Additional Information for US Listing Purposes", "prior_score": 0.3}
]
```

---

## 3. Leaf Evaluation (Text-Based Relevance Scoring)

### Purpose

This is the actual reward signal. The LLM reads a leaf's text content and scores how well it answers the query.

### Text truncation: head + tail

Leaf text ranges from 2k to 95k chars across 144 leaves:

| Text length | Count | Strategy |
|---|---|---|
| < 3000 chars | 4 | Full text fits in prompt |
| 3000–15000 chars | 107 | Head (2000) + Tail (1000) |
| > 15000 chars | 33 | Head (2000) + Tail (1000), key data still captured |

**Why head + tail**:
- **Head** (first 2000 chars): section intro, key definitions, first data points
- **Tail** (last 1000 chars): summary conclusions, table totals, closing figures
- Financial documents like Unilever's put the reorganization announcement at the top and the breakdown tables at the bottom. Either end alone loses signal.

**Token budget**: ~3000 chars ≈ 750 tokens of content + ~200 tokens prompt + ~100 response ≈ **~1050 tokens per call**.

### Leaf evaluation prompt

```python
def build_leaf_eval_prompt(
    query: str,
    path: str,
    title: str,
    text_head: str,
    text_tail: str,
) -> str:
    """
    path: ancestor titles joined by " > ", e.g. "Financial Statements > Notes > Taxation"
    text_head: first 2000 chars of leaf.text_content
    text_tail: last 1000 chars of leaf.text_content (empty if text <= 2000)
    """
    tail_section = f"\n\nText (ending):\n{text_tail}" if text_tail else ""

    return f"""Your job is to score how relevant a document section is to the given question.

Question: {query}

Section path: {path}
Section title: {title}

Text (beginning):
{text_head}{tail_section}

Scoring rubric — be strict:
1.0 — Contains the direct, complete answer
0.8 — Contains significant information that partially answers the question
0.6 — Contains related information that provides useful context
0.4 — Topically related but does not directly help answer the question
0.2 — Only tangentially related
0.0 — Completely unrelated

Reply as JSON:
{{"thinking": "<1-2 sentences explaining your reasoning>", "score": <float>}}
Directly return the JSON. Do not output anything else.""".strip()
```

### Why include the ancestor path

A section titled "Taxation" means different things depending on where it sits:
- `Financial Statements > Notes to the consolidated financial statements > Taxation` — actual tax figures
- `Strategic Report > Review of the Year > Taxation` — strategic narrative about tax policy

The path disambiguates without extra tokens.

### Score clamping

```python
score = float(result["score"])
return max(0.0, min(1.0, score))  # guard against LLM returning 1.2 or -0.1
```

### Example: leaf evaluation call

**Input** (query: "What was Unilever's revenue in 2022?"):

```
Section path: Financial Statements > Consolidated financial statements Unilever Group
Section title: Consolidated financial statements Unilever Group

Text (beginning):
Consolidated income statement
For the year ended 31 December
...

Text (ending):
... Net finance costs | (343) | (527)
Profit before tax | 8,274 | 6,610
...
```

**Expected output**:

```json
{
  "thinking": "This section contains the consolidated income statement with revenue/turnover figures for 2022 and 2021.",
  "score": 1.0
}
```

---

## 4. Answer Synthesis

### Purpose

After MCTS finds the top-K leaves, pass their **full text** (not truncated) to an LLM to produce the final answer.

### Synthesis prompt

```python
def build_synthesis_prompt(query: str, sections: list[dict]) -> str:
    """
    sections: [{"path": "...", "title": "...", "pages": "159-162", "text": "<full text>"}]
    """
    parts = []
    for i, s in enumerate(sections, 1):
        parts.append(
            f"--- Section {i}: {s['path']} (pages {s['pages']}) ---\n{s['text']}"
        )
    combined = "\n\n".join(parts)

    return f"""Answer the question based on the document sections below.
If the sections do not contain enough information, say so.

Question: {query}

{combined}

Instructions:
- Answer directly and concisely.
- Cite page numbers in parentheses when referencing specific data, e.g. (page 159).
- If multiple sections provide conflicting information, note the discrepancy.
- Do not fabricate information not present in the sections.""".strip()
```

### Token budget

For K=3 with average leaf text ~14k chars: ~42k chars ≈ **~10k tokens** prompt + ~500 response. This is the most expensive single call, but it runs only once.

---

## 5. End-to-End Call Budget

| Phase | Calls | Tokens/call | Total tokens |
|---|---|---|---|
| Prior scoring (roots) | 1 | ~300 | ~300 |
| Prior scoring (top root children) | 1–2 | ~500 | ~1,000 |
| Leaf evaluation | 10 | ~1,050 | ~10,500 |
| Answer synthesis | 1 | ~10,500 | ~10,500 |
| **Total** | **~13–14** | | **~22,300** |

For comparison, scoring all 144 leaves without MCTS would cost 144 × ~1,050 = **~151,200 tokens**. MCTS reduces cost by **~85%** while targeting the most relevant sections.

---

## 6. Walkthrough: "What was Unilever's revenue in 2022?"

| Step | Action | LLM sees | Result |
|---|---|---|---|
| **Prior 1** | Score 5 root titles | 5 titles | Financial Statements = 0.9, Strategic Report = 0.5 |
| **Prior 2** | Score 8 FS children titles | 8 titles | Consolidated financial statements = 0.9, Notes = 0.7 |
| **MCTS 1** | UCB1 → "Consolidated financial statements" leaf | Path + head+tail text | Score: 1.0 (contains income statement) |
| **MCTS 2** | UCB1 explores "Notes" (prior 0.7) | Path + head+tail | Score: 0.6 (related context) |
| **MCTS 3–10** | UCB1 exploits + explores | Various leaves | Converges on financial leaves |
| **Synthesis** | Top-3 leaves full text | ~30k chars | "Unilever's turnover in 2022 was EUR 60.1 billion (page 153)..." |

**Total: 13 LLM calls to answer a question in a 241-page document.**
