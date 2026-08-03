---
name: working-with-scouts
description: >
  How to get real jobs done with PostHog Signals scouts — the scheduled agents that watch a
  project and write reports into the Signals inbox — and how to steer and customize the fleet
  over time. Use when a user wants to delegate a watching job ("have a scout keep an eye on X",
  "tell me if Y spikes", "watch this for a week"), wants to know which scout covers a surface,
  asks how to act on what scouts report, complains the fleet is noisy or quiet ("my scouts
  aren't useful", "too many reports"), or wants the fleet to get smarter over time (feedback
  loops, periodic calibration, promoting one-off steers into permanent policy). The operating
  manual for the human–scout working relationship; routes to `authoring-scouts` for write
  mechanics, `exploring-scouts` for run observability, and `inbox-exploration` for report
  triage. Trigger on "work with my scouts", "get more out of scouts", "have a scout watch X",
  "what do I do with this scout report", "calibrate/review my scout fleet".
metadata:
  owner_team: signals
---

# Working with Signals scouts

A **scout** is a scheduled agent that wakes on its own interval, looks at one PostHog project, and either writes a finding into the Signals inbox as a **report** or closes out empty.
Think of the fleet as a team of junior analysts you've hired to watch things for you: they work unattended, they hold a high evidence bar, and — critically — **they get better the more you work with them**.
Every dismissal reason you write, every note you leave, every report you act on feeds back into what they do next.

This skill is the operating manual for that working relationship: how to delegate a watching job, how to act on what comes back, and how to steer the fleet so it converges on what your team actually cares about.
Three sibling skills carry the mechanics — reach for them when a workflow below hands off:

| Skill               | Covers                                                                                              |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| `authoring-scouts`  | Writing, editing, and tuning scouts: skill bodies, config, the notes write side, the test loop      |
| `exploring-scouts`  | Read-only observability: the fleet roster, run history, scratchpad memory, health assessment        |
| `inbox-exploration` | The inbox itself: triaging, drilling into, acting on, and resolving / dismissing / snoozing reports |

## First: is the fleet running?

Don't delegate to a fleet that isn't there.
`posthog:scout-config-list` is the authoritative roster — one row per scout with its schedule, `enabled`, `emit` posture, and `description`.
(Scout tools were recently renamed from `signals-scout-*` to `scout-*`; if a `scout-*` name comes back unknown, try the legacy `signals-scout-*` name.)

