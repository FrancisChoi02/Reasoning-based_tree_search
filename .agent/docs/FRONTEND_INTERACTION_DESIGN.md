# Frontend Interaction Design — Financial Spreading SCT

**Scope:** Full interaction logic for the single-page SCT web UI (`frontend/sample_webpage.html`).  
**Related:** `frontend/README_frontend.md` (file-level documentation)

---

## 1. State Machine & Transitions

```
                 ┌──────────────────────────┐
                 │       SELECTION          │
                 │  - table rows clickable  │
                 │  - source dropdown active│
                 │  - "Run analysis" dimmed │
                 └─────────┬────────────────┘
                           │ [Run analysis] clicked
                           │ (guard: source selected AND >= 2 rows checked)
                           ▼
                 ┌──────────────────────────┐
                 │       ANALYSIS           │
                 │  - all inputs frozen     │
                 │  - cells populate async  │
                 │  - button: "Analyzing..."│
                 └─────────┬────────────────┘
                           │ all queued cells processed
                           ▼
                 ┌──────────────────────────┐
                 │        RESULTS           │
                 │  - cells show values/⚠   │
                 │  - tooltips active       │
                 │  - footer summary visible│
                 │  - history entry added   │
                 │  - button: "Next analysis"│
                 └─────────┬────────────────┘
                           │ [Next analysis] clicked
                           ▼
                      (back to SELECTION, full reset)
```

### Transition guards

| From | To | Condition |
|---|---|---|
| SELECTION | ANALYSIS | `sourceSelect.value !== ""` AND `selectedRows.size > 1` |
| ANALYSIS | RESULTS | `currentIndex >= queue.length` (all cells done) |
| RESULTS | SELECTION | Always allowed (button click) |

### State-conditional UI

| Element | SELECTION | ANALYSIS | RESULTS |
|---|---|---|---|
| Row click (toggle) | enabled | disabled (early return) | disabled |
| Checkboxes | enabled | disabled | disabled |
| Source dropdown | enabled | disabled | disabled |
| Action button text | "Run analysis" | "Analyzing..." | "Next analysis" |
| Action button color | purple-600 | gray-400 | blue-600 |
| Footer | placeholder text | "Analysis in progress..." | Summary stats |
| History clicks | functional | functional | functional |

---

## 2. Component Breakdown

### 2.1 Sidebar (History Panel)

```
┌─────────────────────┐
│ [⏱] History         │  ← header (gray bg, border-bottom)
├─────────────────────┤
│ Moody's - 2026-05.. │  ← history items (prepended, newest first)
│ S&P Global - 20..   │
│ Internal Model - .. │
│ No past analyses    │  ← empty state (italic, gray)
└─────────────────────┘
```

- **Toggle:** Hamburger button in header calls `toggleSidebar()`. Adds/removes `sidebar-closed` class (width→0, opacity→0, 0.3s ease transition).
- **Items:** Name format `{Source} - {YYYY-MM-DD HH:MM}`. Title tooltip shows indicator count.
- **Empty state:** `<li id="empty-history">No past analyses</li>` — removed on first result.
- **Current limitation:** Not clickable to restore past state (future enhancement).

### 2.2 Header

```
[☰] Financial Spreading SCT           Data Source: [Please select data source ▾]
```

- Left: hamburger + title (truncated on small screens).
- Right: bold label "Data Source:" + `<select>` with 4 hardcoded options.
- Dropdown hidden on mobile below `sm` breakpoint via `hidden sm:block`.

### 2.3 Table

```
┌──────────────────┬─────────────────────┬──────┬──────┬──────┬──────┬──────┬────────┐
│ SCT Section      │ Metric              │ FY21 │ FY22 │ FY23 │ FY24 │ FY25 │ Select │
├──────────────────┼─────────────────────┼──────┼──────┼──────┼──────┼──────┼────────┤
│ Income Statement │ Revenue             │ 1,234│ 2,345│ ...  │ ...  │ ...  │  [x]   │
│                  │ Gross Profit        │      │      │      │      │      │  [ ]   │
│                  │ Gross Profit Margin │      │      │      │      │      │  [ ]   │
│ ...              │ ...                 │ ...  │ ...  │ ...  │ ...  │ ...  │  ...   │
│ Balance Sheet    │ Net Worth           │      │      │      │      │      │  [ ]   │
│ ...              │ ...                 │ ...  │ ...  │ ...  │ ...  │ ...  │  ...   │
└──────────────────┴─────────────────────┴──────┴──────┴──────┴──────┴──────┴────────┘
```

