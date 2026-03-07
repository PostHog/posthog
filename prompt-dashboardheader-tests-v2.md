# Prompt: Improve DashboardHeader.test.tsx

## Context

`frontend/src/scenes/dashboard/DashboardHeader.test.tsx` already exists with a 4-scenario button matrix and 2 forceEdit tests. This prompt brings it up to the same standard as `InsightPageHeader.test.tsx` — which was recently improved with better types, cleanup patterns, nested describe blocks, and additional test coverage.

Do NOT rewrite or restructure the existing tests beyond what's described here. The goal is to improve quality and add missing coverage.

## 1. Align with InsightPageHeader patterns

Look at `frontend/src/scenes/insights/InsightPageHeader.test.tsx` as the reference. Apply these structural improvements to DashboardHeader.test.tsx:

**Cleanup pattern**: The current file does manual `logic.unmount()` in each test, which leaks if a test throws before reaching unmount. Replace with the `mountedLogics` array pattern from InsightPageHeader:
- Add `let mountedLogics: { unmount: () => void }[] = []` at describe scope
- Push logics in `renderHeader`, unmount them all in `afterEach`
- Remove individual `logic.unmount()` calls from test bodies

**Helper function**: Add a `queryByAttr` helper like InsightPageHeader has, then use it instead of raw `document.querySelector` calls.

**Typing**: The `makeDashboard` function uses `Record<string, any>` — tighten this to `Partial<DashboardType<QueryBasedInsightModel>>`.

**Nested describes**: Group the tests into `describe('action buttons', ...)`, `describe('forceEdit', ...)`, and `describe('name editing', ...)` blocks.

**Use `screen` from testing-library**: Import `screen` and use `screen.getByPlaceholderText('Enter name')` / `screen.queryByPlaceholderText('Enter name')` for the forceEdit tests instead of `document.querySelector('[data-attr="scene-title-textarea"]')`.

## 2. Add name editing tests

The DashboardHeader passes `onNameChange` to SceneTitleSection which calls `updateDashboard({ id, name, allowUndo: true })`. This triggers a PATCH to the dashboards API. Add:

```
describe('name editing', () => {
    it('onNameChange persists via API')
})
```

Render with a dashboard that has `canEditDashboard: true`. The `forceEdit` pair already confirms the textarea is present for new dashboards and absent for old ones. For this test, use a new dashboard (name `'New Dashboard'`) so the textarea is immediately available. Change the textarea value and blur it. Add an MSW handler for `PATCH /api/environments/:team_id/dashboards/:id/` and verify it gets called.

This covers the name-save wiring bug category (commits `e8782c32`, `e2e34c21`, `330eff70`) which made up 4 of the 7 DashboardHeader fixes.

## 3. Add Edit mode + cannot edit scenario

Add this row to the existing `it.each` matrix:

| Scenario | dashboardMode | canEdit | Expected visible | Expected NOT visible |
|---|---|---|---|---|
| Edit mode, cannot edit | DashboardMode.Edit | false | dashboard-edit-mode-discard, dashboard-edit-mode-save | dashboard-share-button, add-text-tile-to-dashboard, dashboard-add-graph-header |

Same rationale as InsightPageHeader — Cancel and Save need to be there in Edit mode regardless of permission level, because the user needs a way out.

## 4. Add `forceEdit` for Edit mode (not just new dashboard)

The existing forceEdit tests only check the `isNewDashboard` path. But `forceEdit` is also true when `dashboardMode === DashboardMode.Edit`. Add:

```
it('Edit mode gets forceEdit on SceneTitleSection', () => {
```

Render an existing dashboard (old `created_at`, has tiles, custom name) in `DashboardMode.Edit`. Verify the name textarea is immediately visible — confirming `forceEdit` is passed through for edit mode, not just new dashboards.

## Technical notes

- Follow the exact patterns from `InsightPageHeader.test.tsx` — it's the reference for how these tests should look
- Don't modify any production code
- Mock the same things already mocked (`FullScreen`, `MaxTool`)
- Import `screen`, `fireEvent`, `waitFor` from `@testing-library/react`
- Single top-level `describe`, nested sub-describes, no docstrings on tests
