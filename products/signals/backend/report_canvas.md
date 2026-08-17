# Report canvases

Ready reports and reports awaiting input can create a shared canvas session in the public `general` space. This path is gated by the `signals-report-canvases` organization feature flag.

Each report owns one `SignalReportCanvas` link. The link points to:

- one visible discussion task, used as the stable shared session;
- one canvas, which remains stable across report updates;
- the current internal generation task.

The canvas agent receives all PostHog read scopes and `canvas:write`. It cannot mutate other PostHog objects. The first successful generation publishes the canvas immediately.

The report fingerprint includes its narrative, charts, research run, and implementation PR. A changed fingerprint starts another generation against the same canvas. PR webhooks trigger the same idempotent workflow, so a PR can enrich a canvas after its initial publication.

Human participation changes ownership. A message in the discussion or a canvas version from another task marks the link collaborative. Later pipeline generations create drafts and do not replace the human-owned live version.

Once generation produces a live version or draft, the suggested reviewers receive an Activity item targeting the canvas. Reports without resolved suggested reviewers still appear in the shared space but do not create personal Activity items.
