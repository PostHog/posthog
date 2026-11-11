# Engineering analytics frontend conventions

These rules add to `frontend/src/AGENTS.md`. Use `scenes/RepoOverviewScene.tsx` as the model for a new page.

## Scope panel

- Content that a date or run-scope picker changes must sit inside `ScopePanel`. Pass the pickers through `controls`, or `null` for a fixed window.
- Current-state content, such as a backlog, must sit outside the panel and must not refetch when a picker changes.
- `ScopeBar` renders the breadcrumbs above the panel. Pass `showDate={false}` when the page has its own picker.

## Comparisons

- A comparison of this window with the previous window must render as `WindowComparisonCard`.
- A comparison of an author or a team with the repository must render as `ScopeComparisonCard`.
- Another author's row appears in a comparison only when the viewer named that author.
- No page may list authors ordered by delivery performance. The Authors tab orders authors by friction, which SPEC §2 allows.
- A table cell must hold a plain current value through `CountCell`, never a comparison.

## List and detail pages

- A list page, such as the Teams tab, has few columns, a fixed window stated in its tooltips, and no picker.
- A detail page holds the picker, the comparison cards, the charts and the drill-in tables.

## Test tables

- The test id cell must be `TestIdCell` in a `w-full max-w-0` column.
- The cell links to Trunk when the row has a Trunk URL, and otherwise to the file through `githubFileUrl` in `lib/github.ts`.
- A test table must include a `Runner` column and render times with `TZLabel`.

## Components and copy

- Use Lemon components outside charts, `@posthog/quill-charts` for charts, and `MetricTile` or `StatCard` for headline figures.
- Import from `@posthog/quill` only for UI behind the `today-rail-nav` feature flag. Read [`frontend/src/design.md`](../../../frontend/src/design.md) before you add that UI.
- Do not put a paragraph under a section title. Method caveats go in column and card tooltips.
