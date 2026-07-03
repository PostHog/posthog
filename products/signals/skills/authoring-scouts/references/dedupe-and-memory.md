# Dedupe and memory conventions

How a scout decides what to do with a candidate observation, how it writes durable scratchpad entries, and the noise patterns common across PostHog projects.
Author your scout's **Decide** and **Save-memory** sections around these — they're how the fleet avoids re-emitting and gets smarter every run.
This mirrors `signals-scout-general/references/conventions.md`.

## The four states

Every scout classifies each candidate finding against prior runs and the scratchpad before emitting.
Bake this classifier into the scout's Decide section:

1. **Net new** — no prior run mentions the topic, no scratchpad entry covers it. → Emit if it clears the confidence bar (≥ 0.65).
2. **Material update on a prior run** — a prior run covered it, but there's new evidence (a different corroborating source, a fresh deploy correlation, contradicting data, a meaningful escalation in scope). → **Emit fresh, citing the prior `finding_id`** in the description and the evidence list (`source_product: signals_scout`, `entity_id: <prior>`).
   The inbox groups by dedupe key.
3. **Same fact already covered** — a prior run emitted with the same evidence shape. → Skip.
   Optionally rewrite a scratchpad entry confirming the topic stayed quiet.
4. **Already-addressed or noise** — a scratchpad entry with an `addressed:` / `noise:` / `dedupe:` prefix names the entity with a "team aware" note. → Skip; note it in the run summary.

## Scratchpad memory

The scratchpad is durable, per-team prose keyed by string.
It has no tags or TTLs — **the category is encoded in the key prefix** so a future run finds an entry with a single `text=` search.
Re-using a key rewrites the entry in place (the idempotent refresh — use it to confirm a quiet observation without duplicating entries).

| Prefix        | Use for                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pattern:`    | Durable observation about how this team's data normally shapes (baselines).                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `noise:`      | Patterns to ignore (single-user, dev-only, recurring with no fix path).                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `addressed:`  | Team-confirmed fix shipped, or topic the team has moved on from.                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `dedupe:`     | Gates future emits on a specific issue / fingerprint / finding id.                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `allowlist:`  | Vetted entities the scout should never re-surface.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `not-in-use:` | Close-out memo for "product/surface not in use on this team".                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `mcp-gap:`    | Scout-noticed gap in the MCP surface worth raising later.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `improve:`    | Custom scouts only: an evidence-backed suggested change to this scout's own skill body, written for the scout's owner to review and apply (or reject). Keyed `improve:<skill-name>:<topic>` — skill name, not domain, since scratchpad keys are team-wide and two scouts sharing a domain would clobber each other. The harness prompt invites these on custom scouts; canonical scouts never write them (applying one would diverge the seeded row). The scout clears its own entry once a later run confirms the suggestion was addressed. |
| `report:`     | A report this scout authored via the report channel — stores the `report_id` so the next run edits/dedups against it instead of re-filing. See [`report-contract.md`](report-contract.md).                                                                                                                                                                                                                                                                                                                                                   |

Format: `<prefix>:<domain>:<entity>` — e.g. `pattern:error_tracking:baseline`, `noise:logs:rabbitmq-deploy-window`, `dedupe:csp_violations:a1b2c3d4`.
Each canonical specialist has its own `<domain>` label (`error_tracking`, `logs`, `llm_analytics`, `experiments`, `feature-flags`, `session-replay`, `web-analytics`, `pipelines`, `health`, …) — not a closed set.
A new scout introduces its own domain label and reuses the prefixes; match the label a surface's existing entries already use.

## When to write memory vs. emit

| Situation                                                          | Action                                                                    |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| Confirmed real signal, not yet emitted by anyone.                  | Emit (new).                                                               |
| Confirmed real signal, prior run covered it, new evidence.         | Emit (cite prior `finding_id`).                                           |
| Pattern observed but `confidence < 0.65`.                          | Scratchpad `pattern:` entry.                                              |
| Investigated and ruled out; would waste a future run if rechecked. | Scratchpad `noise:` / `addressed:` entry.                                 |
| Scratchpad already covers it; no change.                           | Skip; note in summary.                                                    |
| Issue currently quiet but worth re-checking later.                 | Rewrite the existing entry (same key) with a fresh timestamp + condition. |

## What a good entry looks like

Good entries are **future-run actionable** — the next scout reads them and changes behavior:

```text
key:     dedupe:error_tracking:019de34e-2026-05-01
content: "2026-05-01: surfaced UndefinedTable on access_control_propertyaccesscontrol
         (issue 019de34e...) — 434 users hit it 11:31-13:22 UTC, then stopped. If a future
         run sees this issue still firing, escalate; if quiet since 13:22, treat as
         already-surfaced."
```

Why it works: dated, names the entity id, gives a clear conditional ("still firing → escalate; quiet → skip"), bounded by a precise time anchor, and the key prefix makes it findable.
Bad entry: key `note-1`, content "we have errors today, FYI" — no actionability, no entity, no condition, uncategorized key the next run can't find or act on.

Give your scout 2–3 worked example entries scoped to its surface so each run matches the format instead of inventing its own.

## Cross-project noise patterns

These are noise across essentially all PostHog projects — list the relevant ones in your scout's **Disqualifiers** so it skips them unless there's a real escalation:

- **Single-user, single-session events** — one user, one occurrence, no other signal.
  Almost always a personal browser quirk.
- **Dev-environment bursts** — high counts whose `service` / `properties.env` is `dev` / `local` / `test`.
  Filter before weighing.
- **Sandbox-internal errors** — Docker `TimeoutExpired`, sandbox sync failures, `agentsh` errors.
  Internal harness operations, not user-facing.
- **Single-session frontend state quirks** — e.g. KEA store-path errors; not user-impacting unless distinct-user counts climb.
- **Known upstream provider errors** — Anthropic / OpenAI rate limits, third-party outages already covered by past memory.
  Don't re-emit unless volume or shape changes meaningfully.

The team's scratchpad extends this list per-project as the scout learns — which is exactly why the save-memory discipline matters.
