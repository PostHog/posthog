# Streamlit Apps Hosting - Product Requirements Document

## Overview

Enable PostHog users to create and host Streamlit applications within PostHog, running in isolated Modal sandboxes with secure access to their project's analytics data via HogQL.

## Goals

- Allow users to upload and deploy custom Streamlit apps
- Provide secure, isolated execution environments
- Enable apps to query PostHog data via HogQL bridge
- Simple version management with rollback capability

## Non-Goals (for initial release)

- Public/shareable links without authentication
- Embedding apps in dashboards
- Live logs/monitoring UI
- Custom domain support
- Arbitrary package installation

---

## User Experience

### App Creation

1. User navigates to **Apps** section in project navigation
2. Clicks "New app" button
3. Uploads a zip file containing:
   - `app.py` (required) - Streamlit entry point
   - `requirements.txt` (optional) - dependencies validated against allowlist
   - Static assets (images, CSS, data files) allowed
4. Enters app name (required) and description (optional)
5. App deploys immediately on save

### App Discovery

- New top-level product at `/project/{project_id}/apps`
- List view showing all apps for the project
- Each app card shows: name, description, status (running/stopped), last updated, creator

### App Viewing

- URL structure: `/project/{project_id}/apps/{app_short_id}`
- Team members only (authentication required)
- Cold start behavior:
  - First viewer triggers sandbox spin-up
  - Hedgehog-themed loading screen while starting
  - Frontend polls status endpoint
  - Auto-refreshes when app is ready
- Subsequent viewers connect instantly to running sandbox

### Version Management

- Upload new zip → immediately deploys as new active version on save
- Dropdown in app settings to select and activate previous versions
- All versions retained for 30 days, then pruned
- Rollback is instant (switches active version pointer)

---

## Technical Architecture

### Existing Infrastructure (Reuse)

This product builds on the existing Modal sandbox infrastructure used by Notebooks:

| Component         | Location                                           | Purpose                                                      |
| ----------------- | -------------------------------------------------- | ------------------------------------------------------------ |
| `ModalSandbox`    | `products/tasks/backend/services/modal_sandbox.py` | Core sandbox class with `create()`, `execute()`, `destroy()` |
| `SandboxConfig`   | `products/tasks/backend/services/sandbox.py`       | Configuration for CPU, memory, TTL, image                    |
| `SandboxTemplate` | `products/tasks/backend/services/sandbox.py`       | Enum for sandbox image types                                 |
| HogQL Bridge      | `products/notebooks/backend/notebook_bridge.py`    | Marker-based IPC for HogQL queries                           |

**What's new for Streamlit Apps:**

- `AppRuntime` service - manages Streamlit process lifecycle (similar to `kernel_runtime.py`)
- `Dockerfile.sandbox-streamlit` - new Docker image with Streamlit installed
- HTTP/WebSocket proxy - forwards viewer requests to sandbox
- App models - `StreamlitApp`, `StreamlitAppVersion`, `StreamlitAppSandbox`

### Sandbox Model

```text
┌─────────────────────────────────────────────────────┐
│                    PostHog                          │
│  ┌─────────────┐    ┌─────────────┐                │
│  │   App A     │    │   App B     │                │
│  │  Sandbox    │    │  Sandbox    │                │
│  │             │    │             │    Modal       │
│  │ [Streamlit] │    │ [Streamlit] │    Cloud       │
│  │  Port 8501  │    │  Port 8501  │                │
│  └──────┬──────┘    └──────┬──────┘                │
│         │                  │                        │
│         └────────┬─────────┘                        │
│                  │                                  │
│         ┌───────▼────────┐                         │
│         │  PostHog API   │                         │
│         │  (Proxy/Auth)  │                         │
│         └───────┬────────┘                         │
│                  │                                  │
└──────────────────┼──────────────────────────────────┘
                   │
            ┌──────▼──────┐
            │   Viewers   │
            │ (Team only) │
            └─────────────┘
```

