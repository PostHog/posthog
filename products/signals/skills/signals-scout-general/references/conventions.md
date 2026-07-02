# Conventions

How to decide what to do with a candidate observation, how to write durable
scratchpad entries, and noise patterns common across PostHog projects.

## The four states

Classify every candidate finding against prior runs, the inbox, and the scratchpad
before you author a report (the harness prompt carries the report-channel contract):

1. **Net new** — no prior run, no inbox report, and no scratchpad entry covers this
   topic. → Author a report with `emit-report` if it clears the report bar.

2. **Material update on an existing report** — a report already covers the topic
   (one you authored last run, or a pipeline report), but you have new evidence: a
   different source corroborating, a fresh deploy correlation, contradicting data, a
   meaningful escalation in scope. → **`edit-report` it** — `append_note` with the
   fresh evidence, or rewrite `title`/`summary` on a report you authored. Don't mint
   a near-duplicate.

3. **Same fact already covered** — an existing report already captures the same
   evidence shape, nothing has changed. → Skip. Optionally rewrite an existing
   scratchpad entry confirming the topic stayed quiet (same key + new content =
   idempotent refresh).

4. **Already-addressed or noise** — a scratchpad entry has `addressed:` /
   `noise:` / `dedupe:` prefix and names the issue id with a "team aware" note.
   → Skip; note in your summary that the scratchpad covered it.

## Scratchpad key prefixes

The scratchpad has no tags. Encode the category in the **key prefix** so future
runs can find an entry with a single `text=` search:

| Prefix        | Use for                                                                                                                                                |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `pattern:`    | Durable observation about how this team's data normally shapes (baselines, etc).                                                                       |
| `noise:`      | Patterns to ignore (single-user, dev-only, recurring with no fix path).                                                                                |
| `addressed:`  | Team-confirmed fix shipped or topic the team has moved on from.                                                                                        |
| `dedupe:`     | Gates future runs on a specific issue / fingerprint so you don't re-file it.                                                                           |
| `allowlist:`  | Vetted entities the scout should never re-surface.                                                                                                     |
| `not-in-use:` | Close-out memo for "product not in use on this team".                                                                                                  |
| `mcp-gap:`    | Scout-noticed gap in the MCP surface worth raising in a future review.                                                                                 |
| `report:`     | A report this scout authored — stores the `report_id`, keyed `report:<domain>:<entity>`, so the next run edits/dedups against it instead of re-filing. |
| `reviewer:`   | A resolved owner (bare lowercase GitHub login), keyed `reviewer:<domain>:<area>`, so the next run sets `suggested_reviewers` without re-resolving.     |

Format: `<prefix>:<domain>:<entity>` (e.g. `pattern:error_tracking:baseline`,
`noise:logs:rabbitmq-deploy-window`, `dedupe:csp_violations:a1b2c3d4`).

Common `<domain>` values in fleet use: `error_tracking`, `warehouse`, `experiments`,
`llm_analytics`, `web-analytics`, `feature-flags`, `logs`, `surveys`,
`revenue_analytics`, `csp_violations`, `observability_gaps`, `session-replay`,
`pipelines`, `health`, `anomaly_detection`. Not a closed set — a specialist (or a
custom scout) coins its own label and reuses the prefixes; match the label a
surface's existing entries already use rather than inventing a variant.

Re-using a key updates the entry in place and refreshes `updated_at` — that's
the idempotent refresh pattern. Use it to confirm a quiet observation without
duplicating entries.

## When to author a report vs write a scratchpad entry

| Situation                                                           | Action                                                                  |
| ------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Confirmed, well-formed finding no existing report covers.           | Author a report (`emit-report`).                                        |
| Existing report covers it and you have new evidence.                | `edit-report` (append a note, or rewrite a report you authored).        |
| Pattern observed but you can't yet stand behind it as a 1:1 report. | Scratchpad entry with `pattern:` prefix; keep investigating.            |
| Investigated and ruled out; would waste a future run if rechecked.  | Scratchpad entry with `noise:` or `addressed:` prefix.                  |
| Scratchpad or inbox already covers this; no change.                 | Skip; note in summary.                                                  |
| Issue currently quiet but worth re-checking later.                  | Rewrite the existing entry (same key) with fresh timestamp + condition. |

## Entry shape that pays off

Good entries are **future-run actionable**. The next scout reads them and
changes behavior because of them. Write `content` as Markdown — humans read these
entries directly, so structured Markdown (headings, bullets, `inline code` for ids)
is far easier to skim than a wall of prose:

```text
key:     dedupe:error_tracking:019de34e-2026-05-01
content: "2026-05-01: surfaced UndefinedTable on access_control_propertyaccesscontrol
         (issue 019de34e-e2a3-7e53-80d0-8ccdd0866a36) — 434 users hit it 11:31-13:22 UTC,
         then stopped. If a future run sees this issue still firing, escalate; if it's
         been quiet since 13:22, treat as already-surfaced."
```

Why this works: dated, names the entity id, gives a clear conditional ("still
firing → escalate; quiet → skip"), bounded by a precise time anchor. The key
prefix makes it findable via `text=dedupe:` or `text=error_tracking`.

Bad entry: key `note-1`, content "we have errors today, FYI". No actionability,
no entity, no condition, key carries no category — the next run can't find it
or act on it.

## Cross-project noise patterns

These are noise across all PostHog projects. Skip them unless you see a real
escalation:

- **Single-user, single-session errors** — one user, one occurrence, no other
  signal. Almost always a personal browser quirk.
- **Dev-environment exception bursts** — high counts on `$exception` events
  whose `service` or `properties.env` is `dev` / `local` / `test`. Filter before
  weighing.
- **Sandbox-internal Docker / agentsh errors** — Docker `TimeoutExpired`,
  sandbox sync failures. Internal harness operations, not user-facing.
- **KEA store-path errors with single-session reach** — frontend logic state
  quirks; not user-impacting unless distinct_user counts climb.
- **Pre-known upstream provider errors** (Anthropic / OpenAI rate limits, etc.)
  — already covered by past scratchpad entries; don't re-file unless volume or
  shape changes meaningfully.

The team's scratchpad extends this list per-project as the scout learns.
