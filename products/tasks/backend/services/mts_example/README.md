# MultiTurnSession example — cursed identifier research

A minimal, working example of building a **custom research agent** on top of
`MultiTurnSession`. The output shape matches what Signals consumes, so you can
focus on the research logic instead of the plumbing.

## Five-line mental model

1. `MultiTurnSession.start(prompt, context, model=Shape)` spawns a sandbox agent and returns turn 1 as a validated Pydantic object.
2. `session.send_followup(prompt, Shape)` sends the next prompt and returns the next turn.
3. Each turn validates against a Pydantic schema. If the agent drifts, the helper retries with the validation error.
4. `session.end()` shuts the sandbox down cleanly.
5. Return whatever shape your consumer wants — here it's the Signals 4-tuple.

## What this agent does

Surfaces cursed code — the worst-named identifiers and the stalest comments —
in `PostHog/posthog`, then researches each one (git blame + PostHog MCP)
before emitting output in the Signals shape.

```text
discovery (1 turn)
  → research (N turns, one per discovered item; up to 20)
    → actionability (1 turn)
      → priority (1 turn, skipped when not actionable)
        → presentation (1 turn)
```

## Output shape

Imported directly from Signals — these are the exact types the Signals
pipeline consumes:

```python
(
    list[SignalFinding],
    ActionabilityAssessment,
    PriorityAssessment | None,  # None when not actionable
    ReportPresentationOutput,   # title + summary
)
```

## Run it

DEBUG only. Requires a local PostHog with a team that has a GitHub integration
(so the sandbox can clone `PostHog/posthog`):

```bash
DEBUG=1 python manage.py demo_mts_example --team-id <team_id> --user-id <user_id>
```

Add `--verbose` to stream raw sandbox log lines instead of only agent messages.
On success, the result is written to `mts_example_<timestamp>.json` at the
repo root.

## What to change for your own agent

- Replace `schemas.py` with your own discovery-turn shape.
- Replace `prompts.py` with your turn prompts.
- In `runner.py`, keep the Signals-shape imports if you want Signals to consume
  your output — or replace them with your own Pydantic models if you don't.
- The `MultiTurnSession.start` / `send_followup` / `end` pattern is the same
  for any use case.
