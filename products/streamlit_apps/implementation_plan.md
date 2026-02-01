# Streamlit Apps - Implementation Plan

This checklist contains all tasks needed to implement Streamlit Apps hosting. Tasks are ordered by dependency - complete them in order. Each task should be small enough to finish in one Claude session.

---

## Phase 0: Product Boilerplate

### 0.1 Backend Setup

- [ ] Create `products/streamlit_apps/__init__.py` (empty)
- [ ] Create `products/streamlit_apps/backend/__init__.py` (empty)
- [ ] Create `products/streamlit_apps/backend/apps.py` with `StreamlitAppsConfig`
- [ ] Create `products/streamlit_apps/backend/migrations/__init__.py` (empty)
- [ ] Register app in `posthog/settings/web.py` `PRODUCTS_APPS` list

### 0.2 Frontend Setup

- [ ] Create `products/streamlit_apps/package.json` with `@posthog/products-streamlit-apps` name
- [ ] Create `products/streamlit_apps/manifest.tsx` with scenes, routes, urls
- [ ] Run `pnpm install` to register the new workspace
- [ ] Run `pnpm build:products` to generate products.tsx

### 0.3 Module Registration

- [ ] Add `products.streamlit_apps` module to `tach.toml` with dependencies on `posthog` and `products.tasks`
- [ ] Verify product loads without errors: `python manage.py check`

### 0.4 Boilerplate Verification

- [ ] Run `pnpm install` and `pnpm build:products` without errors
- [ ] Run `python manage.py check` without errors
- [ ] **Verify in Chrome MCP**: Start dev server and navigate to `/project/1/apps`
  - Route should exist (may show empty component or 404 if scene not implemented yet)
  - No JavaScript errors in console
  - Product is registered in the frontend build

---

## Phase 1: Core Infrastructure

### 1.1 Data Models

- [ ] Create `StreamlitApp` model in `products/streamlit_apps/backend/models.py`
  - Fields: `id` (UUID), `short_id`, `team`, `name`, `description`, `active_version` (FK), `cpu_cores`, `memory_gb`, `deleted`, `deleted_at`, `created_by`, `created_at`, `updated_at`
  - Add `generate_short_id()` helper
- [ ] Create `StreamlitAppVersion` model
  - Fields: `id`, `app` (FK), `version_number`, `zip_file` (S3 path), `zip_hash`, `snapshot_id` (nullable), `snapshot_created_at` (nullable), `has_requirements`, `packages` (JSON), `created_by`, `created_at`
  - Add `unique_together = ['app', 'version_number']`
- [ ] Create `StreamlitAppSandbox` model
  - Fields: `id`, `app` (OneToOne), `version` (FK), `sandbox_id`, `status`, `restart_count`, `last_error`, `started_at`, `last_activity_at`, `current_viewers`, `max_viewers`
  - Note: NO `tunnel_url` field - it's ephemeral, fetched live from Modal
  - Add `Status` choices enum (starting, running, stopping, stopped, error)
- [ ] Create `AllowedStreamlitPackage` model
  - Fields: `id`, `name`, `version_constraint`, `added_at`, `added_by`
- [ ] Write tests for model creation and relationships

### 1.2 Migrations

- [ ] Generate and apply migrations: `python manage.py makemigrations streamlit_apps`
- [ ] Verify migrations work: `python manage.py migrate`

### 1.3 Sandbox Template

- [ ] Add `STREAMLIT` to `SandboxTemplate` enum in `products/tasks/backend/services/sandbox.py`
- [ ] Add `STREAMLIT_BASE` image reference in the template config

### 1.4 Docker Image

- [ ] Create `products/tasks/backend/sandbox/images/Dockerfile.sandbox-streamlit`
  - Base: `python:3.11-slim`
  - Install: streamlit, numpy, pandas, plotly, matplotlib, seaborn, etc.
  - Install: custom `posthog` package for `posthog.query()` API
  - Copy: `streamlit_config.toml`, `entrypoint.sh`
- [ ] Create `streamlit_config.toml` (port 8501, headless, no telemetry, HTTP polling mode)
- [ ] Create `entrypoint.sh` (starts Streamlit with app.py)

---

## Phase 2: Zip Validation & Package Allowlist

### 2.1 Package Allowlist Management

