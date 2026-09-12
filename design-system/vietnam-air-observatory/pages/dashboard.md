# Dashboard Page Overrides

> **PROJECT:** Vietnam Air Observatory
> **Generated:** 2026-09-12 14:40:28
> **Page Type:** Dashboard / Data View

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Reviewed product direction (takes precedence)

The generated product category/style (analytics, data-dense dashboard) fits.
The Enterprise Gateway marketing pattern did not match, including on a second
`data dashboard` query. Do not implement sales, logo carousels, hero video,
masonry portfolio cards or a login. Use the research dashboard specification
below as project-specific guidance instead. The original generated MASTER is
retained for tokens, with the following explicit accessibility adjustments.

Desktop: a 232px dark-navy sidebar, small topbar with snapshot status, generous
content canvas and white chart panels. Title typography is system sans with
Fira Sans if locally present; tabular numbers/metadata use a local monospace
stack (Fira Code if present). Do not fetch remote fonts or use CSS @import.
Use navy/blue as the main palette, teal for OceanPark, amber for limitations.
Keep charts prominent, decoration subordinate. Avoid gradient hero sections.

Use light surfaces `#F8FAFC`/white, dark headings `#172B4D`, body `#334155`, muted
text `#475569`, action blue `#1E40AF` with white text. Do not use the generated
white-on-amber button example: amber status uses `#92400E` on `#FFFBEB`.
Non-interactive cards have no pointer cursor, lift or hover animation. Native
controls have visible focus, a 40px minimum height, and wrap on small screens.
Dark theme maps semantic tokens with measured contrast and readable chart axes.
Use inline outline SVGs, no icon-font/CDN dependency and no structural emoji.

Views: Overview, Air quality, Weather context, Model diagnostics, Methods &
provenance. Preserve one nav DOM, wrapping/scrolling navigation on mobile, no
fixed overlay that hides content. Native labelled select/date inputs; text
legends plus distinct line styles. Daily qualified means must retain gaps;
hourly charts can use up to the selected time range, never silently average away
missing hours. Every chart has a labelled expandable table and CSV export.

Keep the frozen window and read-only state visible. ML uses an amber
`Limited diagnostic` notice, explicit empty states, not disabled fake controls.
Overview dates/sensor filters affect descriptive data only; frozen statistics
and model metrics use their own clear fixed-window/split filters. No metric
must appear to recalculate under an unrelated date selection.

### Layout Overrides

- **Max Width:** 1400px or full-width
- **Grid:** 12-column grid for data flexibility
- **Sections:** Snapshot header > scope filters > evidence metrics > trend/coverage > source notes

### Spacing Overrides

- **Content Density:** High — optimize for information display

### Typography Overrides

- Use offline system font fallbacks as specified above; no network font imports.

### Color Overrides

- **Strategy:** Neutral background (let work shine). Text: Black/White. Accent: Minimal.

### Component Overrides

- No overrides — use Master component specs

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Effects: Hover tooltips, chart zoom on click, row highlighting on hover, smooth filter animations, data loading spinners
- Primary actions: inspect data table, export displayed data, view methods.
