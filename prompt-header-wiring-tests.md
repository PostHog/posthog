# Prompt: Add Jest wiring tests for InsightPageHeader and DashboardHeader

## Goal

Create two new test files that verify the correct buttons/actions render for each component mode. These are the two highest-fix-rate frontend files in the repo (13 and 7 fixes respectively), and every bug was about the wrong actions showing in the wrong mode. There are zero existing tests for either component.

## Files to create

1. `frontend/src/scenes/insights/InsightPageHeader.test.tsx`
2. `frontend/src/scenes/dashboard/DashboardHeader.test.tsx`

## Test approach

Use the same pattern as `frontend/src/scenes/experiments/Experiment.test.tsx`:

1. **MSW for API mocking** — use `useMocks` from `~/mocks/jest` to stub API responses. Don't mock kea directly.
2. **`initKeaTests()`** from `~/test/init` to bootstrap kea with router and common logics.
3. **`render()` from `@testing-library/react`** to mount the component.
4. **Assert on `data-attr` values** to check which buttons are in the DOM — use `screen.queryByTestId()` (remember the repo configures Playwright's `testIdAttribute` to `data-attr`, but in Jest/testing-library you should use `[data-attr="..."]` selectors or `screen.getByText()`).
5. **Mount the relevant kea logics** before rendering, and clean them up after.
6. **Mock heavy child components** you don't care about (like `InsightSidePanelContent`, `SceneTitlePanelButton`, `SharingModal`, `SubscriptionsModal`, `TextCardModal`, `DashboardTemplateEditor`, `FullScreen`, etc.) to keep the test focused and avoid pulling in the entire component tree.

## Reference file

Study `frontend/src/scenes/experiments/Experiment.test.tsx` closely — it demonstrates:
- The `useMocks` / `initKeaTests` / `render` pattern
- `jest.mock()` for heavy child components
- `router.actions.push()` to set the URL before mounting
- `waitFor` for async kea data loading
- `it.each` for parameterized test cases
- Proper cleanup with `logic.unmount()` and `cleanup()`

## InsightPageHeader test matrix

The component gets its state from `insightSceneLogic`, `insightLogic`, and `insightDataLogic`. The key variables are `insightMode` (View/Edit), `hasDashboardItemId` (saved vs new), and `canEditInsight`.

Use `it.each` to parameterize these scenarios:

| Scenario | insightMode | hasDashboardItemId | canEditInsight | Expected visible | Expected NOT visible |
|---|---|---|---|---|---|
| New unsaved insight | Edit | false | true | `InsightSaveButton` | `insight-cancel-edit-button`, `insight-edit-button` |
| Saved insight, View mode, can edit | View | true | true | `insight-edit-button` | `insight-cancel-edit-button`, `InsightSaveButton` |
| Saved insight, View mode, can't edit | View | true | false | (none of the action buttons) | `insight-edit-button`, `insight-cancel-edit-button` |
| Saved insight, Edit mode | Edit | true | true | `insight-cancel-edit-button`, `InsightSaveButton` | `insight-edit-button` |

The MSW mocks need to serve:
- `/api/environments/:team_id/insights/:id/` — return an insight object matching the scenario
- The default mocks from `handlers.ts` cover most other endpoints

To set up different states, you can either:
- Use `router.actions.push()` to navigate to the right URL and let the logics load from MSW, OR
- Mount the logic and call `actions.loadInsightSuccess(...)` directly (like the Experiment test does with `loadExperimentSuccess`)

### Additional InsightPageHeader test (non-parameterized)

- **onNameChange calls the right action per mode**: Render in Edit mode, find the scene title textarea (`[data-attr="scene-title-textarea"]`), change its value, and verify `setInsightMetadataLocal` was called (not `setInsightMetadata`). Then render in View mode, do the same, and verify `setInsightMetadata` was called (not `setInsightMetadataLocal`). You can spy on the logic actions for this.

## DashboardHeader test matrix

The component gets state from `dashboardLogic`. The key variables are `dashboardMode` (null/Edit/Fullscreen/Sharing), `canEditDashboard`, and whether the dashboard exists.

| Scenario | dashboardMode | canEditDashboard | Expected visible | Expected NOT visible |
|---|---|---|---|---|
| View mode, can edit | null | true | `dashboard-share-button`, `add-text-tile-to-dashboard`, `dashboard-add-graph-header` | `dashboard-edit-mode-discard`, `dashboard-edit-mode-save` |
| View mode, can't edit | null | false | `dashboard-share-button` | `add-text-tile-to-dashboard`, `dashboard-add-graph-header`, `dashboard-edit-mode-discard` |
| Edit mode | Edit | true | `dashboard-edit-mode-discard`, `dashboard-edit-mode-save` | `dashboard-share-button`, `add-text-tile-to-dashboard`, `dashboard-add-graph-header` |
| Fullscreen mode | Fullscreen | true | `dashboard-exit-presentation-mode` | `dashboard-share-button`, `dashboard-edit-mode-save` |

The MSW mocks need to serve:
- `/api/environments/:team_id/dashboards/:id/` — return a dashboard object
- See `dashboardLogic.test.ts` for the existing mock data shapes (`dashboardResult`, `tileFromInsight`, etc.) — reuse those helpers

### Additional DashboardHeader test

- **New dashboard gets forceEdit**: When dashboard is freshly created (matches the `isNewDashboard` logic — has `_highlight` set, or name is "New Dashboard", or was created <30s ago), verify the `SceneTitleSection` receives `forceEdit={true}` by checking that the scene title textarea is visible without clicking edit.

## Technical notes

- **Mock heavy children** — `jest.mock` the following to simple stubs to avoid pulling in their dependency trees:
  - `InsightSidePanelContent` (InsightPageHeader)
  - `SharingModal`, `SubscriptionsModal`, `TextCardModal`, `DeleteDashboardModal`, `DuplicateDashboardModal`, `DashboardInsightColorsModal`, `DashboardTemplateEditor`, `TerraformExportModal`, `FullScreen` (DashboardHeader)
  - `MaxTool` and `useMaxTool` — stub these as no-ops
- **`AccessControlAction`** wraps some buttons — mock it to just render its children so you can test the button visibility without needing the access control API
- Follow codebase conventions: single top-level `describe`, no docstrings, use `it.each` for the parameterized matrix, use American English
- Don't modify any production code — test-only changes

## Out of scope

- Don't test `SceneTitleSection` itself — it's a dumb rendering component
- Don't test tooltip positioning, keyboard shortcuts, or modal contents
- Don't test the side panel, tags, or activity indicators in `DashboardHeader`