- **Sticky header:** `thead` has `sticky top-0 z-20` with purple-100 bg.
- **Section grouping:** First row of each section shows the section name (e.g., "Income Statement"). Subsequent rows in same section leave the cell empty (span merge is visual-only — each row has its own `<td>`).
- **26 indicators** across 5 years = 130 potential data cells.
- **Row selection:** Clicking any `<tr>` calls `toggleRowSelection(index)`. Selected rows get `row-selected` class (slate-100 bg). Checkbox checked state mirrors `selectedRows` Set.
- **Scrollable:** `.table-scroll` with custom thin scrollbar styling. Min-width 800px prevents squishing.

### 2.4 Footer

```
┌──────────────────────────────────────────────────────────────┐
│ Total Time: 3.2s  Model: Gemini 3.1 Pro (Web)  Tokens: 1,250 │  ← results-summary
│ Select indicators and data source to begin analysis.         │  ← summary-placeholder
│                                          [  Run analysis  ]  │
└──────────────────────────────────────────────────────────────┘
```

- Two mutually exclusive blocks: `results-summary` (blue-50 bg, hidden by default) and `summary-placeholder` (gray text).
- Summary shows after analysis completes.
- Placeholder text changes to provide guidance (e.g., "Select at least 2 indicators").

---

## 3. Event Handling Flow

### 3.1 Row Selection (`toggleRowSelection`)

```
User clicks row (or checkbox onChange)
  │
  ├─ currentState !== 'SELECTION'? → return (no-op)
  │
  ├─ selectedRows.has(index)?
  │    YES → delete from Set, uncheck, remove row-selected
  │    NO  → add to Set, check, add row-selected
  │
  └─ updateButtonState()
```

**Checkbox quirk:** Checkbox `<input>` has `pointer-events-none` so clicks pass through to the row. The `onchange` handler on the checkbox still fires (programmatic toggle). The `fromCheckbox` param prevents double-toggle when the row click also fires.

### 3.2 Source Dropdown (`onchange`)

```
sourceSelect change event
  └─ updateButtonState()
```

### 3.3 Button State (`updateButtonState`)

```
updateButtonState()
  │
  ├─ currentState !== 'SELECTION'? → return
  │
  ├─ hasSource = sourceSelect.value !== ""
  ├─ hasValidCount = selectedRows.size > 1
  │
  ├─ hasSource AND hasValidCount?
  │    YES → btnAction.disabled = false, placeholder = "Ready to run analysis."
  │    NO  → btnAction.disabled = true
  │          ├─ !hasSource → "Please select a data source to begin."
  │          └─ else → "Select at least 2 indicators (N selected)."
```

### 3.4 Action Button (`handleActionClick`)

```
handleActionClick()
  │
  ├─ currentState === 'SELECTION' → startAnalysis()
  └─ currentState === 'RESULTS'   → resetToSelection()
```

### 3.5 Analysis Flow (`startAnalysis` → `simulateApiCalls` → `finishAnalysis`)

```
startAnalysis()
  │
  ├─ currentState = 'ANALYSIS'
  ├─ startTime = Date.now()
  ├─ Freeze UI: disable button, disable dropdown, gray out button
  │
  ├─ Build queue: for each selectedRow × each year → { r: rowIndex, c: yearLabel }
  ├─ Shuffle queue (simulates random network arrival order)
  │
  └─ simulateApiCalls(queue, 0)

simulateApiCalls(queue, currentIndex)
  │
  ├─ currentIndex >= queue.length? → finishAnalysis(), return
  │
  ├─ Get cell div: document.getElementById(`cell-${r}-${c}`)
  ├─ setTimeout(random 50-300ms):
  │    ├─ Remove flash-cell class, trigger reflow
  │    ├─ Random (Math.random() > 0.15):
  │    │    SUCCESS (85%):
  │    │      - Generate random value (1000-11000)
  │    │      - Set innerHTML: tooltip-container with value + audit trail tooltip
  │    │    FAIL (15%):
  │    │      - Set innerHTML: yellow ⚠ SVG icon + "Data gap" tooltip
  │    │      - Add bg-yellow-50 to parent <td>
  │    ├─ Add flash-cell class (triggers CSS animation)
  │    └─ Recurse: simulateApiCalls(queue, currentIndex + 1)
```