**One sandbox per app** - all viewers share the same sandbox instance. Streamlit's native `st.session_state` provides per-user session isolation.

**Concurrent viewer limit:** Maximum 20 viewers per app (configurable). When exceeded, new viewers see "App is busy, please try again later" message. This keeps the architecture simple while protecting sandbox resources.

### Sandbox Lifecycle

| Event                         | Action                                           |
| ----------------------------- | ------------------------------------------------ |
| First viewer request          | Spin up sandbox, start Streamlit                 |
| Subsequent requests           | Route to existing sandbox                        |
| 10 minutes idle (no activity) | Shutdown sandbox                                 |
| App crash                     | Auto-restart immediately (max 3 attempts)        |
| 3 failed restarts             | Mark app as errored, show error state in UI      |
| New version activated         | Stop current sandbox, start new from new version |
| Resource config changed       | Requires sandbox restart to take effect          |

### Sandbox Startup & Snapshots

Each app version gets its own Modal filesystem snapshot. This makes subsequent starts fast (no pip install, no file upload).

**First start of a version (cold):**

```text
┌─────────────────────────────────────────────────────────────┐
│ 1. Create sandbox with base Streamlit image                  │
│ 2. Download zip from S3 (version.zip_file)                   │
│ 3. Upload files to sandbox via Modal filesystem API          │
│    - sandbox.open("/app/app.py", "w").write(...)            │
│ 4. If requirements.txt exists:                               │
│    - pip install -r requirements.txt                         │
│ 5. Create filesystem snapshot                                │
│    - Store snapshot_id on StreamlitAppVersion                │
│ 6. Run `streamlit run /app/app.py`                          │
│ 7. Sandbox ready                                            │
└─────────────────────────────────────────────────────────────┘
```

**Subsequent starts of same version (warm):**

```text
┌─────────────────────────────────────────────────────────────┐
│ 1. Restore sandbox from version.snapshot_id                  │
│    - Code + packages already present                        │
│ 2. Run `streamlit run /app/app.py`                          │
│ 3. Sandbox ready (fast!)                                    │
└─────────────────────────────────────────────────────────────┘
```

**Storage architecture:**

| What              | Where                         | Lifecycle                             |
| ----------------- | ----------------------------- | ------------------------------------- |
| Zip file          | S3 (`version.zip_file`)       | Deleted when version pruned (30 days) |
| Snapshot          | Modal (`version.snapshot_id`) | Deleted when version pruned           |
| Sandbox reference | DB (`sandbox.sandbox_id`)     | Cleared when sandbox stops            |
| Tunnel URL        | Live from Modal               | Ephemeral, fetched each request       |

**Key insight:** After the first successful start, we don't need S3 anymore for that version - the snapshot has everything (code + installed packages).

### HTTP Proxy Architecture (via Modal Tunnels)

PostHog proxies requests to Modal's built-in tunnel feature, which handles WebSocket and HTTP complexity for us:

```text
User → PostHog /proxy/* → Modal Tunnel URL → Streamlit (port 8501)
```

**Request flow:**

1. User requests `/project/123/apps/abc/proxy/...`
2. PostHog authenticates user, verifies team membership
3. PostHog checks concurrent viewer count (max 20)
4. PostHog generates a short-lived Modal Connect Token
5. PostHog proxies request to Modal tunnel URL with token
6. Modal validates token, forwards to Streamlit
7. Response flows back through PostHog to user

**Modal tunnel setup:**

```python
# When starting sandbox (or restoring from snapshot)
sandbox = modal.Sandbox.create(
    app=app,
    image=streamlit_image,
    encrypted_ports=[8501],  # Exposes Streamlit via HTTPS tunnel
    # ... other config
)

# Store sandbox_id for later reconnection
sandbox_record.sandbox_id = sandbox.object_id
sandbox_record.save()

# Get tunnel URL (fetched live, NOT stored - it's ephemeral)
tunnels = sandbox.tunnels()
tunnel_url = tunnels[8501].url  # e.g., "https://abc123xyz.r5.modal.host"
```

