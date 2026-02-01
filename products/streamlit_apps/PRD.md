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
5. App deploys immediately on upload

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

- Upload new zip → immediately deploys as new active version
- Dropdown in app settings to select and activate previous versions
- All versions retained for 30 days, then pruned
- Rollback is instant (switches active version pointer)

---

## Technical Architecture

### Sandbox Model

```
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

### Sandbox Lifecycle

| Event | Action |
|-------|--------|
| First viewer request | Spin up sandbox, start Streamlit |
| Subsequent requests | Route to existing sandbox |
| 10 minutes idle (no viewers) | Shutdown sandbox |
| App crash | Auto-restart (max 3 attempts) |
| 3 failed restarts | Mark app as errored, notify creator |
| New version deployed | Graceful shutdown, spin up new sandbox |

### HTTP Proxy Architecture

PostHog backend maintains a tunnel/proxy to each running sandbox:

1. Viewer requests `/project/123/apps/abc`
2. PostHog authenticates user, verifies team membership
3. PostHog proxies request to sandbox's Streamlit port (8501)
4. Response returned to viewer

This approach ensures:
- All requests go through PostHog auth
- No direct Modal URLs exposed
- Full control over routing and access

### HogQL Bridge

Apps access PostHog data via the same bridge mechanism as notebooks:

```python
# In user's app.py
from posthog_bridge import hogql_execute

df = hogql_execute("SELECT event, count() FROM events GROUP BY event")
st.dataframe(df)
```

Bridge implementation:
- Marker-based IPC (same as notebooks)
- Queries execute with project context
- Read-only access to project data

### Network Access

**Outbound HTTP**: Allowed with domain restrictions
- Block: internal networks, localhost, cloud metadata endpoints (169.254.x.x, etc.)
- Allow: public internet by default
- Future: configurable allowlist per app if needed

### Package Allowlist

Stored in database, managed via Django admin command:

```bash
python manage.py update_streamlit_packages --add pandas numpy plotly
python manage.py update_streamlit_packages --remove some_package
python manage.py update_streamlit_packages --list
```

Starting set (same as notebook sandbox):
- Data: `numpy`, `pandas`, `polars`, `scipy`, `scikit-learn`
- Visualization: `matplotlib`, `seaborn`, `plotly`
- Data formats: `pyarrow`, `duckdb`
- Web/HTTP: `requests`, `beautifulsoup4`, `lxml`
- Database: `sqlalchemy`
- Streamlit ecosystem: `streamlit`, `streamlit-aggrid`, `streamlit-extras`

Requirements validation:
1. Parse `requirements.txt` from uploaded zip
2. Check each package against allowlist
3. Reject upload if any package not allowed (with clear error message)

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

    # Resource configuration
    cpu_cores = models.FloatField(default=0.5)
    memory_gb = models.FloatField(default=1)

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

    # Zip storage
    zip_file = models.FileField(upload_to='streamlit_apps/')  # Or S3 path
    zip_hash = models.CharField(max_length=64)  # SHA256 for integrity

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

    # Modal sandbox reference
    sandbox_id = models.CharField(max_length=255)

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
```

### AllowedStreamlitPackage

```python
class AllowedStreamlitPackage(models.Model):
    name = models.CharField(max_length=255, unique=True)  # PyPI package name
    max_version = models.CharField(max_length=50, blank=True)  # Optional version constraint
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
```

---

## API Endpoints

### App Management

```
GET    /api/projects/{project_id}/streamlit_apps/
POST   /api/projects/{project_id}/streamlit_apps/           # Create (upload zip)
GET    /api/projects/{project_id}/streamlit_apps/{short_id}/
PATCH  /api/projects/{project_id}/streamlit_apps/{short_id}/  # Update name/desc/config
DELETE /api/projects/{project_id}/streamlit_apps/{short_id}/
```

### Version Management

```
GET    /api/projects/{project_id}/streamlit_apps/{short_id}/versions/
POST   /api/projects/{project_id}/streamlit_apps/{short_id}/versions/  # Upload new version
POST   /api/projects/{project_id}/streamlit_apps/{short_id}/versions/{version}/activate/
GET    /api/projects/{project_id}/streamlit_apps/{short_id}/versions/{version}/download/
```

### Sandbox Control

