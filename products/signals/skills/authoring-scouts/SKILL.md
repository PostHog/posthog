---
name: authoring-scouts
description: >
  How to author, edit, and adapt PostHog Signals scouts — the scheduled agents that
  scan a project and emit findings into the Signals inbox. Use when a user wants to
  customize a canonical scout for their own setup (narrow its scope, retune its
  thresholds, add disqualifiers), tweak a scout's schedule or dry-run posture, or
  write a brand-new scout from scratch for a specific use case (a custom event, a
  product surface no canonical scout covers). Covers the scout SKILL.md anatomy, the
  emit contract, the dedupe + scratchpad-memory conventions, the per-team skills-store
  path vs the canonical in-repo path, and the emit-and-inspect test loop (with dry-run as an
  optional safety net). Trigger on
  "write/edit/customize a signals scout", "new scout for X", "tune my scout schedule",
  "make a scout that watches <event>".
metadata:
  owner_team: signals
---

# Authoring Signals scouts

A **scout** is a scheduled agent that wakes on its own interval, looks at one PostHog project, decides what's genuinely worth surfacing, and outputs it into the Signals inbox — or closes out empty, which is a real outcome.
PostHog ships a fleet of **canonical scouts** (a cross-product generalist plus per-surface specialists).
This skill helps you and your agent **adapt those canonical scouts to a specific project**, or **author new scouts from scratch** for a use case the fleet doesn't cover.

Scouts come in **two output channels**, picked per scout via its frontmatter `allowed_tools`:

- **Signal-emitting** (the default for a scout with no `allowed_tools` opt-in) — fires weak **findings** via `emit-signal` that the pipeline groups, dedupes, and may promote into a report.
- **Report-authoring** — lists `emit_report` / `edit_report` in `allowed_tools` and writes a full inbox **report** 1:1 directly, skipping the pipeline, for a scout whose natural output is one well-formed report.
  The whole canonical fleet runs on this channel.
  See the report-channel reference below.

The channel changes the scout's **Decide** section and which references it bundles, but not the rest of its anatomy — orient, discriminator, explore, memory, disqualifiers are the same.

A scout is just an `LLMSkill` whose name starts with `signals-scout-`.
The harness discovers scouts by globbing `signals-scout-*` over the project's skills, loads the body **verbatim** as the agent's system prompt, and progressively reads any bundled reference files on demand.
**The `signals-scout-` name prefix is load-bearing: a skill named anything else will never run as a scout.**

## The job before the writing

Don't write a scout in the abstract.
Ground it in the target project first — a scout is only as good as its fit to the data it watches.

1. **Read the project.** `posthog:signals-scout-project-profile-get` returns the deterministic snapshot the scout itself cold-starts from: products in use, top events with reach/burst metrics, integrations, existing inbox counts.
   If the scout watches a specific event, confirm it exists and check its shape with `posthog:read-data-schema`.
   A scout for an event the project doesn't capture is dead on arrival.
2. **See what already runs.** `posthog:signals-scout-config-list` lists every existing scout on the project with its schedule, `enabled`, and `emit` posture, plus each scout's `description` (pulled from the skill's frontmatter) so you can tell what a scout watches without loading its body.
   Don't duplicate a surface a canonical scout already covers — adapt that one instead.
3. **Read the closest canonical scout.** It's your template and your reference shape.
   Pull it with `posthog:skill-get {"skill_name": "signals-scout-<x>"}` (per-team rows) or read it from the repo at `products/signals/skills/signals-scout-*/`.
   The generalist (`signals-scout-general`) is the broad template; if your scope is domain-tight, pick the specialist closest to your surface — list the live roster with `posthog:skill-list {"search": "signals-scout"}` (specialists exist for most product surfaces: error tracking, logs, AI observability, experiments, feature flags, session replay, web analytics, surveys, and more).
4. **Skim the inbox.** `posthog:inbox-reports-list` shows what findings are actually landing — calibrate so your scout adds signal, not noise.