**Reconnecting to a running sandbox:**

```python
def get_tunnel_url(sandbox_record):
    # Reconnect to Modal sandbox by ID
    sandbox = modal.Sandbox.from_id(sandbox_record.sandbox_id)

    # Fetch current tunnel URL (may change between restarts)
    tunnels = sandbox.tunnels()
    return tunnels[8501].url
```

**Security model (defense in depth):**

| Layer         | Protection                                         |
| ------------- | -------------------------------------------------- |
| PostHog API   | User auth, team membership, viewer limits          |
| Tunnel URL    | Cryptographically random, never exposed to users   |
| Connect Token | Short-lived, included in every proxied request     |
| Sandbox       | Validates `X-Verified-User-Data` header from Modal |

**Connect Token usage:**

```python
# PostHog generates token for each proxy request
token = sandbox.create_connect_token(
    user_metadata={"user_id": user.id, "team_id": team.id}
)

# Proxy request includes token
response = requests.get(
    f"{tunnel_url}{path}",
    headers={"Authorization": f"Bearer {token}", **forwarded_headers}
)
```

This approach ensures:

- Full Streamlit functionality (WebSocket works via Modal's tunnel)
- All requests go through PostHog auth
- No Modal URLs exposed to users
- Defense in depth with Connect Tokens
- No custom WebSocket infrastructure needed

### HogQL Bridge

Apps access PostHog data via a pre-installed `posthog` package with a user-friendly API:

```python
# In user's app.py
import posthog

# Query PostHog data (returns pandas DataFrame)
df = posthog.query("SELECT event, count() FROM events GROUP BY event")
st.dataframe(df)
```

Bridge implementation:

- Pre-installed `posthog` package in the sandbox image (not the standard posthog-python SDK)
- Marker-based IPC under the hood (same mechanism as notebooks)
- Queries execute with the app's team context (enforced server-side)
- Read-only access to project data
- Team isolation: queries are always scoped to `StreamlitApp.team_id`, cannot access other teams' data

### Network Access

**Outbound HTTP**: Allowed, relying on Modal's network isolation

- Modal handles blocking of internal networks, metadata endpoints, etc.
- All outbound HTTP requests are logged for debugging/auditing
- Future: configurable allowlist per app if needed

### Package Allowlist

Stored in database with version constraints, managed via Django admin command:

```bash
python manage.py update_streamlit_packages --add "pandas>=2.0,<3.0" "numpy>=1.24"
python manage.py update_streamlit_packages --remove pandas
python manage.py update_streamlit_packages --list
```

Starting set (same as notebook sandbox):

- Data: `numpy`, `pandas`, `polars`, `scipy`, `scikit-learn`
- Visualization: `matplotlib`, `seaborn`, `plotly`
- Data formats: `pyarrow`, `duckdb`
- Web/HTTP: `requests`, `beautifulsoup4`, `lxml`
- Database: `sqlalchemy`
- Streamlit ecosystem: `streamlit`, `streamlit-aggrid`, `streamlit-extras`

Requirements validation (two-stage):

**On upload:**

1. Parse `requirements.txt` from uploaded zip
2. Check each package name and version against allowlist
3. Reject upload if any package not allowed (with clear error message)

**On app start:**

1. Re-validate packages against current allowlist
2. If a package was removed from allowlist since upload, refuse to start
3. Show error: "App uses package X which is no longer allowed"

---

## Data Models

### StreamlitApp

```python
class StreamlitApp(models.Model):
    short_id = models.CharField(max_length=12, unique=True)  # URL identifier
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Active version
    active_version = models.ForeignKey('StreamlitAppVersion', null=True, on_delete=models.SET_NULL)

    # Resource configuration (max: 8 cores, 16 GB)
    cpu_cores = models.FloatField(default=0.5)  # Allowed: 0.25, 0.5, 1, 2, 4, 8
    memory_gb = models.FloatField(default=1)    # Allowed: 0.5, 1, 2, 4, 8, 16

    # Soft delete
    deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### StreamlitAppVersion

```python
class StreamlitAppVersion(models.Model):
    app = models.ForeignKey(StreamlitApp, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField()  # Auto-incrementing per app

    # Zip storage (S3)
    zip_file = models.CharField(max_length=500)  # S3 path
    zip_hash = models.CharField(max_length=64)   # SHA256 for integrity

    # Modal snapshot (set after first successful start)
    snapshot_id = models.CharField(max_length=255, null=True, blank=True)
    snapshot_created_at = models.DateTimeField(null=True, blank=True)

    # Parsed metadata
    has_requirements = models.BooleanField(default=False)
    packages = models.JSONField(default=list)  # Parsed from requirements.txt

    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['app', 'version_number']
```

### StreamlitAppSandbox

```python
class StreamlitAppSandbox(models.Model):
    app = models.OneToOneField(StreamlitApp, on_delete=models.CASCADE)
    version = models.ForeignKey(StreamlitAppVersion, on_delete=models.CASCADE)

    # Modal sandbox reference (used to reconnect to running sandbox)
    sandbox_id = models.CharField(max_length=255)
    # Note: tunnel_url is NOT stored - it's ephemeral and fetched live from Modal

    # Status tracking
    status = models.CharField(max_length=20, choices=[
        ('starting', 'Starting'),
        ('running', 'Running'),
        ('stopping', 'Stopping'),
        ('stopped', 'Stopped'),
        ('error', 'Error'),
    ])

    # Restart tracking
    restart_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    # Activity tracking
    started_at = models.DateTimeField(null=True)
    last_activity_at = models.DateTimeField(null=True)

    # Concurrent viewer tracking
    current_viewers = models.PositiveIntegerField(default=0)
    max_viewers = models.PositiveIntegerField(default=20)
```

### AllowedStreamlitPackage

```python
class AllowedStreamlitPackage(models.Model):
    name = models.CharField(max_length=255, unique=True)  # PyPI package name
    version_constraint = models.CharField(max_length=100, blank=True)  # e.g., ">=2.0,<3.0"
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
```

---

## API Endpoints

### App Management

```text
GET    /api/projects/{project_id}/streamlit_apps/
POST   /api/projects/{project_id}/streamlit_apps/           # Create (upload zip)
GET    /api/projects/{project_id}/streamlit_apps/{short_id}/
PATCH  /api/projects/{project_id}/streamlit_apps/{short_id}/  # Update name/desc/config
DELETE /api/projects/{project_id}/streamlit_apps/{short_id}/
```

### Version Management

```text
GET    /api/projects/{project_id}/streamlit_apps/{short_id}/versions/
POST   /api/projects/{project_id}/streamlit_apps/{short_id}/versions/  # Upload new version
POST   /api/projects/{project_id}/streamlit_apps/{short_id}/versions/{version}/activate/
GET    /api/projects/{project_id}/streamlit_apps/{short_id}/versions/{version}/download/
```

### Sandbox Control

```text
GET    /api/projects/{project_id}/streamlit_apps/{short_id}/status/
POST   /api/projects/{project_id}/streamlit_apps/{short_id}/start/
POST   /api/projects/{project_id}/streamlit_apps/{short_id}/stop/
POST   /api/projects/{project_id}/streamlit_apps/{short_id}/restart/
```

**Status response (detailed):**

```json
{
  "status": "running",
  "current_viewers": 5,
  "max_viewers": 20,
  "started_at": "2024-01-15T10:30:00Z",
  "active_version": 3,
  "restart_count": 0,
  "last_error": null
}
```

**Delete behavior:**

- `DELETE /streamlit_apps/{short_id}/` performs soft-delete
- Stops the running sandbox immediately
- Sets `deleted=True` and `deleted_at` on the app
- All versions are soft-deleted (zip files retained for 30 days)
- App no longer appears in list view
- Hard cleanup runs as background task after 30 days

### App Proxy (viewer access)

```text
GET    /api/projects/{project_id}/streamlit_apps/{short_id}/proxy/*
POST   /api/projects/{project_id}/streamlit_apps/{short_id}/proxy/*   # Streamlit form submissions
```

---

## Sandbox Docker Image

New file: `products/tasks/backend/sandbox/images/Dockerfile.sandbox-streamlit`

```dockerfile
FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Install base packages (allowlist)
RUN pip install --no-cache-dir \
    streamlit==1.31.0 \
    numpy \
    pandas \
    polars \
    plotly \
    matplotlib \
    seaborn \
    scipy \
    scikit-learn \
    pyarrow \
    duckdb \
    requests \
    beautifulsoup4 \
    lxml \
    sqlalchemy

# PostHog query package (custom, not the standard posthog-python SDK)
# Provides posthog.query() API with marker-based IPC
COPY posthog/ /usr/local/lib/python3.11/site-packages/posthog/

# Streamlit config (disable telemetry, set server options)
RUN mkdir -p /root/.streamlit
COPY streamlit_config.toml /root/.streamlit/config.toml

# Entry point
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8501

ENTRYPOINT ["/entrypoint.sh"]
```

Streamlit config (`streamlit_config.toml`):

```toml
[server]
port = 8501
headless = true
enableCORS = false
enableXsrfProtection = false  # PostHog handles auth via Connect Token

[browser]
gatherUsageStats = false

[theme]
base = "light"
```

---

## File Structure

```text
products/
├── tasks/backend/services/
│   ├── modal_sandbox.py           # EXISTING - ModalSandbox class (reuse)
│   └── sandbox.py                 # EXISTING - SandboxConfig, SandboxTemplate (reuse)
│
├── tasks/backend/sandbox/images/
│   └── Dockerfile.sandbox-streamlit  # NEW - Streamlit-specific image
│
└── streamlit_apps/
    ├── __init__.py
    ├── package.json               # @posthog/products-streamlit-apps
    ├── manifest.tsx               # Product registration (routes, scenes, urls)
    ├── spec.md
    ├── prompt.md
    ├── implementation_plan.md
    ├── backend/
    │   ├── __init__.py
    │   ├── apps.py                # Django AppConfig (label="streamlit_apps")
    │   ├── models.py              # StreamlitApp, StreamlitAppVersion, StreamlitAppSandbox
    │   ├── migrations/
    │   │   └── __init__.py
    │   ├── api/
    │   │   ├── __init__.py
    │   │   ├── streamlit_app.py   # App CRUD + version endpoints
    │   │   └── proxy.py           # HTTP proxy to Modal tunnel
    │   ├── services/
    │   │   ├── __init__.py
    │   │   ├── app_runtime.py     # Streamlit lifecycle (uses ModalSandbox)
    │   │   └── zip_validator.py   # Validate uploads, check allowlist
    │   └── management/
    │       └── commands/
    │           └── update_streamlit_packages.py
    └── frontend/
        ├── StreamlitApps.tsx          # List page scene
        ├── StreamlitApp.tsx           # Viewer page scene
        ├── StreamlitAppEdit.tsx       # Create/Edit page scene
        ├── StreamlitAppZipUpload.tsx  # Drag-and-drop upload component
        ├── StreamlitAppLoading.tsx    # Loading state component
        ├── streamlitAppsLogic.ts      # List state
        ├── streamlitAppLogic.ts       # Viewer state (keyed by short_id)
        ├── streamlitAppEditLogic.ts   # Edit/create state (keyed)
        └── types.ts
```

## Product Registration

### package.json

```json
{
  "name": "@posthog/products-streamlit-apps",
  "peerDependencies": {
    "@posthog/icons": "*",
    "@posthog/lemon-ui": "*",
    "@types/react": "*",
    "react": "*",
    "kea": "*"
  }
}
```

### manifest.tsx

```typescript
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
  name: 'Streamlit Apps',
  urls: {
    streamlitApps: (): string => '/apps',
    streamlitApp: (id: string): string => `/apps/${id}`,
    streamlitAppEdit: (id: string): string => `/apps/${id}/edit`,
    streamlitAppNew: (): string => '/apps/new',
  },
  scenes: {
    StreamlitApps: {
      name: 'Streamlit Apps',
      import: () => import('./frontend/StreamlitApps'),
      projectBased: true,
    },
    StreamlitApp: {
      name: 'Streamlit App',
      import: () => import('./frontend/StreamlitApp'),
      projectBased: true,
    },
    StreamlitAppEdit: {
      name: 'Streamlit App Edit',
      import: () => import('./frontend/StreamlitAppEdit'),
      projectBased: true,
    },
  },
  routes: {
    '/apps': ['StreamlitApps', 'streamlitApps'],
    '/apps/new': ['StreamlitAppEdit', 'streamlitAppNew'],
    '/apps/:id': ['StreamlitApp', 'streamlitApp'],
    '/apps/:id/edit': ['StreamlitAppEdit', 'streamlitAppEdit'],
  },
}
```

### backend/apps.py

```python
from django.apps import AppConfig


class StreamlitAppsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.streamlit_apps.backend"
    label = "streamlit_apps"
```

### Registration Points

1. **Django settings** - Add to `PRODUCTS_APPS` in `posthog/settings/web.py`:

   ```python
   "products.streamlit_apps.backend.apps.StreamlitAppsConfig",
   ```

2. **API router** - Register ViewSet in `posthog/api/__init__.py`:

   ```python
   from products.streamlit_apps.backend.api import StreamlitAppViewSet
   projects_router.register(r"streamlit_apps", StreamlitAppViewSet, "project_streamlit_apps", ["project_id"])
   ```

3. **Module deps** - Add to `tach.toml`:

   ```toml
   [[modules]]
   path = "products.streamlit_apps"
   depends_on = ["posthog", "products.tasks"]
   ```

4. **Build products** - Run after creating manifest.tsx:

   ```bash
   pnpm build:products
   ```

---

## Security Considerations

### Authentication & Authorization

- All endpoints require authentication
- Team membership verified on every request
- Sandbox proxy validates team membership before forwarding

### Sandbox Isolation

- Each app runs in its own Modal sandbox
- No shared filesystem between apps
- Resource limits enforced (CPU, memory)
- Network egress filtered (no internal network access)

### Code Execution

- Only allowlisted packages can be installed
- No shell access for end users
- Streamlit runs as non-root user in container

### Data Access

- HogQL bridge provides read-only access
- Queries scoped to team's project
- No direct database access

---

## UI Mockups (Text Description)

### Apps List Page

```text
┌─────────────────────────────────────────────────────────┐
│  Apps                                    [+ New app]    │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌─────────────────────┐      │
│  │ Sales Dashboard     │  │ Funnel Explorer     │      │
│  │ Running · 3 viewers │  │ Stopped             │      │
│  │ Created by @jane    │  │ Created by @alex    │      │
│  └─────────────────────┘  └─────────────────────┘      │
│                                                         │
│  ┌─────────────────────┐                               │
│  │ Event Browser       │                               │
│  │ Error               │                               │
│  │ Created by @jane    │                               │
│  └─────────────────────┘                               │
└─────────────────────────────────────────────────────────┘
```

Status badges: Running (green), Stopped (gray), Starting (yellow), Error (red). No emojis, no animation.

### App Viewer Page

```text
┌─────────────────────────────────────────────────────────┐
│  [PostHog navigation bar]                               │
├─────────────────────────────────────────────────────────┤
│  [< Apps]  Sales Dashboard                    [Edit]    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                                                         │
│              [ Streamlit app iframe ]                   │
│                                                         │
│                                                         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### App Loading State

```text
┌─────────────────────────────────────────────────────────┐
│  [< Apps]  Sales Dashboard                    [Edit]    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                                                         │
│              Waking up the hedgehogs...                 │
│                                                         │
│         Your app is starting. This usually takes        │
│              about 10-30 seconds.                       │
│                                                         │
│                   [············]                        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### App Error State

```text
┌─────────────────────────────────────────────────────────┐
│  [< Apps]  Sales Dashboard                    [Edit]    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                  App failed to start                    │
│                                                         │
│  Error: ModuleNotFoundError: No module named 'foo'      │
│                                                         │
│              [Try again]  [View settings]               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### App Busy State (concurrent viewer limit)

```text
┌─────────────────────────────────────────────────────────┐
│  [< Apps]  Sales Dashboard                    [Edit]    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                    App is busy                          │
│                                                         │
│     This app has reached its viewer limit (20).         │
│         Please try again in a few minutes.              │
│                                                         │
│                      [Refresh]                          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### App Create/Edit Page

Same component for both create and edit modes.

**Create mode** (`/project/:id/apps/new`):

```text
┌─────────────────────────────────────────────────────────┐
│  Create new app                                         │
├─────────────────────────────────────────────────────────┤
│  Name: [                    ] (required)                │
│  Description: [                                      ]  │
│                                                         │
│  ─── Upload ───                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │                                                   │   │
│  │     Drag and drop your zip file here            │   │
│  │              or click to browse                  │   │
│  │                                                   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ─── Resources ───                                      │
│  CPU:    [0.5 cores ▼]                                 │
│  Memory: [1 GB ▼]                                      │
│                                                         │
│                                      [Create app]       │
└─────────────────────────────────────────────────────────┘
```

**After zip uploaded (validation feedback):**

```text
│  ─── Upload ───                                         │
│  my-app.zip (245 KB)                          [Remove]  │
│                                                         │
│  Files:                                                 │
│    ✓ app.py                                            │
│    ✓ requirements.txt                                  │
│      - pandas (allowed)                                │
│      - plotly (allowed)                                │
│    · data/sample.csv                                   │
│    · assets/logo.png                                   │
```

**Edit mode** (`/project/:id/apps/:appId/edit`):

```text
┌─────────────────────────────────────────────────────────┐
│  Sales Dashboard                              [Delete]  │
├─────────────────────────────────────────────────────────┤
│  Name: [Sales Dashboard        ]                        │
│  Description: [Interactive sales metrics explorer    ]  │
│                                                         │
│  ─── Upload new version ───                             │
│  ┌─────────────────────────────────────────────────┐   │
│  │     Drag and drop to upload a new version       │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ─── Version ───                                        │
│  Active: v3 (uploaded 2 hours ago)                      │
│  [v3 - 2 hours ago    ▼]                               │
│                                                         │
│  ─── Resources ───                                      │
│  CPU:    [0.5 cores ▼]                                 │
│  Memory: [1 GB ▼]                                      │
│                                                         │
│  ─── Status ───                                         │
│  Status: Running · 3 viewers                            │
│  [Stop]  [Restart]                                      │
│                                                         │
│                                      [Save changes]     │
└─────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Core Infrastructure

- [ ] Data models and migrations (`StreamlitApp`, `StreamlitAppVersion`, `StreamlitAppSandbox`, `AllowedStreamlitPackage`)
- [ ] Streamlit sandbox Docker image (`Dockerfile.sandbox-streamlit`)
- [ ] Add `STREAMLIT` to `SandboxTemplate` enum (in existing `sandbox.py`)
- [ ] Zip upload and validation service
- [ ] Package allowlist management command

### Phase 2: App Runtime & API

- [ ] `AppRuntime` service (uses existing `ModalSandbox` for lifecycle)
  - First start: download zip from S3, upload to sandbox, pip install, create snapshot
  - Subsequent starts: restore from snapshot
- [ ] App CRUD endpoints (ViewSet + serializers)
- [ ] Version management endpoints (upload, activate, list)
- [ ] HogQL bridge integration (adapt from notebooks)

### Phase 3: Proxy Layer (via Modal Tunnels)

- [ ] Update `AppRuntime` to use `encrypted_ports=[8501]` when creating sandbox
- [ ] Fetch tunnel URL live from running sandbox (not stored - it's ephemeral)
- [ ] HTTP proxy that forwards to Modal tunnel URL
- [ ] Connect Token generation for each proxied request
- [ ] Concurrent viewer tracking and enforcement (max 20, "App is busy" response)
- [ ] Activity tracking (update `last_activity_at` on requests)
- [ ] Outbound HTTP request logging

### Phase 4: Frontend

- [ ] Apps list page with status indicators
- [ ] App creation flow (zip upload modal)
- [ ] App viewer with hedgehog loading state
- [ ] App settings page (name, description, resources, version dropdown)

### Phase 5: Lifecycle Management

- [ ] Idle timeout detection and shutdown (10 min)
- [ ] Auto-restart on crash (max 3 attempts)
- [ ] Version pruning task (30 days)
- [ ] Graceful version switching (stop old sandbox, start new)

---

## Open Questions (Resolved)

| Question                     | Resolution                                                                             |
| ---------------------------- | -------------------------------------------------------------------------------------- |
| Per-user vs per-app sandbox? | Per-app, Streamlit sessions handle user isolation                                      |
| External HTTP access?        | Allowed with restrictions (no internal networks)                                       |
| Package management?          | Allowlist in DB, Django command to manage                                              |
| Version retention?           | 30 days, then pruned                                                                   |
| Auth model?                  | Team members only, logged in required                                                  |
| Sandbox startup?             | Per-version snapshots; first start creates snapshot, subsequent starts restore from it |
| Tunnel URL storage?          | Ephemeral, fetched live from Modal (not stored in DB)                                  |
| File upload to sandbox?      | Modal filesystem API (`sandbox.open()`) for uploading from S3                          |

---

## UI Verification Checkpoints

During development, verify the UI using Chrome MCP browser automation. These checkpoints ensure the implementation matches the spec.

### After List Page (Phase 7)

**Navigate to**: `/project/1/apps`

- [ ] "Apps" appears in project sidebar navigation
- [ ] Empty state shows when no apps exist
- [ ] "New app" button is prominent and clickable
- [ ] App cards display: name, status badge, viewer count (if running), creator

### After Create/Edit Page (Phase 8)

**Navigate to**: `/project/1/apps/new`

- [ ] Form fields: name (required), description (optional)
- [ ] Drag-and-drop upload zone is visible and styled
- [ ] Resource dropdowns show CPU and memory options
- [ ] After uploading zip:
  - File name and size displayed
  - File list shows with validation (✓ app.py, ✓/✗ packages)
  - Remove button available
- [ ] "Create app" button submits form

**Navigate to**: `/project/1/apps/{id}/edit`

- [ ] Same form as create, pre-filled with current values
- [ ] Version dropdown shows all versions
- [ ] Status section shows current state with Stop/Restart buttons
- [ ] Delete button (with confirmation) present

### After Viewer Page (Phase 9)

**Navigate to**: `/project/1/apps/{id}`

- [ ] Header: back link (< Apps), app name, Edit button
- [ ] Loading state: "Waking up the hedgehogs..." with progress
- [ ] Running state: iframe fills available space
- [ ] Error state: user-friendly message, "Try again" button
- [ ] Busy state: "App is busy" message when viewer limit reached

### Final Verification

**Complete user flow**:

1. Sidebar → Apps (see list/empty state)
2. "New app" → create form
3. Upload zip → see validation
4. Create → redirect to viewer
5. See loading → running (or error)
6. Edit → modify settings
7. Back to list → see app in grid

**Status badge colors**:

- Running: green
- Stopped: gray
- Starting: yellow
- Error: red

---

## Future Considerations (Out of Scope)

- Public/shareable links
- Custom domains
- App templates/marketplace
- Live logs viewer
- Usage analytics/billing
- Embedding in dashboards
- Git-based deployments
- Environment variables/secrets management
