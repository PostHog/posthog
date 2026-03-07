# Prompt: Expand InsightPageHeader.test.tsx coverage

## Context

`frontend/src/scenes/insights/InsightPageHeader.test.tsx` already exists with 4 parameterized button-visibility scenarios and 1 name-change wiring test. These are good but only cover about a third of the bugs that have historically hit this file. This prompt adds the missing scenarios.

Do NOT rewrite or restructure the existing tests. Add to them.

## What to add

### 1. Add these scenarios to the existing `it.each` matrix

Add these rows to the existing parameterized test array. Follow the exact same shape (`scenario`, `insightMode`, `dashboardItemId`, `canEdit`, `visible`, `notVisible`):

| Scenario | insightMode | dashboardItemId | canEdit | Expected visible | Expected NOT visible |
|---|---|---|---|---|---|
| Saved insight, Edit mode, cannot edit | Edit | abc123 | false | (none) | insight-edit-button, insight-cancel-edit-button, insight-save-button |

This catches the case where a permission change happens while someone is on the edit URL.

### 2. Add alert button visibility tests

Two of the 16 historical bugs were about alert actions appearing when they shouldn't (commits `2cb284a7` and `197930cc`). Add these tests:

```
it('does not show alert actions when query type does not support alerts')
```

Render with a saved insight in View mode whose query is a `LifecycleQuery` or `PathsQuery` (something where `areAlertsSupportedForInsight` returns false). Verify no alert-related UI is rendered. You'll need to check what `data-attr` the alert button uses — look at the component tree to find it.

```
it('shows alert actions when query type supports alerts and insight is saved')
```

Render with a saved insight in View mode with a `TrendsQuery`. Verify the alert action is present.

Note: `useMaxTool` is already mocked to a no-op, but the alert button visibility is driven by `areAlertsSupportedForInsight(query)` which is a pure function of the query — it should work without mocking if you pass the right query shape.

### 3. Add forceEdit prop test

The `forceEdit` → `SceneTitleSection` wiring was the root cause of the "save on blur" and "scene title naming" bugs (commits `e2e34c21`, `e8782c32`). Add:

```
it('passes forceEdit=true to SceneTitleSection in Edit mode')
```

Render in Edit mode. Verify the scene title textarea (`[data-attr="scene-title-textarea"]`) is immediately visible without clicking anything — this means `forceEdit` is true and the title is in edit state.

```
it('does not force edit in View mode')
```

Render in View mode. Verify the scene title textarea is NOT in the DOM — the title should be a static element, not an input. The user would need to click to edit.

### 4. Add onNameChange View mode test

The existing test only checks Edit mode → `setInsightMetadataLocal`. Add the View mode counterpart:

```
it('onNameChange calls setInsightMetadata (not local) in View mode')
```

Render a saved insight in View mode with `canEdit: true`. Click the scene name to enter edit mode (`[data-attr="scene-name"]` button), then change the textarea value. Verify the insight name is persisted (not just local). You can check this by spying on `insightLogic.actions` — `setInsightMetadata` should be called, not `setInsightMetadataLocal`.

Alternatively: since in View mode the component calls `setInsightMetadata` which triggers an API PATCH, you could add an MSW handler for `PATCH /api/environments/:team_id/insights/:id/` and verify it gets called.

## Technical notes

- Follow the exact patterns already in the file — `renderHeader()`, `useMocks`, `initKeaTests`, `cleanup`
- Don't change the existing tests, just add new ones
- The `InsightSaveButton` has `data-attr="insight-save-button"` (in `InsightSaveButton.tsx`)
- For alert button attrs, check `InsightPageHeader.tsx` and any alert-related components it renders — the alert action may come through `useMaxTool` (which is mocked) or through a button in the actions slot
- Single top-level `describe`, no docstrings on tests
- Don't modify any production code
