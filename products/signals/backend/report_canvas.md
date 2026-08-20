# Report canvases

Ready reports and reports awaiting input can run through the canvas generation pipeline. This path is gated by the `signals-report-canvases` organization feature flag and by the team already having a general space. PostHog Desktop provisions that space on first run, so a team that does not use Desktop generates nothing and never has a space created for it.

Generation is a shadow workflow by default. Each attempt stores its source, status, duration, model metadata, validation result, and failure details in `SignalReportCanvasGeneration`. Reviewers can inspect and label attempts in Django admin without changing what people see in Inbox.

The `signals-report-canvases-publish` organization feature flag enables publication behavior. When enabled, successful attempts link to their canvas and can notify suggested reviewers. Keep this flag disabled while evaluating generation quality.

To preview a small backfill, pass explicit report IDs. Generation starts only when `--execute` is present:

```bash
python manage.py backfill_report_canvases <report-id> [<report-id> ...] --team-id <team-id>
python manage.py backfill_report_canvases <report-id> [<report-id> ...] --team-id <team-id> --execute
```

Only reports in `ready` or `pending_input` are eligible. The organization feature flag must be enabled outside local development. Backfills do not notify suggested reviewers unless `--notify-reviewers` is also passed.

Canvas generation requires the PostHog MCP server. Report-canvas tasks probe it from their sandbox before starting the agent and fail with a setup error when it is missing or unreachable.

The report workflow follows the canvas build rather than the longer-lived agent session. A ready build completes generation immediately; a failed build immediately records its diagnostic on the report canvas.

Each report owns one internal `SignalReportCanvas` link used by the generation agent. The link points to:

- one visible discussion task, used as the stable shared session;
- one canvas, which remains stable across report updates;
- the current internal generation task.

The canvas agent receives all PostHog read scopes and `canvas:write`. It cannot mutate other PostHog objects. Successful source is copied into the generation-attempt record for review.

The report fingerprint includes its narrative, charts, research run, and implementation PR. A changed fingerprint starts another generation against the same canvas. PR webhooks trigger the same idempotent workflow, so a PR can enrich a canvas after its initial publication.

Human participation changes ownership. A message in the discussion or a canvas version from another task marks the link collaborative. Later pipeline generations create drafts and do not replace the human-owned live version.

Suggested reviewers receive an Activity item only when `signals-report-canvases-publish` is enabled.

## Test locally

Configure the dev environment with the Desktop, Tasks, and Product analytics services:

```bash
hogli dev:apply desktop tasks product_analytics
hogli up -d -y
hogli wait -y
```

Add a working LLM provider key to `.env.local`. Report canvases are enabled automatically when Django runs with `DEBUG=True`, but the team still needs a general space: open Desktop once, or call `POST /api/projects/<team-id>/task_channels/provision_defaults/`.

Create a researched report from the included synthetic fixture:

```bash
python manage.py ingest_report_json \
    products/signals/backend/report_generation/fixtures/insight_scene_logic_mode_property_bug.json \
    --team-id 1 \
    --suggested-reviewer-login <your-github-login>
```

Inspect `SignalReportCanvasGeneration` in Django admin after the generation task finishes.

The GitHub login must belong to a user in the local organization. Reviewer Activity requires the publication flag.