### 3.6 Results Completion (`finishAnalysis`)

```
finishAnalysis()
  │
  ├─ currentState = 'RESULTS'
  ├─ Compute duration = (Date.now() - startTime) / 1000
  ├─ Mock tokens = selectedRows.size * 5 * random(30..50)
  │
  ├─ Populate summary: time, model ("Gemini 3.1 Pro (Web)"), tokens
  ├─ Show results-summary, hide summary-placeholder
  │
  ├─ Transform button: "Next analysis", blue-600, enabled
  │
  └─ Add history entry:
       ├─ Remove #empty-history if present
       └─ Prepend <li> with "{Source} - {YYYY-MM-DD HH:MM}"
```

### 3.7 Reset (`resetToSelection`)

```
resetToSelection()
  │
  ├─ currentState = 'SELECTION'
  │
  ├─ For each selectedRow × each year:
  │    ├─ Clear cell innerHTML
  │    ├─ Remove flash-cell class
  │    └─ Remove bg-yellow-50 from parent <td>
  │
  ├─ Uncheck all checkboxes, remove row-selected class
  ├─ Clear selectedRows Set
  │
  ├─ Reset dropdown to default (value=""), re-enable
  ├─ Hide summary, show placeholder
  ├─ Reset button to "Run analysis", purple-600
  │
  └─ updateButtonState()
```

---

## 4. Data Model

### 4.1 Indicators (26 items)

```js
indicators = [
  { sec: 'Income Statement', met: 'Revenue' },
  { sec: 'Income Statement', met: 'Gross Profit' },
  // ... 7 more Income Statement
  { sec: 'Balance Sheet', met: 'Net Worth' },
  // ... 7 more Balance Sheet
  { sec: 'Cash Flow', met: 'Operating cashflow' },
  // ... 4 more Cash Flow
  { sec: 'Ratios', met: 'Ext. Gearing (TFD/TNW) (x)' },
  // ... 2 more Ratios
  { sec: 'Others', met: 'Capital Expenditure' },
]
```

| Section | Count |
|---|---|
| Income Statement | 9 |
| Balance Sheet | 8 |
| Cash Flow | 5 |
| Ratios | 3 |
| Others | 1 |
| **Total** | **26** |

### 4.2 Cell ID Convention

Each cell div carries an ID: `cell-{rowIndex}-{yearLabel}`  
Example: `cell-0-FY21`, `cell-3-FY24`

### 4.3 Selected Rows

`selectedRows` is a `Set<number>` containing 0-based row indices.

---

## 5. CSS Architecture

| Class / Rule | Purpose |
|---|---|
| `.flash-cell` animation | 1.5s yellow-200 → transparent highlight on data arrival |
| `.tooltip-container` / `.tooltip` | Hover-reveal audit trail (visibility + opacity transition) |
| `.table-scroll::-webkit-scrollbar-*` | Thin 8px custom scrollbar (slate palette) |
| `#sidebar` / `.sidebar-closed` | Width + padding + opacity transition (0.3s ease) |
| `.row-selected` | Slate-100 background for selected rows |

---

## 6. Integration Plan (Backend Wiring)

When replacing the mock with a real backend:

1. **`startAnalysis()`**: Replace queue build with a `POST /api/analyze` call sending `{ source, indicators: [...selectedRows] }`.
2. **`simulateApiCalls()`**: Replace with **Server-Sent Events (SSE)** or **WebSocket** stream. Each cell result arrives as `{ rowIndex, year, value, formula, source, error? }`.
3. **`finishAnalysis()`**: Update model name and token count from the API response metadata.
4. **`indicators[]`**: Fetch from `GET /api/indicators` instead of hardcoding.
5. **History**: Persist via `localStorage` (MVP) or `GET/POST /api/history` (full stack).