```
GET    /api/projects/{project_id}/streamlit_apps/{short_id}/status/
POST   /api/projects/{project_id}/streamlit_apps/{short_id}/start/
POST   /api/projects/{project_id}/streamlit_apps/{short_id}/stop/
POST   /api/projects/{project_id}/streamlit_apps/{short_id}/restart/
```

### App Proxy (viewer access)

```
GET    /api/projects/{project_id}/streamlit_apps/{short_id}/proxy/*
WS     /api/projects/{project_id}/streamlit_apps/{short_id}/proxy/ws  # WebSocket for Streamlit
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

# PostHog bridge library
COPY posthog_bridge.py /usr/local/lib/python3.11/site-packages/

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
enableXsrfProtection = false  # PostHog handles auth

[browser]
gatherUsageStats = false

[theme]
base = "light"
```

---

## File Structure

```
products/
└── streamlit_apps/
    ├── __init__.py
    ├── PRD.md
    ├── backend/
    │   ├── __init__.py
    │   ├── models.py              # Data models
    │   ├── api/
    │   │   ├── __init__.py
    │   │   ├── streamlit_app.py   # App CRUD endpoints
    │   │   ├── version.py         # Version management
    │   │   └── proxy.py           # HTTP proxy to sandbox
    │   ├── services/
    │   │   ├── __init__.py
    │   │   ├── sandbox_manager.py # Sandbox lifecycle
    │   │   ├── zip_validator.py   # Validate uploads
    │   │   └── bridge.py          # HogQL bridge for Streamlit
    │   └── management/
    │       └── commands/
    │           └── update_streamlit_packages.py
    └── frontend/
        └── ... (React components, Kea logic)
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

```
┌─────────────────────────────────────────────────────────┐
│  Apps                                    [+ New app]    │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌─────────────────────┐      │
│  │ 📊 Sales Dashboard  │  │ 📈 Funnel Explorer  │      │
│  │ Running             │  │ Stopped             │      │
│  │ Updated 2 hours ago │  │ Updated 3 days ago  │      │
│  └─────────────────────┘  └─────────────────────┘      │
│                                                         │
│  ┌─────────────────────┐                               │
│  │ 🔍 Event Browser    │                               │
│  │ Error               │                               │
│  │ Updated 1 day ago   │                               │
│  └─────────────────────┘                               │
└─────────────────────────────────────────────────────────┘
```

### App Loading State

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│                    🦔 🦔 🦔                             │
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

### App Settings

```
┌─────────────────────────────────────────────────────────┐
│  Sales Dashboard                              [Delete]  │
├─────────────────────────────────────────────────────────┤
│  Name: [Sales Dashboard        ]                        │
│  Description: [Interactive sales metrics explorer    ]  │
│                                                         │
│  ─── Resources ───                                      │
│  CPU:    [0.5 cores ▼]                                 │
│  Memory: [1 GB ▼]                                      │
│                                                         │
│  ─── Version ───                                        │
│  Active: v3 (uploaded 2 hours ago)                      │
│  [v3 - 2 hours ago    ▼]  [Upload new version]         │
│                                                         │
│  ─── Status ───                                         │
│  Status: Running                                        │
│  [Stop]  [Restart]                                      │
│                                                         │
│                                      [Save changes]     │
└─────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Data models and migrations
- [ ] Streamlit sandbox Docker image
- [ ] Basic sandbox manager (start/stop)
- [ ] Zip upload and validation
- [ ] Package allowlist management command

### Phase 2: API & Proxy
- [ ] App CRUD endpoints
- [ ] Version management endpoints
- [ ] HTTP proxy to sandbox
- [ ] WebSocket proxy for Streamlit interactivity
- [ ] HogQL bridge integration

### Phase 3: Frontend
- [ ] Apps list page
- [ ] App creation flow (zip upload)
- [ ] App viewer with loading state
- [ ] App settings page
- [ ] Version management UI

### Phase 4: Lifecycle Management
- [ ] Idle timeout detection and shutdown
- [ ] Auto-restart on crash (max 3)
- [ ] Version pruning (30 days)
- [ ] Graceful version switching

---

## Open Questions (Resolved)

| Question | Resolution |
|----------|------------|
| Per-user vs per-app sandbox? | Per-app, Streamlit sessions handle user isolation |
| External HTTP access? | Allowed with restrictions (no internal networks) |
| Package management? | Allowlist in DB, Django command to manage |
| Version retention? | 30 days, then pruned |
| Auth model? | Team members only, logged in required |

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
