# Scout anatomy

A scout is a single `SKILL.md` (its body is loaded verbatim as the agent's system prompt) plus optional `references/` files read on demand.
Keep the body lean and push depth into references — every line of the body is a recurring token cost on **every** run.

## Contents

- Naming
- Frontmatter
- Body structure (lean core and task routes)
- References
- Skeleton — specialist scout
- Skeleton — broad / cross-product scout

## Naming

Any valid skill name works: lowercase letters, numbers, and hyphens.
The `SignalScoutConfig` row is what makes a skill a scout.
Name it in lowercase kebab-case after the surface or question the scout watches: `error-tracking`, `checkout-funnel`, `mcp-feedback`.
The canonical fleet keeps the `signals-scout-` prefix, and a per-team scout can use it too.
The prefix only controls whether the coordinator auto-registers a config for a skill that has none, so a scout named anything else comes in through `scout-create-prepare` / `-execute`, which writes the skill and its config in one call.

## Frontmatter

```yaml
---
name: signals-scout-<scope>
description: >
  One or two sentences, third person: the surface it watches and the specific shapes it
  looks for (bursts, regressions, clusters, drops). Keep it tight. Don't restate the
  fleet-wide boilerplate every scout shares (files reports above the bar, writes
  memory, closes out empty, self-contained peer) — that's assumed, and repeating it
  across the fleet burns the caller's token budget and gets truncated in AI plugins.
allowed_tools:
  - emit_report
  - edit_report
compatibility: >
  Designed for the PostHog Signals agent in a Claude sandbox with PostHog MCP scopes
  (read-only analytics plus signal_scout_report:write for reports and
  signal_scout_internal:write for scratchpad).
  Assumes the signals-scout MCP family (project-profile-get, runs-list, runs-retrieve,
  scratchpad-search, scratchpad-remember, scratchpad-forget, emit-report, edit-report)
  plus whatever query tools the scope needs (e.g. execute-sql, read-data-schema,
  query-error-tracking-issues-list, inbox-reports-list).
metadata:
  owner_team: signals # or the team that owns the scope
  scope: <scope> # short machine label, e.g. error_tracking, csp_violations
---
```

`name` and `description` are required and validated at build time.
`allowed_tools` with `emit_report` / `edit_report` is what puts the scout on the report channel — **every scout needs it** (without it the scout falls back to a deprecated legacy signal-emitting channel and can't write reports).
`compatibility` and `metadata` are optional but conventional — `compatibility` documents the scopes/tools the scout assumes; `metadata.scope` gives downstream tooling a short label.

The `description` does double duty: beyond skill discovery, it is surfaced verbatim as the scout's `description` on the config API (`scout-config-list` / `-create` / `-update` responses) — it's how the fleet roster reads to agents and the UI without opening each scout's body.
Write it to stand alone in that listing, and keep it short: it's also loaded alongside every other scout's into a caller's AI plugin, where a wordy description wastes token budget and gets truncated.
A sentence or two that names the surface and the shapes is the whole job.

## Body structure

Treat `SKILL.md` as a lean core and route selector. It loads on every run. A reference loads only when its route needs it.

Keep these items in the core:

1. **Identity and discriminator.** State the scout's task and name the cheap signal-vs-noise discriminator. Examples include `count` against `distinct_users`, reach over raw count, or negative share against baseline.
2. **Stop gates.** Define the cheapest safe conditions for ending a quiet run. Include any pre-route check needed to avoid a false empty result, such as checking a longer window when `top_events` is thin.
3. **Route conditions.** Define the small set of investigation lanes and name the exact reference file to read for each lane. Make the routes mutually clear. State when several routes may run.
4. **Pre-route invariants.** Keep only the task-specific facts that every route needs before selection, such as source availability, ownership, or one shared discriminator query.
5. **Universal task rules.** Keep a rule in the core only when it is specific to this scout and applies to every route.

Put task depth in lazy references:

- Lane-specific SQL, tool sequences, thresholds, and classification logic.
- Candidate-only reporting criteria and disqualifiers.
- Task-specific memory keys and content formats.
- Detailed examples, taxonomies, and edge cases.

A recurring measurement / LLM-judge scout uses the same structure. Its core contains the population gate and route selection. Its task reference contains the rubric, sampling rules, and record shape. It stops early only when there are no eligible items because ordinary judgments form the denominator.

Do not copy behavior that the scout harness already supplies. In particular, do not restate:

- Generic prior-run, sibling-run, notes, or scratchpad lookup.
- Generic scratchpad prefixes or save-as-you-go instructions.
- The generic report author/edit contract or reviewer routing.
- The generic tool catalog.
- The generic run-summary or close-out contract.

Add only the task-specific part of those behaviors. For example, a route may define the exact memory key for a rejected warehouse candidate, or the evidence required before a GitHub item is report-worthy. Do not repeat how to call the generic memory or report tools.

## References

Use references for task-specific depth by default. This keeps startup context small and loads only the instructions needed for the selected lane. A small scout may need one task reference. A scout with distinct lanes should normally have one reference per lane.

Every reference must be self-contained for the route that loads it:

- Do not depend on text described as "above", "below", or "at the top of this file".
- Do not link to a section that the route does not also load.
- Repeat a small task-specific invariant when that is necessary to make the route safe in isolation.
- Route every outcome that needs task-specific memory to the reference that defines that memory, including rejected candidates and all-clear digests.

Do not bundle copies of fleet-wide conventions or the report-channel contract. Attach references to a per-team scout with `posthog:skill-file-create`; in the repo, place them in `references/` so the build collects them.

## Skeleton — specialist scout

```markdown
---
name: signals-scout-<scope>
description: >
  Signals scout for PostHog <surface>. Watches <event/metric> for <the shapes: bursts /
  regressions / clusters / drops>.
allowed_tools:
  - emit_report
  - edit_report
compatibility: >
  Designed for the PostHog Signals agent in a Claude sandbox with PostHog MCP scopes
  (read-only analytics plus signal_scout_report:write and signal_scout_internal:write).
  Assumes the signals-scout MCP family plus <the query tools this scope needs>.
metadata:
  owner_team: <team>
  scope: <scope>
---

# Signals scout: <surface>

You are a focused <surface> scout. Watch <event/metric> for <meaningful shapes>.

The relationship between <X> and <Y> is the primary signal-vs-noise discriminator.

## Stop gates

- If <safe empty condition>, stop.
- If <ambiguous empty condition>, first check <longer-window or source-health invariant>.

## Route

After the stop gates and shared check, choose the matching lane:

- **<Lane A>:** when <condition>, read `references/lane-a.md` and follow it.
- **<Lane B>:** when <condition>, read `references/lane-b.md` and follow it.
- **No matching lane:** stop.

Run more than one lane only when <task-specific condition>.

## Shared task invariant

Before selecting a lane, <one check that every lane requires>.
```

Example `references/lane-a.md`:

```markdown
# <Lane A>

Use <specific query or tool sequence>.

## Classification

- <shape and threshold> means <task-specific outcome>.
- Reject <task-specific disqualifier>.

## Candidate handling

For a qualifying candidate, require <specific evidence>.
For a rejected candidate, remember `<scope>:rejected:<entity>` with <task-specific fields>.
```

## Skeleton — broad / cross-product scout

Start from `signals-scout-general` instead.
Its job is **cross-product correlations** and **surfaces no specialist covers** — it deliberately leaves single-surface deep dives to the specialists and rotates investigative lenses across runs to avoid lens-lock.
Use this shape when your scout's question spans products (e.g. "deploy → error burst → revenue dip") rather than living inside one surface.