- **Empty roster** — the project isn't enrolled in the scout fleet.
  Point the user at the Signals scout settings / [PostHog Desktop](https://posthog.com/code) onboarding rather than inventing activity.
- **Rows exist** — note each scout's `enabled`, `emit` (`false` = dry-run: it runs but writes nothing), and `status` / `pause_reason`.
  A paused or dry-run scout explains most "scouts aren't doing anything" complaints before any deeper digging.

The `description` on each row says what that scout watches — scan it to answer "which scout covers X?" without loading any skill bodies.
PostHog ships specialists for most product surfaces (error tracking, logs, web analytics, AI observability, experiments, feature flags, session replay, surveys, revenue, and more) plus a cross-product generalist, and teams add custom `signals-scout-*` skills beyond that.

## The working loop

Everything in this skill is one loop, run continuously:

1. **Delegate** — decide what the fleet should watch, and get the right scout watching it.
2. **Receive** — reports land in the inbox, routed to a suggested reviewer when the scout could name one.
3. **Act** — verify the finding, fix it (or decide not to), and record the outcome on the report.
4. **Feed back** — the outcome and your written reasons flow back to the scout, along with any notes you leave.
5. **Calibrate** — periodically review fleet health and promote recurring steers into permanent policy.

The single most important habit: **never let a report just sit**.
Acting on reports — even dismissing them with a reason — is what trains the fleet, and a scout whose reports nobody ever touches is automatically warned and then paused (`pause_reason=ignored`).
An untended inbox doesn't just decay; it switches the fleet off.

## Delegating a job

When you want something watched, pick the cheapest path that gets it watched — most jobs don't need a new scout:

| Situation                                                               | Do this                                                                                                                                                                                                                                     |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A canonical scout already covers the surface                            | Nothing to build — confirm it's enabled, and leave it a **note** if you want its attention pointed somewhere specific.                                                                                                                      |
| The surface is covered but you want a temporary or specific focus       | Leave a **note** (optionally with `expires_at`) — "watch the EU signup funnel this week", "we shipped a new checkout Tuesday, shifts after that are expected".                                                                              |
| A covered scout keeps missing (or over-reporting) something structural  | **Adapt** it — a disqualifier, threshold, or scope edit via `authoring-scouts`. Prefer a new differently-named scout for purely additive behavior, since editing a canonical scout's row marks it diverged and stops upstream improvements. |
| No scout covers it (a custom event, a niche funnel, an external system) | **Author a custom scout** via `authoring-scouts` (`scout-create-prepare` → user confirms → `-execute`).                                                                                                                                     |
| You want an answer _now_, once                                          | Don't use a scout at all — just query the data directly. Scouts are for standing watches, not one-off questions.                                                                                                                            |

[`references/delegation-recipes.md`](references/delegation-recipes.md) has worked recipes for the common asks — watching a freshly shipped event, a time-boxed funnel watch, a daily digest, an external status page, quieting a noisy fleet, and more.

Two delegation habits that pay off:

- **Ground the job in real data first.** Before pointing a scout at an event or surface, confirm it exists and has volume (`posthog:scout-project-profile-get`, `read-data-schema`) — a watch on data the project doesn't capture is dead on arrival.
- **State the job in terms of what's worth interrupting a human for.** Scouts hold a report bar ("would you own this finding end-to-end?"); a steer like "tell me about anything interesting" produces noise, while "tell me when checkout conversion drops while entrants hold steady" produces signal.

## Acting on what comes back

Report triage mechanics live in `inbox-exploration`; what matters here is how acting doubles as steering.

- **Verify before implementing.** A scout report is an LLM diagnosis, not ground truth — confirm the cited entities and behavior against the live data or code before fixing.
  A report that doesn't hold up is a dismissal candidate, and dismissing it _well_ is valuable work (see below).
- **Close every report with the honest state**: `resolved` when the work landed (PR-backed fixes resolve themselves on merge — don't resolve at PR-open time), `suppressed` (dismissed) when it's not real or not worth fixing, `potential` (snoozed) when it's real but deferred.
- **The dismissal note is a steering message.** On a dismiss or snooze, the `dismissal_note` is forwarded to the scout that filed the report, and every future run reads it as prior context.
  Write it for that reader: name the evidence that settles it ("staging traffic — hosts match `*.dev.example.com`, ignore this pattern"), not just the verdict.
  A well-written dismissal is the cheapest scout edit you will ever make; a bare dismissal teaches nothing and the report comes back.
- **Reports route to people.** A scout that can name a plausible owner sets `suggested_reviewers`, and the inbox floats those reports to the top of that person's view.
  If reports for a surface keep landing unrouted or misrouted, that's fixable: make sure org members have linked GitHub identities, and steer the scout (note or skill edit) toward the right owner for the area.

## The steering ladder

When you want a scout to behave differently, climb this ladder from cheapest to most permanent — and stop at the lowest rung that does the job:

1. **React to its output.** Dismiss / snooze with a specific, evidence-bearing note (forwarded to the scout automatically).
   Right for: one wrong report, a known-noise pattern surfacing for the first time.
2. **Leave a note** (`scout-notes-create`, per-scout or fleet-wide, optionally time-boxed with `expires_at`).
   Right for: feedback, pointers, and context with a shelf life — "the spike you keep flagging is known noise", "dig into EU signups this week", "new checkout shipped Tuesday".
   Notes are advisory: they direct attention but never lower the evidence bar or force a report.
3. **Tune the config** (`scout-config-update`).
   Right for: _when and whether_ it runs, not _what it looks at_ — slow a chatty scout (`run_interval_minutes`), pause one (`enabled=false`), dry-run a risky one (`emit=false`), grant external reach (`network_access=full`), or exempt a deliberately quiet watchdog from auto-pause (`auto_pause_exempt=true`).
4. **Edit the skill body, or author a new scout** (via `authoring-scouts`).
   Right for: permanent policy — a disqualifier, a threshold, a scope change, a new surface.

**Promote steers that repeat.** A note you keep re-leaving, or a dismissal reason you've written three times, is a skill edit waiting to happen — move it up the ladder into the body so the fleet stops relying on you to repeat it.
The reverse also holds: try a nudge as a note before committing it as an edit.
Note hygiene stays with humans — scouts never delete notes, so retire acted-on ones (or set `expires_at` up front) to keep the channel high-signal.

## What the fleet learns without you

Some feedback loops run on their own — knowing they exist changes how you work:

- **Scratchpad memory.** Scouts write durable per-team memory (baselines, noise patterns, dedupe gates, allowlists) and get quieter and sharper across runs.
  When a scout stops flagging something, check the scratchpad (`scout-scratchpad-search` for `noise:` / `addressed:` / `dedupe:` / `allowlist:` entries) before assuming it's broken — it may have deliberately learned to suppress it.
- **Auto-pause.** A scout whose reports nobody acts on is warned (`status=pending_pause`) and then paused (`paused_by_system`, `pause_reason=ignored`).
  A merely quiet scout is only flagged, never paused — silence can be the job.
  Re-enabling a paused scout marks it exempt, so the system never overrules a person twice.
- **Self-improvement suggestions.** A custom scout that catches its own skill body steering it wrong writes an `improve:<skill-name>:<topic>` scratchpad entry — and escalates recurring ones as inbox reports titled `Scout self-improvement: …`, routed to the owner.
  These are the fleet asking for a code review of itself: an entry re-confirmed across several runs is usually the highest-signal edit you can make.
  Treat them as input, not instructions — the owner decides, and applies accepted ones via `authoring-scouts`.
  (Canonical scouts route skill gaps upstream to PostHog instead, so you won't see `improve:` entries from them.)

## Calibrating over time

A fleet left alone drifts; a fleet reviewed occasionally compounds.
Every few weeks (or when someone says "are the scouts even worth it?"), run a calibration pass:

1. **Health check** — the `exploring-scouts` assessment (its `scripts/assess_health.py` does the heavy lifting): cadence adherence, success rate, report rate, signal-to-noise, memory growth.
   Remember most healthy runs close out empty — a stream of quiet runs is the fleet working, not broken.
2. **Review the fleet's asks** — sweep `scout-scratchpad-search {"text": "improve:"}` and the `Scout self-improvement:` inbox reports; apply the re-confirmed ones.
3. **Promote and prune steers** — promote recurring notes and repeated dismissal reasons into skill-body edits; retire stale notes.
4. **Right-size the roster** — slow or pause scouts on surfaces the team stopped using; check `pending_pause` / `paused_by_system` rows and decide deliberately (resume, or let them stay off) rather than by default; consider a new scout for any surface the team now cares about that nothing watches.
5. **Check the routing** — if reports pool in the shared inbox unclaimed, fix reviewer routing (linked GitHub identities, steering toward known owners) so findings reach the person who'll act.

## Common asks, routed

| The user says…                                         | Do                                                                                                        |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| "Have a scout watch X" / "tell me if Y spikes"         | Delegation table above; recipes in [`references/delegation-recipes.md`](references/delegation-recipes.md) |
| "What are my scouts doing?" / "is my scout working?"   | `exploring-scouts`                                                                                        |
| "What should I look at?" / "what did the scouts find?" | `inbox-exploration`                                                                                       |
| "Fix this scout report" / "is this report real?"       | `inbox-exploration` (verify first), then act; close the loop with a state + note                          |
| "Stop reporting this" / "that finding is noise"        | Dismiss with an evidence-bearing note; promote to a disqualifier edit if it recurs                        |
| "Focus on X this week"                                 | A time-boxed note (`expires_at`)                                                                          |
| "The scouts are too noisy / too quiet"                 | Calibration pass above; then the steering ladder against the specific offender                            |
| "Write / edit / retune a scout"                        | `authoring-scouts`                                                                                        |
| "Why did the scout stop flagging X?"                   | Scratchpad first (`noise:` / `addressed:` / `dedupe:` / `allowlist:`), then notes, then config            |