- [ ] Create `products/streamlit_apps/backend/management/__init__.py`
- [ ] Create `products/streamlit_apps/backend/management/commands/__init__.py`
- [ ] Create `update_streamlit_packages.py` management command
  - Support: `--add`, `--remove`, `--list` flags
  - Validate package names
- [ ] Write tests for the management command
- [ ] Seed initial allowlist (numpy, pandas, plotly, etc.)

### 2.2 Zip Validator Service

- [ ] Create `products/streamlit_apps/backend/services/__init__.py`
- [ ] Create `products/streamlit_apps/backend/services/zip_validator.py`
  - `validate_zip(file)` - checks structure, size (10MB max)
  - `validate_requirements(requirements_txt)` - parses and checks allowlist
  - Returns validation result with errors
- [ ] Write tests for zip validation (valid zip, missing app.py, invalid packages, too large)

---

## Phase 3: App Runtime Service

### 3.1 App Runtime Core

- [ ] Create `products/streamlit_apps/backend/services/app_runtime.py`
  - Import `ModalSandbox` from `products/tasks/backend/services/modal_sandbox.py`
  - Import `SandboxConfig`, `SandboxTemplate` from `products/tasks/backend/services/sandbox.py`
- [ ] Implement `AppRuntimeService` class with:
  - `start_app(app: StreamlitApp)` - handles cold/warm start (see 3.2)
  - `stop_app(app: StreamlitApp)` - destroys sandbox, updates status
  - `get_status(app: StreamlitApp)` - returns current sandbox status
  - `get_tunnel_url(app: StreamlitApp)` - fetches tunnel URL live from Modal (NOT stored)
  - `get_connect_token(app, user)` - generates Modal Connect Token for proxy auth
- [ ] Write tests for start/stop lifecycle

### 3.2 Sandbox Startup Flow (Cold vs Warm)

- [ ] Implement **cold start** (version has no snapshot):
  1. Create sandbox with base Streamlit image + `encrypted_ports=[8501]`
  2. Download zip from S3 (`version.zip_file`)
  3. Upload files to sandbox via Modal filesystem API (`sandbox.open()`)
  4. If `requirements.txt` exists: `pip install -r requirements.txt`
  5. Create filesystem snapshot, store `snapshot_id` on version
  6. Run `streamlit run /app/app.py`
- [ ] Implement **warm start** (version has snapshot):
  1. Restore sandbox from `version.snapshot_id`
  2. Run `streamlit run /app/app.py`
- [ ] Write tests for cold start (snapshot creation) and warm start (snapshot restore)

### 3.3 App Runtime Lifecycle

- [ ] Add `restart_app(app: StreamlitApp)` method
  - Increment `restart_count`, respect max 3 restarts
  - Use warm start (restore from snapshot)
- [ ] Add `_upload_app_files(sandbox, version)` helper
  - Download zip from S3
  - Extract and upload via `sandbox.open(path, "w").write(content)`
- [ ] Add `_start_streamlit_process(sandbox)` helper
  - Run `streamlit run /app/app.py` in background
- [ ] Write tests for restart logic

---

## Phase 4: API Endpoints

### 4.1 Serializers

- [ ] Create `products/streamlit_apps/backend/api/__init__.py`
- [ ] Create `products/streamlit_apps/backend/api/streamlit_app.py`
- [ ] Implement `StreamlitAppSerializer` with nested `active_version` and `created_by`
- [ ] Implement `StreamlitAppMinimalSerializer` for list view
- [ ] Implement `StreamlitAppVersionSerializer`
- [ ] Write tests for serializers

### 4.2 App ViewSet

- [ ] Implement `StreamlitAppViewSet` in `streamlit_app.py`
  - Extend `TeamAndOrgViewSetMixin`, `viewsets.ModelViewSet`
  - `scope_object = "streamlit_app"`
  - Override `perform_create` to set `created_by` and handle zip upload
- [ ] Register ViewSet in `posthog/api/__init__.py` under projects router
- [ ] Write tests for CRUD operations

### 4.3 Version Management Endpoints

- [ ] Add `@action versions` (GET) - list all versions for an app
- [ ] Add `@action upload_version` (POST) - upload new zip, create version, activate
- [ ] Add `@action activate_version` (POST) - switch active version
- [ ] Write tests for version management

### 4.4 Sandbox Control Endpoints

