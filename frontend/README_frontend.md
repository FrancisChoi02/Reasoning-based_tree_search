# frontend/ — Financial Spreading SCT Web UI

**Input:** `sample_webpage.html` (self-contained HTML + Tailwind CSS CDN + vanilla JS)  
**Output:** Interactive single-page financial scorecard with selection/analysis/results states  
**Position:** Presentation layer — decoupled from the Python extraction pipeline. Delivers the SCT (Score Table) UI for indicator selection, mock analysis playback, and audit-trail inspection.

If modified, update this header and `.agent/docs/FRONTEND_INTERACTION_DESIGN.md`.

---

## Files

| File | Purpose |
|---|---|
| `sample_webpage.html` | Single-file web app: 3-state SCT UI, mock async cell population, history sidebar |

## Architecture

```
┌─ Sidebar (toggleable) ─────────────────────────────┐
│  History list (Data Source – Timestamp)             │
└─────────────────────────────────────────────────────┘
┌─ Header ────────────────────────────────────────────┐
│  [☰] Financial Spreading SCT    [Data Source: ▾]    │
└─────────────────────────────────────────────────────┘
┌─ Table (scrollable) ────────────────────────────────┐
│  SCT Section | Metric | FY21..FY25 | Select         │
│  Income Stmt | Revenue| (values)   | [x]            │
│  ...          | ...    | ...        | ...            │
└─────────────────────────────────────────────────────┘
┌─ Footer ────────────────────────────────────────────┐
│  [Summary: time/model/tokens]     [Run/Next button] │
└─────────────────────────────────────────────────────┘
```

## State Machine

```
SELECTION ──[Run analysis]──► ANALYSIS ──[all cells done]──► RESULTS
    ▲                                                          │
    └──────────────────[Next analysis]─────────────────────────┘
```

### SELECTION
- Table rows are clickable to toggle checkbox + highlight.
- Data source dropdown must be selected.
- "Run analysis" disabled until: (a) source selected, (b) >= 2 rows checked.

### ANALYSIS
- All inputs frozen (dropdown, checkboxes, button disabled).
- Cells populate one-by-one with random delay (50-300 ms), simulating async API responses.
- Each cell briefly flashes yellow-green on arrival.
- 85% success (value + tooltip) / 15% failure (yellow ⚠ marker).

### RESULTS
- Footer shows total time, model name, token count.
- History sidebar gets a new entry: `{Source} - {YYYY-MM-DD HH:MM}`.
- Button becomes "Next analysis" → resets to SELECTION.

## Key Implementation Details

- **Indicators (26):** Hardcoded in `indicators[]` array covering Income Statement, Balance Sheet, Cash Flow, Ratios, Others.
- **Years (5):** FY21, FY22, FY23, FY24, FY25.
- **Data sources (4):** Moody's, S&P Global, Fitch, Internal Model.
- **Mock API:** `simulateApiCalls()` uses recursive `setTimeout` to serialize cell updates. Queue is shuffled for visual randomness.
- **Flash animation:** CSS `@keyframes flashHighlight` — yellow-200 bg → transparent over 1.5s.
- **Tooltip:** CSS-only `.tooltip-container` hover reveals audit trail (formula, source, component breakdown).
- **Sidebar toggle:** `toggleSidebar()` adds/removes `sidebar-closed` class (width 0, opacity 0, 0.3s transition).
- **Row selection:** `row-selected` class (slate-100 bg). Checkboxes have `pointer-events-none` to avoid double-toggle.

## Dependencies

| Dependency | Role |
|---|---|
| Tailwind CSS (CDN) | Utility-first styling |
| (none else) | No JS frameworks, no build step |

## Future Integration Points

- Replace `simulateApiCalls()` with real `fetch()` / SSE to a Python backend endpoint.
- Replace `indicators[]` with an API-fetched schema.
- Persist history in `localStorage` or backend session.
