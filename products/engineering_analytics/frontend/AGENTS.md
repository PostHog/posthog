# Engineering analytics frontend conventions

UI grammar for every scene in this product. `frontend/src/AGENTS.md` and the repo skills still apply; these rules are the product-specific layer on top. Model new surfaces on `RepoOverviewScene.tsx` (the repo hub), which is the reference implementation for all of them.

## The scope panel bounds what the pickers govern

- Content a window or repo picker modifies lives inside `ScopePanel` (`components/ScopePanel.tsx`): controls dock on its rim via the `controls` prop, and `busy` shows the rim spinner while anything inside reloads.
- Current-state content (a backlog, a "now" signal list) sits outside the panel and must not refetch when a picker changes. If a section does not move with the picker, it does not belong inside the border, and the reverse.
- Navigation (repo chip and crumbs via `ScopeBar`, `showDate={false}` when the page has its own picker) sits above the panel; it scopes identity, not time.

## One comparison vocabulary per question

- Window-vs-window comparison renders as `WindowComparisonCard` ("This window / Previous window" bars plus a `DeltaBadge`). Nothing else: no invented forms (a muted "was N" companion value was tried and removed), no `MetricTile` delta pills for windowed metrics.
- Scope-vs-repository comparison (an author or a team against the repository) renders as `ScopeComparisonCard` ("This author / Repo" bars on one scale). The question there is "is this friction unusual here", which a previous window can't answer. It never compares authors or teams with each other. The one extra baseline is the author's own team: the ready-to-merge card draws it as muted rows between the author and the repository, one row per team the comparison picked.
- Table cells hold plain current values via `CountCell` (`components/CountCell.tsx`). Comparison never lives in a table cell.

## Information altitude

- List pages (the Teams roster) are scannable snapshots: few columns, plain numbers, fixed default window stated in tooltips, no picker.
- Detail pages carry the depth: the picker, the comparison cards, charts, and drill-in tables.

## Test tables

- The test id cell is `TestIdCell` (`components/TestIdCell.tsx`) in a `w-full max-w-0` column: link to Trunk when the payload carries a `trunk_url`, else to the file on GitHub via `githubFileUrl` in `lib/github.ts`.
- Include a `Runner` column; render times with `TZLabel`.

## Components and copy

- Lemon for all UI chrome; `@posthog/quill-charts` only for data viz (charts, the `MetricCard` pill). Never raw `@posthog/quill` primitives here.
- No boilerplate subheader paragraphs under section titles. Method caveats go in column and card tooltips; the scene subtitle is one plain line.
