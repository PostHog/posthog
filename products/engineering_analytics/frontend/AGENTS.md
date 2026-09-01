# Engineering analytics frontend conventions

UI grammar for every scene in this product. `frontend/src/AGENTS.md` and the repo skills still apply; these rules are the product-specific layer on top. Model new surfaces on `RepoOverviewScene.tsx` (the repo hub), which is the reference implementation for all of them.

## The scope panel bounds what the pickers govern

- Content a window or repo picker modifies lives inside one outlined panel (`relative mt-4 rounded-lg border border-primary p-4`), with the controls docked on its rim (`absolute -top-4 right-3 ... bg-primary px-2`), plus a `Spinner` on the rim while any content inside reloads.
- Current-state content (a backlog, a "now" signal list) sits outside the panel and must not refetch when a picker changes. If a section does not move with the picker, it does not belong inside the border, and the reverse.
- Navigation (repo chip and crumbs via `ScopeBar`, `showDate={false}` when the page has its own picker) sits above the panel; it scopes identity, not time.

## One comparison vocabulary

- Window-vs-window comparison renders as `WindowComparisonCard` ("This window / Previous window" bars plus a `DeltaBadge`). Nothing else: no invented forms (a muted "was N" companion value was tried and removed), no `MetricTile` delta pills for windowed metrics.
- Table cells hold plain current values (`font-semibold tabular-nums`, right-aligned). Comparison never lives in a table cell.

## Information altitude

- List pages (the Teams roster) are scannable snapshots: few columns, plain numbers, fixed default window stated in tooltips, no picker.
- Detail pages carry the depth: the picker, the comparison cards, charts, and drill-in tables.

## Test tables

- A test id cell is a truncating `font-mono text-xs` link with a leading `IconExternal` in a `w-full max-w-0` cell: to Trunk when the payload carries a `trunk_url`, else to the file on GitHub. See `TeamQuarantinedTestsTable.tsx`.
- Include a `Runner` column; render times with `TZLabel`.

## Components and copy

- Lemon for all UI chrome; `@posthog/quill-charts` only for data viz (charts, the `MetricCard` pill). Never raw `@posthog/quill` primitives here.
- No boilerplate subheader paragraphs under section titles. Method caveats go in column and card tooltips; the scene subtitle is one plain line.
