# Streamlit Apps - Ralph Loop Prompt

You are implementing the Streamlit Apps product for PostHog. This is a new product that allows users to upload and host Streamlit applications in isolated Modal sandboxes with access to their PostHog data via HogQL.

## Instructions

1. **Study the spec thoroughly** - Read `products/streamlit_apps/spec.md` to understand the full product requirements, data models, API design, and architecture. Pay special attention to the "Existing Infrastructure (Reuse)" section.

2. **Study the implementation plan** - Read `products/streamlit_apps/implementation_plan.md` to see all tasks and their completion status.

3. **Pick the highest leverage unchecked task** - Find the first unchecked `[ ]` task in `implementation_plan.md`. Earlier tasks are dependencies for later ones, so work in order.

4. **Complete the task** - Implement the task following PostHog conventions (see below). Mark the task as complete `[x]` when done.

5. **Write an unbiased test** - Add tests that verify the implementation works correctly. Tests should be thorough but not over-engineered. Use parameterized tests where appropriate.

6. **Run tests** - Run tests with `pytest <path>`. If tests fail:
   - **Fix the implementation, NOT the test**
   - Tests define the expected behavior - if they fail, your code is wrong
   - Never modify a test just to make it pass
   - If a test seems wrong, stop and reconsider your implementation

7. **Commit your work** - Create a commit with a conventional commit message (e.g., `feat(streamlit-apps): add StreamlitApp model`). No Claude attribution in commits.

When all tasks in `implementation_plan.md` are complete, output:

```xml
<promise>STREAMLIT APPS COMPLETE</promise>
```

---

## Codebase Conventions

### Backend (Python/Django)

**File Structure:**

```text
products/streamlit_apps/
├── backend/
│   ├── __init__.py
│   ├── apps.py              # Django app config
│   ├── models.py            # All Django models
│   ├── api/
│   │   ├── __init__.py
│   │   └── streamlit_app.py # ViewSets and serializers
│   ├── services/
│   │   ├── __init__.py
│   │   └── sandbox_manager.py
│   └── tests/
│       └── test_*.py
```

**Model Patterns:**

- Use `models.UUIDField(primary_key=True, default=uuid.uuid4)` for IDs
- Always include `team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)`
- Use `created_by`, `created_at`, `updated_at` fields
- Use `choices` for status enums

**ViewSet Patterns:**

```python
class StreamlitAppViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "streamlit_app"
    queryset = StreamlitApp.objects.all()
    serializer_class = StreamlitAppSerializer
```

**Testing:**

- Use pytest with `@pytest.mark.django_db`
- Use parameterized tests where appropriate
- Test happy path and edge cases

### Frontend (TypeScript/React/Kea)

**File Structure:**

```text
products/streamlit_apps/
├── frontend/
│   ├── StreamlitApps.tsx        # List page component
│   ├── StreamlitApp.tsx         # Detail/viewer component
│   ├── streamlitAppsLogic.ts    # List state management
│   ├── streamlitAppLogic.ts     # Detail state management (keyed)
│   └── types.ts
```

**Kea Logic Patterns:**

- Use `kea-loaders` for API calls
- Use `key()` for detail logics
- Sync detail updates back to list logic with `findMounted()`
- Use selectors for derived state

**Component Patterns:**

- Use functional components with hooks
- Connect to Kea with `useValues()` and `useActions()`
- Use Tailwind for styling
- Use LemonButton, LemonInput, etc. from `@posthog/lemon-ui`

**Naming:**

- Sentence case for UI text ("Save changes" not "Save Changes")
- American English spelling

### General

- **No over-engineering** - Keep it simple, add complexity only when needed
- **No extra features** - Only implement what's in the spec
- **Conventional commits** - `feat:`, `fix:`, `chore:`
- **First line under 72 chars** - For commit messages

---

## Key Files to Reference

**Existing patterns to follow:**

- `products/notebooks/backend/models.py` - Model patterns
- `products/notebooks/backend/api/notebook.py` - ViewSet patterns
- `products/notebooks/frontend/Notebooks.tsx` - List page patterns
- `products/tasks/backend/services/modal_sandbox.py` - Modal sandbox patterns
- `products/notebooks/backend/kernel_runtime.py` - Sandbox lifecycle patterns

**Registration points:**

- `posthog/api/__init__.py` - Register ViewSets
- `posthog/urls.py` - URL routing (if needed)
- `frontend/src/scenes/urls.ts` - Frontend routes
- `frontend/src/scenes/sceneTypes.ts` - Scene registration

---

## UI Verification with Chrome MCP

You have access to Chrome browser automation tools (`mcp__claude-in-chrome__*`). Use these to verify UI changes:

**When to verify:**

- After completing any frontend component task
- After adding/modifying routes
- After changing navigation
- When a task mentions "verify in UI" or has a verification checkpoint

**Verification workflow:**

1. **Get tab context**: `mcp__claude-in-chrome__tabs_context_mcp` (creates tab group if needed)
2. **Create new tab**: `mcp__claude-in-chrome__tabs_create_mcp`
3. **Navigate**: `mcp__claude-in-chrome__navigate` to `http://localhost:8000/project/1/apps`
4. **Screenshot**: `mcp__claude-in-chrome__computer` with `action: screenshot`
5. **Interact**: Click buttons, fill forms, test navigation
6. **Read page**: `mcp__claude-in-chrome__read_page` for accessibility tree if needed

**What to check:**

- Components render without errors
- Navigation works correctly
- Forms accept input and show validation
- Status badges display correctly
- Loading states appear appropriately
- Error states show user-friendly messages

**Important:**

- The dev server is already running (managed externally)
- Login as a test user first if not already authenticated
- Take screenshots to document verification
- If something looks wrong, fix it before marking the task complete

---

## Current State

Check git status and the implementation plan to understand what's been done and what's next. Each task should be small enough to complete in one session without exceeding context limits.
