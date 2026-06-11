# Scout anatomy

A scout is a single `SKILL.md` (its body is loaded verbatim as the agent's system prompt)
plus optional `references/` files read on demand. Keep the body lean and push depth into
references — every line of the body is a recurring token cost on **every** run.

## Contents

- Naming
- Frontmatter
- Body structure (the ten canonical sections)
- References
- Skeleton — specialist scout
- Skeleton — broad / cross-product scout

## Naming

The skill name **must** match `signals-scout-<scope>` — the harness discovers scouts by
globbing `signals-scout-*`. `<scope>` is lowercase kebab-case naming the surface or
question the scout watches: `signals-scout-error-tracking`, `signals-scout-checkout-funnel`,
`signals-scout-mcp-feedback`. A skill named anything else is just a normal skill and never
runs as a scout.

## Frontmatter

```yaml
---
name: signals-scout-<scope>
description: >
  One paragraph, third person. State the surface it watches, the specific shapes it
  looks for (bursts, regressions, clusters, drops), that it emits only above the
  confidence bar and otherwise writes memory and closes out empty, and that it's a
  self-contained peer in the signals-scout-* fleet.
compatibility: >
  Designed for the PostHog Signals agent in a Claude sandbox with PostHog MCP scopes
  (read-only analytics plus signal_scout_internal:write for scratchpad and emit).
  Assumes the signals-scout MCP family (project-profile-get, runs-list, runs-retrieve,
  scratchpad-search, scratchpad-remember, scratchpad-forget, emit-signal) plus whatever
  query tools the scope needs (e.g. execute-sql, read-data-schema,
  query-error-tracking-issues-list, inbox-reports-list).
metadata:
  owner_team: signals # or the team that owns the scope
  scope: <scope> # short machine label, e.g. error_tracking, csp_violations
---
```

`name` and `description` are required and validated at build time. `compatibility` and
`metadata` are optional but conventional — `compatibility` documents the scopes/tools the
scout assumes; `metadata.scope` gives downstream tooling a short label.

The `description` does double duty: beyond skill discovery, it is surfaced verbatim as the
scout's `description` on the config API (`signals-scout-config-list` / `-create` / `-update`
responses) — it's how the fleet roster reads to agents and the UI without opening each
scout's body. Write it to stand alone in that listing.

## Body structure

The canonical body is a workflow, not a script — it reads like how an experienced analyst
would approach the surface, and trusts the agent to adapt. The fleet's specialists all
share this shape:

1. **Identity + discriminator (the most important lines).** One sentence on what the scout
   is, then **name the signal-vs-noise discriminator explicitly** and tell the agent to
   internalize it. This is the cheap profile-shape read that separates "worth a look" from
   "baseline". Examples: `count` vs `distinct_users` ratio (error tracking); reach over raw
   count (CSP); negative+mixed share vs baseline (MCP feedback). Without this, the scout
   wastes every run re-deciding what "normal" means.

2. **Quick close-out.** A cheap early-exit so a quiet run costs almost nothing: if the
   watched event is absent from the profile's `top_events` or sitting at baseline (no fresh
   24h activity), write one scratchpad entry and stop. This keeps idle scouts cheap.

   ```text
   key:     not-in-use:<scope>:team{team_id}     # if the surface is absent entirely
        or  pattern:<scope>:baseline-team{team_id} # if it fires at a steady baseline
   content: "<surface> baseline ~{count}/day, no fresh 24h burst at {timestamp}"
   ```

3. **Orient.** Three cheap reads cold-start every run — bake them into the body:
   - `signals-scout-scratchpad-search` (`text=<scope keyword>`) — durable steering from
     past runs; the `pattern:` / `noise:` / `addressed:` / `dedupe:` entries tell the scout
     what's normal and what's already covered.
   - `signals-scout-runs-list` (last 7d) — what prior runs of this scout (and siblings)
     found and ruled out. Pull `-runs-retrieve` only for a summary worth drilling into.
   - `signals-scout-project-profile-get` — the deterministic snapshot; read the discriminator
     metrics off the relevant `top_events` row.