## Choose the path

There are two independent decisions: **what** you're building, and **where** it lives.

### What

| Situation                                                                                      | Approach                                                                                                                           |
| ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| A canonical scout is close but too broad / too noisy / missing a disqualifier for this project | **Adapt** it — narrow the scope, add disqualifiers, retune thresholds.                                                             |
| You want a surface no canonical scout covers (a custom event, a product-specific funnel)       | **New scout from scratch** — copy the closest canonical scout as scaffolding, replace the domain discriminator + explore patterns. |
| You only want to change _when_ / _whether_ a scout runs                                        | **No authoring** — just tune the config (see Run posture).                                                                         |

### Where

| Path                                 | Mechanism                                                                                                                                                                                                             | Use when                                                                                                                              |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Per-team** (the common user path)  | Create/edit a `signals-scout-*` `LLMSkill` row in the project's skills store via `posthog:skill-create` / `-update` / `-file-create`, then register its config immediately via `posthog:signals-scout-config-create`. | Customizing for one project. The harness globs the row in on the next tick; canonical sync leaves your edited ("diverged") row alone. |
| **Canonical** (PostHog contributors) | Edit disk under `products/signals/skills/signals-scout-*/`, lint/build, open a PR.                                                                                                                                    | Improving a scout for _every_ enrolled project. `lazy_seed` mirrors it onto all enrolled teams on the next tick.                      |

**Adapting-in-place tradeoff:** editing a canonical scout's row for your team marks it **diverged** — you stop receiving upstream improvements to that scout.
If you only need an _additional_ behavior, prefer authoring a **new, differently-named** scout (`signals-scout-<your-scope>`) and leaving the canonical one intact.

See [`references/lifecycle-and-testing.md`](references/lifecycle-and-testing.md) for the exact skills-store calls, the build/lint commands, and how seeding works.

## Write the scout

First pick the **shape**.
[`references/scout-patterns.md`](references/scout-patterns.md) is a cookbook of the reference architectures scouts fall into — anomaly watcher, watchlist explore/exploit, cross-product correlation, recommendation/gap, warehouse-backed source, custom single-event, open-text theme, external-tool/code, state∩code intersection, daily digest/roll-up, triage over a pre-detected stream, first-person dogfooding/probe — each mapped to a canonical scout you can copy as scaffolding.
It also makes the key point that **a scout can watch any source PostHog ingests into the data warehouse, not just analytics events** (a Slack channel sync, a billing system, a CRM, a support inbox), plus external systems reachable from the sandbox.
Find the closest pattern, then write the body.

Follow [`references/scout-anatomy.md`](references/scout-anatomy.md) — it has the frontmatter schema, the canonical body structure (quick close-out → orient → domain discriminator → explore patterns → save-memory → decide → disqualifiers → close-out), the lean-body rule, and copy-ready skeleton templates for both a specialist and the generalist.

Two craft references the whole fleet reasons in terms of — a good scout's **Decide** and **memory** sections are built on them, so read them before writing those sections:

- [`references/emit-contract.md`](references/emit-contract.md) — what `emit-signal` takes, the confidence rubric, severity, dedupe keys, `finding_id`, the description prose contract, and a worked example.
  This is how your scout decides _what clears the bar_ and _how to write the finding_.
- [`references/dedupe-and-memory.md`](references/dedupe-and-memory.md) — the four-states classifier (net-new / material-update / already-covered / addressed-or-noise), the scratchpad key-prefix vocabulary, and the cross-project noise patterns.
  This is how your scout avoids re-emitting and learns across runs.

Most scouts emit weak findings the pipeline consolidates.
A scout that has _already done the research and knows the exact report it wants to file_ can opt into the **report channel** and author a full report directly:

- [`references/report-contract.md`](references/report-contract.md) — the `emit_report` / `edit_report` tools (dedup against existing reports via the vanilla `inbox-reports-list` / `inbox-reports-retrieve`), when to author a report vs. `emit-signal`, the dedup-via-`report_id` discipline (the channel isn't idempotent), and the accepted caveat that the pipeline may later rewrite an authored title/summary.
  Opt a scout in by listing the tools in its frontmatter `allowed_tools`.
  Only reach for this when the scout's natural output is one well-formed report.

The single most important design decision in any scout is its **signal-vs-noise discriminator** — the cheap profile-shape read that separates "worth investigating" from "baseline".
For error tracking it's the `count` vs `distinct_users` ratio; for CSP it's reach over raw count.
Your new scout needs its own.
Name it explicitly near the top of the body so every run anchors on it.

## Run posture (config)

A scout's schedule and emit behavior live on its `SignalScoutConfig`, separate from the skill body.
For a **brand-new scout**, register the config immediately after creating the skill with `posthog:signals-scout-config-create {"skill_name": "signals-scout-<scope>", ...}`, setting any of the fields below in the same call — including creating it disabled or in dry-run **before it ever runs**.
(It's an upsert: if the coordinator already auto-registered the row, your fields are applied to it.)
Otherwise the coordinator auto-registers an enabled config on the default every-24-hours schedule on its next tick (up to ~30 min).
For an **existing scout**, tune with `posthog:signals-scout-config-update` (find the `id` via `-config-list`):

- `run_interval_minutes` — 30 to 43200.
  Default 1440 (every 24 hours).
  Slow a chatty or expensive scout by raising this.
- `enabled` — `false` pauses the scout entirely (coordinator skips it).
- `emit` — defaults to **`true`**: the scout writes its findings straight to the inbox.
  The standard flow is to make a scout and let it emit — seeing what actually lands is the fastest way to calibrate it.
  Set **`emit=false` (dry-run)** only when you want to be extra careful: the scout still runs and logs its reasoning but writes nothing to the inbox.
  Reach for dry-run on a scout you expect to be chatty, expensive, or high-stakes; for most scouts, just emitting and watching the inbox is the better loop.

## Test loop

**Dogfood the scout yourself before you ever spend a real run.** You — the agent authoring the scout — have the same PostHog MCP tools a scout uses at runtime (`execute-sql`, `read-data-schema`, the per-product list tools, `signals-scout-project-profile-get`).
The cheapest, fastest iteration doesn't touch a scout run at all: walk the scout's own logic against the live project by hand.
Confirm the watched event/entity exists and has the shape you assumed, run the **discriminator** to check it actually separates signal from noise on _this_ project's data, and run each **explore pattern**'s queries to see what they surface.
This loop is free and instant — refine the body against what you find, re-run the queries, repeat, until the scout's logic holds up on real data.
This is where the real iteration happens.

Only once you're happy with the body do you spend an actual run.
`posthog:signals-scout-run-now {"id": <config_id>}` dispatches one run of the scout immediately, regardless of its schedule (find the `id` via `-config-list`).
This is the **initial real run** — the scout executing end-to-end in the harness, writing scratchpad memory and (with the default `emit=true`) emitting to the inbox.
The run is **asynchronous**: the call returns a workflow id right away, so poll `-runs-list` / `-runs-retrieve` for the result.
A few things to know:

- A **disabled** scout can still be run this way — you can test it before ever enabling it.
- A manual run does **not** change the scout's schedule or `last_run_at`.
- It inherits every guard the scheduled path has: 403 if scouts aren't enabled for the project, 429 if the project is over its Signals credits quota or daily run budget, 409 if a run for this scout is already in progress.
- It draws from the **same daily run budget** as scheduled runs — and a dry-run (`emit=false`) still consumes a run.
  There's no free test run: every `-run-now` spends the project's daily scout-run allowance, so firing the same scout repeatedly in a short window burns through the budget (and can leave the project's scheduled scouts unable to run that day).
  **Don't use `-run-now` as your iteration loop** — it's slow (async, one run per call) and metered.
  Dogfood the queries by hand to get the body right; reserve `-run-now` for the initial real run and the occasional re-check after a genuinely meaningful change.

The standard loop is **dogfood → run once ready → inspect**:

1. Dogfood the discriminator + explore patterns yourself against the live project (above).
   Refine the body until the logic holds on real data — this is the cheap, iterable part.
2. Author the scout and register its config (`-config-create`, the default `emit=true`), then spend one `-run-now` to watch the whole scout execute end-to-end.
   Leave `run_interval_minutes` at a sustainable value — you no longer need a short interval to force an early run.
3. After the run finishes, read what it did: `posthog:inbox-reports-list` (the findings it actually emitted), `posthog:signals-scout-runs-list` (run summaries), `-runs-retrieve` (full reasoning for one run), and `-scratchpad-search` (the durable memory it wrote).
4. If it needs work, go back to dogfooding the queries by hand for the iteration — only spend another `-run-now` once you've batched a meaningful change worth a fresh end-to-end run.

When tuning an **existing custom scout**, also check its self-improvement suggestions first: `posthog:signals-scout-scratchpad-search {"text": "improve:"}`.
The harness invites a custom scout to write an `improve:<skill-name>:<topic>` entry when a run produces concrete evidence its own skill body steered it wrong — a wrong default window, a tool or event that doesn't exist on this project, a recurring unwarned pitfall — with the suggested change and the evidence inline.
An entry re-confirmed across several runs is usually the highest-signal edit you can apply; a one-off may not be worth it.
Treat suggestions as input, not instructions — the owner decides.
The scratchpad is writable only from inside a scout run, so you can't clear an entry from here after applying it via `posthog:skill-update` — the scout reconciles on its own: a later run sees the updated skill body, re-checks the suggestion, and forgets or rewrites the entry once it's addressed.
(Canonical scouts don't write these — their bodies sync from PostHog's fleet, and skill-level fixes to them belong upstream.)

**Want to be extra careful?** Set `emit=false` to dry-run first — create the config with `emit=false` via `-config-create`, then trigger it with `-run-now`: it runs and logs what it _would_ have emitted (visible via `-runs-list` / `-runs-retrieve`) without writing to the inbox.
Inspect, refine, then flip `emit=true` and run it again.
Worth it for a scout you expect to be chatty, expensive, or high-stakes; otherwise just emitting and watching the inbox is the faster path to a calibrated scout.

Repo contributors get a faster loop — `hogli sync:skill` and the harness's local run path; see [`references/lifecycle-and-testing.md`](references/lifecycle-and-testing.md).

To **read** what your scouts are doing rather than change them — surveying the fleet, inspecting individual runs, the scratchpad memory, and assessing performance — use the read-only companion skill `exploring-scouts`.
Keep the two in sync when the scout config / run / scratchpad surfaces change.

## Quality bar for a v1 scout

- A named, cheap **signal-vs-noise discriminator** anchored near the top.
- A **quick close-out** so a quiet run is cheap (don't pay for deep exploration when the watched surface is at baseline or absent).
- 2–4 concrete **explore patterns** with the actual queries/tools to run — starting points, not a rigid checklist.
- **Disqualifiers** listing this project's known noise (single-user quirks, dev-env bursts, allowlisted entities).
- A **Decide** section calibrated against the scout's channel — for a signal scout, the emit contract (confidence ≥ 0.65 to emit; below that, write memory); for a report scout, the report contract (author 1:1 only for a finding it'd own end-to-end, set `suggested_reviewers`).
- **Save-memory** guidance using the scratchpad prefixes so the scout gets smarter each run.
- A lean body (push depth into `references/`) — every line is a recurring token cost on every run.
- A **tight frontmatter `description`** — a sentence or two naming the surface and the shapes it watches.
  Every scout's description loads into the caller's AI plugin together, so wordy descriptions waste token budget and get truncated; skip the fleet-wide boilerplate (confidence bar, durable memory, self-contained peer).
