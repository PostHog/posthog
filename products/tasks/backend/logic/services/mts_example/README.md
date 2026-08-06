# MultiTurnSession example — cursed identifier research

Minimal working example of a **custom research agent** on top of `MultiTurnSession`. Output shape matches what Signals consumes.

## Mental model

1. `MultiTurnSession.start(prompt, context, model=Shape)` → validated turn 1.
2. `session.send_followup(prompt, Shape)` → validated turn N. Retries on schema drift.
3. `session.end()` → shut the sandbox down.

## What this agent does

Finds cursed identifiers and stale comments in `PostHog/posthog`, researches each (git blame + required PostHog MCP lookup), emits the Signals shape.

```text
discovery → research ×N (up to 10) → actionability → priority? → presentation
```

## Output shape

Returns `ReportResearchOutput` from `products.signals.backend.report_generation.research` — consumed as-is by the Signals pipeline.

## Run it

DEBUG only. Set up local sandboxes + GitHub integration + PostHog MCP OAuth first — see [docs/internal/sandboxes-setup-guide.md](../../../../../docs/internal/sandboxes-setup-guide.md).

```bash
DEBUG=1 python manage.py demo_mts_example --team-id <id> --user-id <id>
```

`--verbose` streams raw sandbox logs. Result lands in `mts_example_<timestamp>.json` at repo root.

## Adapt it

- Swap `schemas.py` for your discovery shape.
- Swap `prompts.py` for your turn prompts.
- Keep the Signals imports in `runner.py` if you want Signals to consume your output, otherwise replace them.
