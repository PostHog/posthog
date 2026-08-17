# Report canvases

Ready reports and reports awaiting input can create a shared canvas session in the public `general` space. This path is gated by the `signals-report-canvases` organization feature flag.

To preview a small backfill, pass explicit report IDs. Generation starts only when `--execute` is present:

```bash
python manage.py backfill_report_canvases <report-id> [<report-id> ...] --team-id <team-id>
python manage.py backfill_report_canvases <report-id> [<report-id> ...] --team-id <team-id> --execute
```

Only reports in `ready` or `pending_input` are eligible. The organization feature flag must be enabled outside local development. Backfills do not notify suggested reviewers unless `--notify-reviewers` is also passed.

Canvas generation requires the PostHog MCP server. Report-canvas tasks probe it from their sandbox before starting the agent and fail with a setup error when it is missing or unreachable.

The report workflow follows the canvas build rather than the longer-lived agent session. A ready build completes generation immediately; a failed build immediately records its diagnostic on the report canvas.

Each report owns one `SignalReportCanvas` link. The link points to:

- one visible discussion task, used as the stable shared session;
- one canvas, which remains stable across report updates;
- the current internal generation task.

The canvas agent receives all PostHog read scopes and `canvas:write`. It cannot mutate other PostHog objects. The first successful generation publishes the canvas immediately.

The report fingerprint includes its narrative, charts, research run, and implementation PR. A changed fingerprint starts another generation against the same canvas. PR webhooks trigger the same idempotent workflow, so a PR can enrich a canvas after its initial publication.

Human participation changes ownership. A message in the discussion or a canvas version from another task marks the link collaborative. Later pipeline generations create drafts and do not replace the human-owned live version.

Once generation produces a live version or draft, the suggested reviewers receive an Activity item targeting the canvas. Reports without resolved suggested reviewers still appear in the shared space but do not create personal Activity items.

## Test locally

Configure the dev environment with the Desktop, Tasks, and Product analytics services:

```bash
hogli dev:apply desktop tasks product_analytics
hogli up -d -y
hogli wait -y
```

Add a working LLM provider key to `.env.local`. Report canvases are enabled automatically when Django runs with `DEBUG=True`.

Create a researched report from the included synthetic fixture:

```bash
python manage.py ingest_report_json \
    products/signals/backend/report_generation/fixtures/insight_scene_logic_mode_property_bug.json \
    --team-id 1
```

Open Desktop and select `general`. The report appears immediately as a canvas session. Its canvas source appears after the generation task finishes.

The Activity item appears only when the fixture resolves to a suggested reviewer in the local organization.
