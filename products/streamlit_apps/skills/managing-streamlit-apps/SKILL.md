---
name: managing-streamlit-apps
description: Create, deploy, and operate Streamlit apps in PostHog via the streamlit-apps MCP tools — create an app, set its source, start and stop its sandbox, poll status, list versions, delete, and share the app with humans via its PostHog URL. Use when asked to "create a streamlit app", "deploy a data app", "ship a dashboard app", "restart/stop my app", "why is my app not running", or "give me a link to the app".
---

# Managing Streamlit apps

A Streamlit app is a Python data app running in an isolated sandbox inside PostHog.
Each app has immutable versions of its code; one version is active; a sandbox process serves the active version.
The full lifecycle is driven with the `streamlit-apps-*` MCP tools.

## The happy path: create → set source → start → share

1. `streamlit-apps-create` with a `name` (optionally `description`, `cpu_cores` 0.25–8, `memory_gb` 0.5–16, defaults 0.5 / 1).
   The app exists but has no code yet.
2. `streamlit-apps-set-source` with the complete `app.py` source as one string.
   This creates version 1 and activates it.
   Write the source per the `writing-streamlit-apps` skill — in particular use `posthog_apps.query()` for PostHog data, never `import posthog`.
3. `streamlit-apps-start`.
   Returns immediately; the sandbox boots asynchronously.
4. Poll `streamlit-apps-status` until `status` is `running` (typically well under a minute).
   If it lands on `error`, read `last_error` — see Troubleshooting below.
5. Share the app: the `_posthogUrl` returned by create/get/start (`/streamlit-apps/{short_id}`) is the app's page in PostHog.
   That link is what you give humans.
   Viewers need to be logged into PostHog with access to the project (the app renders in an authenticated iframe; there is no public URL).

## Whose data the app reads

The app's queries run with the data access of the person who authored the **active version** — set the source, and the app reads what you can read.
Anyone who can view the app sees those results, so treat publishing an app as sharing that data with everyone on the project.
An app whose version author has since been deleted can't start; upload a new version to fix it.

## Updating code

Call `streamlit-apps-set-source` again: it creates the next version and activates it.
A running sandbox is stopped so it can't keep serving stale code — call `streamlit-apps-start` afterwards to serve the new version.
Versions are immutable, but not permanent: `streamlit-apps-versions` lists the newest 50, and non-active versions older than 30 days are deleted along with their code.
There is no rollback tool: to roll back, set the old source again (fetch it from your conversation or wherever it's kept — versions store the zip, not an inline source view).

## Stopping, idling, and deleting

- `streamlit-apps-stop` stops the sandbox; code and versions are untouched. Starting again later is cheap.
- Idle sandboxes are stopped automatically after a period of no activity — a stopped app is normal, not an error. Start it again when needed.
- `streamlit-apps-delete` stops any sandbox and soft-deletes the app. Confirm with the user before deleting anything you didn't create in this conversation.

## Troubleshooting

- **`status: error` with `last_error: "Start failed: ..."`** — the sandbox failed to provision or boot. Retry `streamlit-apps-start` once; if it persists, surface `last_error` to the user (provisioning failures are usually platform-side, not app-side).
- **Tool calls return 403 "Streamlit apps is not available."** — the `streamlit-apps` feature flag is off for this organization. This is a rollout gate, not an error you can fix; tell the user.
- **App runs but a query inside it fails** — that's an app-code concern; see `writing-streamlit-apps` (bridge limits: 30s execution, 256 MB memory per query).
- **App shows old code after set-source** — you skipped step "start after set-source"; the sandbox was stopped and needs a start.

## Renaming and resizing

`streamlit-apps-update` changes an app's name, description, `cpu_cores` (0.25–8), or `memory_gb` (0.5–16); only the fields you pass change.
New sizing applies the next time the sandbox starts, so stop + start after resizing a running app.
Defaults (0.5 CPU / 1 GB) fit typical dashboard apps.
Raise `memory_gb` only when the app itself holds large DataFrames in memory — the 256 MB HogQL bridge query cap is server-side and does NOT change with sandbox sizing, so bigger sandboxes don't fix failing queries.