- [ ] Add `@action status` (GET) - return sandbox status
- [ ] Add `@action start` (POST) - start sandbox via AppRuntime
- [ ] Add `@action stop` (POST) - stop sandbox via AppRuntime
- [ ] Add `@action restart` (POST) - restart sandbox
- [ ] Write tests for sandbox control

---

## Phase 5: HTTP Proxy (via Modal Tunnels)

### 5.1 Modal Tunnel Integration

- [ ] Ensure `AppRuntime.start_app()` uses `encrypted_ports=[8501]`
- [ ] Implement `get_tunnel_url(sandbox_record)`:
  - Reconnect to Modal sandbox via `modal.Sandbox.from_id(sandbox_record.sandbox_id)`
  - Fetch tunnel URL via `sandbox.tunnels()[8501].url`
  - Return URL (do NOT store it - it's ephemeral)
- [ ] Consider caching tunnel URL in memory (Redis) for a few minutes to reduce Modal API calls
- [ ] Write tests for tunnel URL retrieval

### 5.2 HTTP Proxy with Connect Tokens

- [ ] Create `products/streamlit_apps/backend/api/proxy.py`
- [ ] Implement `StreamlitProxyView` (extends `View`)
  - Authenticate user, verify team membership
  - Check concurrent viewer limit
  - Generate Connect Token via `sandbox.create_connect_token(user_metadata={...})`
  - Forward request to Modal tunnel URL with `Authorization: Bearer {token}`
  - Return response
- [ ] Register proxy URL: `/api/projects/{team_id}/streamlit_apps/{short_id}/proxy/`
- [ ] Write tests for proxy authentication, token generation, and forwarding

### 5.3 Concurrent Viewer Handling

- [ ] Add `current_viewers` tracking in `StreamlitAppSandbox`
- [ ] Increment viewer count on proxy request (with session tracking)
- [ ] Decrement on session timeout/disconnect
- [ ] Return "App is busy" (503) when `current_viewers >= max_viewers`
- [ ] Write tests for concurrent viewer limits

### 5.4 Activity Tracking & Logging

- [ ] Update `last_activity_at` on each proxied request
- [ ] Log outbound HTTP requests from sandbox for debugging/auditing
- [ ] Write tests for activity tracking

---

## Phase 6: HogQL Bridge Integration

### 6.1 PostHog Query Package

- [ ] Create `posthog` package for sandbox (NOT the standard posthog-python SDK)
  - `posthog.query(hogql_string)` → returns pandas DataFrame
  - Uses marker-based IPC under the hood (same as notebooks)
- [ ] Study `products/notebooks/backend/kernel_runtime.py` for bridge patterns
- [ ] Implement bridge handler in `products/streamlit_apps/backend/services/bridge.py`
  - Intercept markers from Streamlit stdout
  - Execute HogQL with team context from `StreamlitApp.team_id`
  - Return results to sandbox
- [ ] Write tests for HogQL query execution via bridge

---

## Phase 7: Frontend - List Page

### 7.1 Types and API

- [ ] Create `products/streamlit_apps/frontend/types.ts`
  - Define `StreamlitApp`, `StreamlitAppVersion`, `StreamlitAppStatus` types
- [ ] Verify API client generation works (or add manual API calls)

### 7.2 List Logic

- [ ] Create `products/streamlit_apps/frontend/streamlitAppsLogic.ts`
  - Use `kea-loaders` for `loadStreamlitApps`, `createStreamlitApp`, `deleteStreamlitApp`
  - Add `updateStreamlitApp` reducer for syncing from detail logic
- [ ] Write tests for the logic

### 7.3 List Component

- [ ] Create `products/streamlit_apps/frontend/StreamlitApps.tsx`
  - Grid of app cards showing: name, status, current viewers, created by
  - "New app" button navigates to create page
  - Click card navigates to app viewer
- [ ] Add route in `frontend/src/scenes/urls.ts`
- [ ] Register scene in `frontend/src/scenes/sceneTypes.ts`
- [ ] Add "Apps" to project navigation sidebar

### 7.4 UI Verification Checkpoint

- [ ] **Verify in Chrome MCP**: Navigate to `/project/1/apps`
  - "Apps" appears in sidebar navigation
  - Empty state shows "No apps yet" message with "New app" button
  - Page renders without console errors
  - Take screenshot for documentation

---

## Phase 8: Frontend - Create/Edit Page (Combined)

### 8.1 Edit Logic

- [ ] Create `products/streamlit_apps/frontend/streamlitAppEditLogic.ts`
  - Key by `short_id` (or `'new'` for create mode)
  - `loadStreamlitApp` loader (skip in create mode)
  - `saveApp` action (create or update)
  - `uploadZip` action with validation
  - `deleteApp` action (edit mode only)
- [ ] Write tests for the logic

### 8.2 Zip Upload Component

- [ ] Create `products/streamlit_apps/frontend/StreamlitAppZipUpload.tsx`
  - Drag-and-drop zone + click to browse
  - Show uploaded file name and size
  - Parse and display file list from zip:
    - ✓ app.py (required, show error if missing)
    - ✓ requirements.txt (optional, validate packages)
    - · other files (just list them)
  - Show package validation (allowed/not allowed)
- [ ] Write tests for zip parsing and validation display

### 8.3 Edit Page Component

- [ ] Create `products/streamlit_apps/frontend/StreamlitAppEdit.tsx`
  - Create mode: name (required), description, zip upload (required), resources
  - Edit mode: same + version dropdown, status controls, delete button
  - "Create app" / "Save changes" button
- [ ] Add routes: `/project/:id/apps/new`, `/project/:id/apps/:appId/edit`

### 8.4 UI Verification Checkpoint

- [ ] **Verify in Chrome MCP**: Test create flow
  - Navigate to `/project/1/apps/new`
  - Form renders with name, description, upload zone, resource dropdowns
  - Drag-drop zone is visible and styled correctly
  - "Create app" button is present
  - Take screenshot of empty form
- [ ] **Verify in Chrome MCP**: Test zip upload display
  - Upload a test zip file (drag or click)
  - File list displays with validation icons (✓ for valid, ✗ for invalid)
  - Package validation shows allowed/not allowed status
  - Take screenshot of uploaded state

---

## Phase 9: Frontend - App Viewer

### 9.1 Viewer Logic

- [ ] Create `products/streamlit_apps/frontend/streamlitAppLogic.ts`
  - Key by `short_id`
  - `loadStreamlitApp` loader
  - `startApp`, `stopApp`, `restartApp` actions
  - `pollStatus` for checking sandbox readiness
- [ ] Add status polling (every 2s while starting)

### 9.2 Loading State

- [ ] Create `products/streamlit_apps/frontend/StreamlitAppLoading.tsx`
  - "Waking up the hedgehogs..." message
  - Progress indicator
  - Auto-refresh when status becomes `running`

### 9.3 Viewer Component

- [ ] Create `products/streamlit_apps/frontend/StreamlitApp.tsx`
  - Header: back link, app name, edit button
  - Show loading state while sandbox starts
  - Embed iframe pointing to proxy URL when running
  - Show error state with error message (not full traceback)
  - Show "App is busy" state when concurrent limit reached
- [ ] Add route for `/project/:id/apps/:appId`

### 9.4 UI Verification Checkpoint

- [ ] **Verify in Chrome MCP**: Test viewer states
  - Create a test app via API or UI
  - Navigate to `/project/1/apps/{short_id}`
  - Loading state shows "Waking up the hedgehogs..." message
  - Back link navigates to apps list
  - Edit button navigates to edit page
  - Take screenshots of loading state
- [ ] **Verify in Chrome MCP**: Test error state (if sandbox not configured)
  - Error state shows user-friendly message
  - "Try again" and "View settings" buttons are present
  - Take screenshot of error state

---

## Phase 10: Lifecycle Management

### 11.1 Idle Timeout

- [ ] Add background task to check for idle sandboxes
  - Query sandboxes where `last_activity_at < now - 10 minutes`
  - Stop idle sandboxes via AppRuntime
- [ ] Register task with Celery/scheduler
- [ ] Write tests for idle detection

### 11.2 Auto-Restart

- [ ] Add health check in AppRuntime
  - Detect crashed Streamlit processes
  - Auto-restart up to 3 times
  - Mark as `error` after 3 failures
- [ ] Write tests for auto-restart logic

### 11.3 Version Pruning

- [ ] Add background task to prune old versions
  - Delete versions older than 30 days (except active version)
  - Delete associated zip files from S3 (`version.zip_file`)
  - Delete associated Modal snapshots (`version.snapshot_id`)
- [ ] Register task with Celery/scheduler
- [ ] Write tests for pruning logic (including snapshot cleanup)

### 11.4 Graceful Version Switching

- [ ] When `active_version` changes:
  - Stop current sandbox (if running)
  - Clear `StreamlitAppSandbox` record
  - Next viewer request will start new sandbox with new version
- [ ] Write tests for version switching

---

## Phase 11: Polish & Integration

### 12.1 Navigation

- [ ] Add "Apps" to project navigation sidebar
- [ ] Add appropriate icon

### 12.2 Empty States

- [ ] Add empty state for apps list ("No apps yet, create your first one")
- [ ] Add helpful tips in upload modal

### 12.3 Error Handling

- [ ] Add user-friendly error messages for:
  - Invalid zip structure
  - Disallowed packages
  - Sandbox start failures
  - Proxy connection errors

### 12.4 Final Testing

- [ ] End-to-end test: upload app, view running, stop, restart
- [ ] Test version rollback flow
- [ ] Test idle timeout behavior
- [ ] Test with real Modal sandbox (requires Modal API key)

### 12.5 Final UI Verification Checkpoint

- [ ] **Verify in Chrome MCP**: Full user flow
  - Navigate to Apps from sidebar
  - Click "New app" → verify create page loads
  - Fill form and upload zip → verify validation display
  - Create app → verify redirect to viewer
  - Verify loading state → iframe when ready (or error state)
  - Click Edit → verify edit page with current values
  - Change version → verify dropdown works
  - Navigate back to list → verify app appears in grid
  - Take screenshots at each step
- [ ] **Verify in Chrome MCP**: Status badges
  - Running apps show green "Running" badge with viewer count
  - Stopped apps show gray "Stopped" badge
  - Error apps show red "Error" badge
- [ ] **Verify in Chrome MCP**: Empty states
  - New project shows "No apps yet" with helpful CTA
  - Delete all apps → verify empty state returns

---

## Requirements from User

Before running this in production, you'll need:

1. **Modal API Key** - Required for sandbox provisioning
   - Set `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` environment variables
   - The existing notebook infrastructure already uses these

2. **Docker Image Registry** - The Streamlit image needs to be built and pushed
   - Image: `ghcr.io/posthog/posthog-sandbox-streamlit:master`
   - CI/CD pipeline needs to build this image

3. **File Storage (S3)** - For storing uploaded zip files
   - Uses existing PostHog file storage (S3 or local)
   - Zips stored at path in `StreamlitAppVersion.zip_file`
   - Cleaned up when versions are pruned (30 days)

4. **Modal Snapshots** - For fast sandbox restarts
   - Filesystem snapshots created after first successful start
   - Stored in Modal (referenced by `StreamlitAppVersion.snapshot_id`)
   - Cleaned up when versions are pruned (30 days)

---

## Notes

- Reference `products/notebooks/` for patterns throughout implementation
- Reference `products/tasks/backend/services/modal_sandbox.py` for sandbox usage
- Use `flox activate -- bash -c "<command>"` if commands fail in terminal

## Testing

Run tests with `pytest <path>` (e.g., `pytest products/streamlit_apps/backend/tests/`).

**CRITICAL: Tests define expected behavior.**

- If a test fails, fix your implementation, NOT the test
- Never modify tests just to make them pass
- If tests keep failing, your implementation approach is likely wrong
- Tests are the source of truth for correct behavior

## Chrome MCP Verification

Use Chrome browser automation to verify UI changes. See `prompt.md` for detailed instructions.

**Quick reference:**

1. `mcp__claude-in-chrome__tabs_context_mcp` - get/create tab group
2. `mcp__claude-in-chrome__tabs_create_mcp` - create new tab
3. `mcp__claude-in-chrome__navigate` - go to URL
4. `mcp__claude-in-chrome__computer` with `action: screenshot` - capture state
5. `mcp__claude-in-chrome__find` - locate elements by description
6. `mcp__claude-in-chrome__form_input` - fill form fields

**Dev server is already running** (managed externally).

**Verification checkpoints** are marked in this plan with "**Verify in Chrome MCP**". Complete these after implementing the associated frontend tasks.
