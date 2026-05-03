# Dedupe & skip rules

The cost of re-emitting a known issue is higher than the cost of staying silent. These
rules cover when to emit fresh vs cite-prior vs skip vs remember.

## The four states

For any candidate finding, classify it against prior runs and memory before emitting:

1. **Net new** — no prior run mentions this topic, no memory entry covers it. → Emit if
   it clears the confidence bar (`confidence ≥ 0.65`, see
   [finding-schema.md](finding-schema.md)).

2. **Material update on a prior run** — a prior run covered the topic, but you have new
   evidence: a different source corroborating, a fresh deploy correlation, contradicting
   data, a meaningful escalation in scope. → **Emit fresh, citing the prior `finding_id`
   in the description and in the evidence list** (`source_product: signals_agent`,
   `entity_id: <prior_finding_id_or_run_id>`). The inbox groups by dedupe key so this is
   how you advance the picture without spamming.

3. **Same fact already covered** — a prior run already emitted with the same evidence
   shape. → Skip. Optionally write a memory entry confirming the topic stayed quiet.

4. **Already-addressed or noise** — memory says "addressed", "noise", "ignore", or names
   the issue id with a "team aware" note. → Skip and note in your summary that memory
   covered it.

## Reading prior runs efficiently

`signals-agent-runs-list` returns recent run summaries (the prose closing
paragraph). Skim the summaries, not the full prompts. A run summary that mentions your
candidate's entity ID, dedupe-key keyword, or topic is enough to flag for closer reading
via `signals-agent-runs-retrieve`.

When in doubt, read the prior run's findings (`get_run.findings`) — they expose the
exact `dedupe_keys`, evidence ids, and time_range you'd be re-emitting.

## Reading memory efficiently

`signals-agent-memory-list` defaults to non-expired entries. Sort visually by:

- `tags` containing `dedupe`, `noise`, `addressed`, `ignore`, or your candidate topic.
- Recent `created_at` first.

Trust memory. If a memory entry says "issue 019de34e... stayed quiet after 13:22 — treat
as already-surfaced", and your current observation matches (still quiet, no new
fingerprints), skip.

## When to write memory vs emit

| Situation                                                           | Action                             |
| ------------------------------------------------------------------- | ---------------------------------- |
| Confirmed real signal, not yet emitted by anyone.                   | `emit_finding` (new).              |
| Confirmed real signal, prior run covered it, you have new evidence. | `emit_finding` (cite prior id).    |
| Pattern observed but `confidence < 0.65`.                           | `remember` with hypothesis + tags. |
| Investigated and ruled out; would waste a future run if rechecked.  | `remember` ("ruled out: <why>").   |
| Memory already covers this; no change.                              | Skip; note in summary.             |
| Issue currently quiet but worth re-checking later.                  | `remember` with conditional steer. |

## Memory entry shape that pays off

Good memory entries are **future-run actionable**. The next agent reads them and changes
behavior because of them:

```text
2026-05-01: surfaced UndefinedTable on access_control_propertyaccesscontrol (issue
019de34e-e2a3-7e53-80d0-8ccdd0866a36) — 434 users hit it 11:31-13:22 UTC, then stopped.
If a future run sees this issue still firing, escalate; if it's been quiet since 13:22,
treat as already-surfaced.
```

Why this works: dated, names the entity id, gives a clear conditional ("still firing →
escalate; quiet → skip"), bounded by a precise time anchor.

Bad memory entry: "we have errors today, FYI". No actionability, no entity, no condition
— the next run can't act on it.

Use `tags` so future searches converge:

- `pattern` — durable observation about how this team's data normally shapes (baselines,
  recurring cadences, healthy ratios). The most common tag in steady-state runs.
- `dedupe` — entries that gate future emits.
- `noise` — patterns to ignore (single-user, dev-only, recurring with no fix path).
- `addressed` — team-confirmed fix shipped, or a topic the team has already moved on
  from.
- `domain:<area>` — filterable by topic. Canonical values match the per-product
  references: `domain:error_tracking`, `domain:warehouse`, `domain:experiments`,
  `domain:llm_analytics`, `domain:web_analytics`, `domain:feature_flags`,
  `domain:logs`.
- `entity:<id>` — direct lookup (issue id, flag key, experiment id, source prefix,
  insight short_id, etc.).
- `tag:exploration` — written from a wildcard / coverage-rotation read (see
  [calibration.md](calibration.md)). Distinguishes "I deliberately poked here and
  it was quiet" from a real `noise` tag. A future wildcard can re-check
  `tag:exploration` entries; a `noise` tag should be trusted longer.

TTL defaults to 7 days for `agent_inference` memory. Override with `ttl_days` (clamped
`[1, 90]`) when the steer should outlast the default — e.g. a long-lived "team-confirmed
this is acceptable noise" needs 60+ days.

## Cross-run noise patterns to recognize

These are noise across all PostHog projects. Skip them unless you see a real escalation:

- **Single-user, single-session errors** — one user, one occurrence, no other signal.
  Almost always a personal browser quirk.
- **Dev-environment exception bursts** — high counts on `$exception` events whose
  `service` or `properties.env` is `dev`/`local`/`test`. Filter these out before
  weighing.
- **Sandbox-internal Docker/agentsh errors** — Docker `TimeoutExpired`, sandbox sync
  failures. Internal harness operations, not user-facing.
- **KEA store-path errors with single-session reach** — frontend logic state quirks; not
  user-impacting unless you see distinct_user counts climbing.
- **Pre-known Anthropic upstream errors** — already covered by past memory; don't re-emit
  unless there's a meaningful change in volume or shape.

These are starting heuristics — the team's `SignalMemory` extends this list per-project
as the agent learns.
