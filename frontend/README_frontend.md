# frontend/ — Financial Spreading SCT Web UI

**Input:** `sample_webpage.html` (self-contained HTML + Tailwind CSS CDN + vanilla JS), GET `/api/companies` (company dropdown), POST `/api/spread` SSE stream, GET `/api/history` (sidebar)
**Output:** Interactive single-page financial scorecard with company dropdown (populated from DB), real-time cell updates via SSE, audit-trail tooltips, and clickable history restoration
**Position:** Presentation layer — consumes backend SSE stream for live metric resolution. Company selection is now a dropdown fed by GET /api/companies. No mock data path in production.

If modified, update this header and `.agent/docs/FRONTEND_INTERACTION_DESIGN.md`.

---

## Files

| File | Purpose |
|---|---|
| `sample_webpage.html` | Single-file web app: 3-state SCT UI, SSE stream consumption, history sidebar |

## Architecture

```
┌─ Sidebar (toggleable) ─────────────────────────────┐
│  History list (Data Source – Timestamp)             │
└─────────────────────────────────────────────────────┘
┌─ Header ────────────────────────────────────────────┐
│  [☰] Financial Spreading SCT  [Company: ▾] [Source: ▾] │
└─────────────────────────────────────────────────────┘
┌─ Table (scrollable) ────────────────────────────────┐
│  SCT Section | Metric | FY21..FY25 | YoY | Select   │
│  Income Stmt | Revenue| (live SSE)| ... | [x]        │
│  ...          | ...    | ...        | ... | ...       │
└─────────────────────────────────────────────────────┘
┌─ Footer ────────────────────────────────────────────┐
│  [Summary: time/model/tokens]     [Run/Next button] │
└─────────────────────────────────────────────────────┘
```

## State Machine

```
SELECTION ──[Run analysis]──► ANALYSIS ──[SSE stream ends]──► RESULTS
    ▲                                                              │
    └──────────────────[Next analysis]─────────────────────────────┘
```

### SELECTION
- Table rows are clickable to toggle checkbox + highlight.
- Company name (text input) and data source (dropdown) must be set.
- "Run analysis" disabled until: (a) company name entered, (b) source selected, (c) >= 2 rows checked.

### ANALYSIS
- All inputs frozen (company, source dropdown, checkboxes disabled).
- Backend streams SSE events; each resolved metric updates its cell immediately with flash animation.
- Unresolved metrics show yellow warning marker with error detail in tooltip.
- Tree verification results appear in the status text.

### RESULTS
- Footer shows total time, model name.
- History sidebar gets a new entry: `{Source} - {YYYY-MM-DD HH:MM}`.
- Button becomes "Next analysis" -> resets to SELECTION.

## SSE Protocol (from backend)

```
event: tree_verification  {"event":"tree_verification","results":{"FY21":{...},"FY22":{...},...}}
event: metric             {"canonical_name":"Revenue","year":"FY22","row_index":0,"value":12345,"status":"resolved","formula":null,"error":null}
event: year_error         {"event":"year_error","year":"FY23","message":"Tree not available"}
event: complete           {"event":"complete"}
```

## Dependencies

| Dependency | Role |
|---|---|
| Tailwind CSS (CDN) | Utility-first styling |
| Backend API (`/api/spread`) | SSE stream of resolved metrics |
| (none else) | No JS frameworks, no build step |

If folder contents change, update this index.