4. **Profile shape / discriminator table.** A small table mapping the discriminator's
   shapes to what they usually mean, so the agent triages fast. (See the error-tracking
   scout's `count`-vs-`distinct_users` table for the canonical example.)

5. **Explore patterns.** 2–4 named investigation patterns — **starting points, not a
   checklist**. Each names the concrete tools/queries to run and the shape that confirms it.
   E.g. "Burst with broad reach" → list active issues, SQL hourly breakdown, look for the
   one-occurrence-per-distinct-user shape. Give the agent real queries, not generic advice.

6. **Save memory as you go.** Tell the scout to write scratchpad entries continuously,
   encoding the category in the key prefix (see
   [`dedupe-and-memory.md`](dedupe-and-memory.md)). Give 2–3 worked example entries scoped
   to this surface so the agent matches the format.

7. **Decide.** Emit / remember / skip, calibrated against the emit contract (see
   [`emit-contract.md`](emit-contract.md)). State the surface-specific "strong finding"
   thresholds (e.g. "confidence ≥ 0.85, with concrete entity ids and counts
   in the evidence"). Tell it to cross-check `inbox-reports-list` before emitting.

8. **Disqualifiers.** The known noise for this surface that should be skipped (single-user
   quirks, dev-env bursts, allowlisted domains, known upstream provider errors). "When in
   doubt, write memory instead of emitting."

9. **MCP tools.** List the direct (read-only) calls and the harness-level tools the scout
   uses, so the agent doesn't rediscover them each run.

10. **Close out.** One paragraph: looked at what, emitted what, remembered what, ruled out
    what. The harness saves this as the run summary; future runs read it via
    `signals-scout-runs-list`. Tell it **not** to write a separate "run metadata" scratchpad
    entry — the summary already serves that role. "Looked but found nothing meaningful" is a
    real outcome.

Not every scout needs all ten sections, but every scout needs 1 (discriminator), 2 (quick
close-out), 3 (orient), 7 (decide), 8 (disqualifiers), and 10 (close out). Sections 4–6 and
9 are where a specialist earns its keep.

## References

The generalist carries two references the rest of the fleet reasons in terms of —
`references/emit.md` (the emit contract) and `references/conventions.md` (the four-states
classifier + scratchpad vocab). For a **per-team** scout you usually don't need to bundle
your own copies — the canonical scout already encodes the conventions inline, and your
scout body can too. Bundle a reference only when you have genuinely surface-specific depth
(a long SQL cookbook, a taxonomy of fingerprints) that would bloat the body. Attach bundled
files to a per-team scout with `posthog:llma-skill-file-create`; in the repo, drop them in
`references/` and they're collected automatically.

## Skeleton — specialist scout

```markdown
---
name: signals-scout-<scope>
description: >
  Focused Signals scout for PostHog projects using <surface>. Watches <event/metric> for
  <the shapes: bursts / regressions / clusters / drops>. Emits findings only when they
  clear the confidence bar; otherwise writes durable memory and closes out empty.
  Self-contained peer in the signals-scout-* fleet.
compatibility: >
  Designed for the PostHog Signals agent in a Claude sandbox with PostHog MCP scopes
  (read-only analytics plus signal_scout_internal:write). Assumes the signals-scout MCP
  family plus <the query tools this scope needs>.
metadata:
  owner_team: <team>
  scope: <scope>
---

# Signals scout: <surface>

You are a focused <surface> scout. Spot meaningful changes in <event/metric> — <the
shapes> — and emit findings only when they clear the confidence bar.

<Name the discriminator here.> The relationship between <X> and <Y> is the most important
signal-vs-noise discriminator. Internalize that shape.

## Quick close-out: is <surface> even loud?

If <event> is absent from `top_events` or at baseline (no fresh 24h activity), <surface>
isn't where the signal is today. Cheap scratchpad entry + close out empty.

## How a run works

Cycle between these moves; skip what's not useful.

### Get oriented

- `signals-scout-scratchpad-search` (`text=<scope keyword>`) — durable steering.
- `signals-scout-runs-list` (last 7d) — what prior runs found and ruled out.
- `signals-scout-project-profile-get` — read the discriminator metrics off `top_events`.

### Profile shape

| Pattern   | What it usually means           |
| --------- | ------------------------------- |
| <shape A> | <meaning A — investigate first> |
| <shape B> | <meaning B — usually noise>     |

### Explore

Patterns to watch — starting points, not a checklist.

#### <Pattern 1>

<the concrete queries/tools and the confirming shape>

#### <Pattern 2>

<...>

### Save memory as you go

Write a scratchpad entry whenever you observe something a future run should know. Encode the
category in the key prefix — `pattern:`, `noise:`, `addressed:`, `dedupe:`.

- key `pattern:<scope>:baseline` — "<normal shape for this project>"
- key `dedupe:<scope>:<entity>` — "<surfaced when, with what condition for next run>"

### Decide

- **Emit** via `signals-scout-emit-signal` above the bar (confidence ≥ 0.85,
  concrete entity ids + counts in evidence). Cross-check `inbox-reports-list` first.
- **Remember** if below the bar but worth carrying forward.
- **Skip** if a `noise:` / `addressed:` / `dedupe:` entry already covers it.

### Close out

One paragraph: looked at what, emitted what, remembered what, ruled out what.

## Disqualifiers (skip these)

- <surface-specific noise: single-user, dev-env, allowlisted, known-upstream>

## MCP tools

Direct (read-only): <list>. Harness-level: project-profile-get, scratchpad-search,
runs-list, runs-retrieve, emit-signal, scratchpad-remember.
```

## Skeleton — broad / cross-product scout

Start from `signals-scout-general` instead. Its job is **cross-product correlations** and
**surfaces no specialist covers** — it deliberately leaves single-surface deep dives to the
specialists and rotates investigative lenses across runs to avoid lens-lock. Use this shape
when your scout's question spans products (e.g. "deploy → error burst → revenue dip") rather
than living inside one surface.
