---
name: working-with-scouts
description: >
  How to get real jobs done with PostHog Signals scouts — the scheduled agents that watch a
  project and write reports into the Signals inbox — and how to steer and customize the fleet
  over time. Use when a user wants to delegate a watching job ("have a scout keep an eye on X",
  "tell me if Y spikes"), wants a recurring judged metric from a scout ("score X on a
  schedule", "measure quality of Y"), wants to know which scout covers a surface, asks how to
  act on what scouts report, complains the fleet is noisy or quiet, or wants the fleet to get
  smarter over time (feedback loops, calibration, promoting one-off steers into policy). The
  operating manual for the human–scout working relationship; routes to `authoring-scouts` for
  write mechanics, `exploring-scouts` for run observability, and `inbox-exploration` for report
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
Two reads answer it: `posthog:scout-metadata-get` says whether the project is **enrolled** to run scouts at all, and `posthog:scout-config-list` is the roster — one row per scout with its schedule, `enabled`, `emit` posture, and `description`.
Check enrollment first, whatever the roster shows — config rows outlive enrollment, so a drained project can carry a roster of enabled scouts that never run (stale `last_run_at` across the board is the tell).
(Scout tools were recently renamed from `signals-scout-*` to `scout-*`; if a `scout-*` name comes back unknown, try the legacy `signals-scout-*` name.)
One access rule covers everything here: scout rows live on the project's **canonical parent**, so every scout read and write — this roster read included, plus the notes and config steering below — returns 403 for a credential scoped only to a child environment; work from the parent project (or a credential that covers it).

- **Not enrolled** — point the user at the Signals scout settings / [PostHog Desktop](https://posthog.com/desktop) onboarding rather than inventing activity.
- **Enrolled, empty roster** — likely newly enrolled and awaiting the first coordinator tick (configs auto-register then); say so instead of re-sending the user through onboarding.
- **Enrolled, rows exist** — note each scout's `enabled`, `emit` (`false` = dry-run: it runs but writes nothing), and `status` / `pause_reason`.
  A paused or dry-run scout explains most "scouts aren't doing anything" complaints before any deeper digging.
  Also check `emit_eligibility` on `posthog:scout-project-profile-get`: when `can_emit` is false (the org hasn't approved AI processing, or the `signals_scout` source is disabled), every scout write is silently dropped even on an enabled `emit: true` scout — surface its `remediation` line before promising coverage.
  (For read callers the profile is a cached snapshot built by scout runs, so a 404 means no fresh profile exists — not ineligibility; fall back to checking the `signals_scout` source config via `posthog:inbox-source-configs-list` and treat eligibility as unknown rather than blocking on the profile.)

The `description` on each row says what that scout watches — scan it to answer "which scout covers X?" without loading any skill bodies.
(A row with an empty description is usually an orphan whose skill was since deleted — it can't run, so don't count it as coverage.)
PostHog ships specialists for most product surfaces (error tracking, logs, web analytics, AI observability, experiments, feature flags, session replay, surveys, revenue, and more) plus a cross-product generalist, and teams add custom `signals-scout-*` skills beyond that.

## The working loop

Everything in this skill is one loop, run continuously:

1. **Delegate** — decide what the fleet should watch, and get the right scout watching it.
2. **Receive** — reports land in the inbox, routed to a suggested reviewer when the scout could name one.
3. **Act** — verify the finding, fix it (or decide not to), and record the outcome on the report.
4. **Feed back** — the outcome and your written reasons flow back to the scout, along with any notes you leave.
5. **Calibrate** — periodically review fleet health and promote recurring steers into permanent policy.

The single most important habit: **never let a report just sit**.
Acting on reports — even dismissing them with a reason — is what trains the fleet, and a scout whose inbox reports nobody ever touches is automatically warned and then paused (`pause_reason=ignored`; Slack-delivered scouts are exempt, since consumption there can't be measured).
An untended inbox doesn't just decay; it switches the fleet off.

## Delegating a job

When you want something watched, pick the cheapest path that gets it watched — most jobs don't need a new scout:

| Situation                                                                                                     | Do this                                                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A canonical scout already covers the surface                                                                  | Nothing to build — confirm it's enabled, and leave it a **note** if you want its attention pointed somewhere specific.                                                                                                                                                                                                             |
| The surface is covered but you want a temporary or specific focus                                             | Leave a **note** (optionally with `expires_at`) — "watch the EU signup funnel this week", "we shipped a new checkout Tuesday, shifts after that are expected".                                                                                                                                                                     |
| A covered scout keeps missing (or over-reporting) something structural                                        | **Adapt** it — a disqualifier, threshold, or scope edit via `authoring-scouts`. Prefer a new differently-named scout for purely additive behavior, since editing a canonical scout's row marks it diverged and stops upstream improvements.                                                                                        |
| No scout covers it (a custom event, a niche funnel, an external system)                                       | **Author a custom scout** via `authoring-scouts` (`posthog:scout-create-prepare` → user confirms → `-execute`).                                                                                                                                                                                                                    |
| You want a recurring **metric**, not reports — a subjective quality/classification score no query can compute | **Author a measurement scout** on the structured-output channel: it judges a sample every run and records schema-validated `$scout_structured_output` events you chart in insights (and a workflow can act on), filing a report only on a material shift. See the recurring measurement / LLM-judge pattern in `authoring-scouts`. |
| You want an answer _now_, once                                                                                | Don't use a scout at all — just query the data directly. Scouts are for standing watches, not one-off questions.                                                                                                                                                                                                                   |

[`references/delegation-recipes.md`](references/delegation-recipes.md) has worked recipes for the common asks — watching a freshly shipped event, a time-boxed funnel watch, a daily digest, an external status page, quieting a noisy fleet, and more.

Two delegation habits that pay off:

- **Ground the job in real data first.** Before pointing a scout at an event or surface, confirm it exists (`posthog:scout-project-profile-get`, `posthog:read-data-schema`) and actually has volume (a quick `posthog:execute-sql` count over a recent window — the profile and schema tools don't return counts for a new or rare event) — a watch on data the project doesn't capture is dead on arrival.
- **State the job in terms of what's worth interrupting a human for.** Scouts hold a report bar ("would you own this finding end-to-end?"); a steer like "tell me about anything interesting" produces noise, while "tell me when checkout conversion drops while entrants hold steady" produces signal.

## Acting on what comes back

Report triage mechanics live in `inbox-exploration`; what matters here is how acting doubles as steering.

- **Verify before implementing.** A scout report is an LLM diagnosis, not ground truth — confirm the cited entities and behavior against the live data or code before fixing.
  A report that doesn't hold up is a dismissal candidate, and dismissing it _well_ is valuable work (see below).
- **Close every report with the honest state**: `resolved` when the work landed (PR-backed fixes resolve themselves on merge — don't resolve at PR-open time), `suppressed` (dismissed) when it's not real or not worth fixing, `potential` (snoozed) when it's real but deferred.
- **The dismissal note is a steering message.** On a dismiss or snooze, the `dismissal_note` is forwarded to the scout that filed the report, and every future run reads it as prior context.
  Write it for that reader: name the evidence that settles it ("staging traffic — hosts match `*.dev.example.com`, ignore this pattern"), not just the verdict.
  A well-written dismissal is the cheapest scout edit you will ever make; a bare dismissal teaches nothing and the report comes back.
  One caveat: forwarding is best-effort and requires the dismisser to hold scout-steering (skill-editor) access — without it the note still lands on the report but never reaches the scout, so for a steer that must stick, confirm it arrived (`posthog:scout-notes-list`) or have someone authorized leave a note directly.
  The forwarded note also expires after ~30 days — it becomes durable only if the scout folds it into scratchpad memory, so a steer that must outlive that belongs up the ladder as a skill edit.
- **Reports route to people.** A scout that can name a plausible owner sets `suggested_reviewers`, and the inbox floats those reports to the top of that person's view.
  If reports for a surface keep landing unrouted or misrouted, that's fixable: make sure org members have linked GitHub identities, and steer the scout (note or skill edit) toward the right owner for the area.

## The steering ladder

When you want a scout to behave differently, climb this ladder from cheapest to most permanent — and stop at the lowest rung that does the job:

1. **React to its output.** Dismiss / snooze with a specific, evidence-bearing note (forwarded to the scout automatically).
   Right for: one wrong report, a known-noise pattern surfacing for the first time.
2. **Leave a note** (`posthog:scout-notes-create`, per-scout or fleet-wide, optionally time-boxed with `expires_at`).
   Right for: feedback, pointers, and context with a shelf life — "the spike you keep flagging is known noise", "dig into EU signups this week", "new checkout shipped Tuesday".
   Notes are advisory: they direct attention but never lower the evidence bar or force a report.
3. **Tune the config** (`posthog:scout-config-update`).
   Right for: _when and whether_ it runs, not _what it looks at_ — slow a chatty scout (`run_interval_minutes`; if the config carries a `run_cron_schedule`, that takes precedence, so update or clear it too), pause one (`enabled=false`), dry-run a risky one (`emit=false`), grant external reach (`network_access=full`), or exempt a deliberately quiet watchdog from auto-pause (`auto_pause_exempt=true`).
4. **Edit the skill body, or author a new scout** (via `authoring-scouts`).
   Right for: permanent policy — a disqualifier, a threshold, a scope change, a new surface.
   For a **custom scout** this is the strongest steer there is: the skill body is yours, edit it freely — it's where recurring notes and repeated dismissal reasons should end up.
   For a **canonical scout** the same edit **forks it**: your team's copy is marked diverged, PostHog's canonical sync leaves it alone from then on, and you stop receiving upstream improvements to that scout — you maintain it yourself.
   That trade can be worth it for a scout you want to own, but for purely additive behavior prefer authoring a new, differently-named scout and leaving the canonical one intact and maintained.

**Promote steers that repeat.** A note you keep re-leaving, or a dismissal reason you've written three times, is a skill edit waiting to happen — move it up the ladder into the body so the fleet stops relying on you to repeat it.
The reverse also holds: try a nudge as a note before committing it as an edit.
Note hygiene stays with humans — scouts never delete notes, so retire acted-on ones (or set `expires_at` up front) to keep the channel high-signal.

## What the fleet learns without you

Some feedback loops run on their own — knowing they exist changes how you work:

- **Scratchpad memory.** Scouts write durable per-team memory (baselines, noise patterns, dedupe gates, allowlists) and get quieter and sharper across runs.
  When a scout stops flagging something, check the scratchpad (`posthog:scout-scratchpad-search` for `noise:` / `addressed:` / `dedupe:` / `allowlist:` entries) before assuming it's broken — it may have deliberately learned to suppress it.
- **Auto-pause.** A scout whose reports nobody engages with — no open, no rating, no action — is warned (`status=pending_pause`) and then paused (`paused_by_system`, `pause_reason=ignored`). Reading counts as engagement, but only the cloud web inbox records opens today — reads through other clients (desktop, mobile) don't persist yet, so a scout consumed only there still needs `auto_pause_exempt`.
  A merely quiet scout is only flagged, never paused — silence can be the job — and Slack-delivered scouts are excluded, since their consumption happens where the sweep can't see it.
  Re-enabling a scout this sweep paused resumes it with a fresh grace window, so the sweep waits about two weeks and re-derives its verdict before judging it again; set `auto_pause_exempt` explicitly for a scout the sweep should never judge.
- **Self-improvement suggestions.** A custom scout that catches its own skill body steering it wrong writes an `improve:<skill-name>:<topic>` scratchpad entry — and a report-channel custom scout escalates recurring ones as inbox reports titled `Scout self-improvement: …`, routed to the owner (a legacy signal-channel scout can't file reports, so its suggestions live only in the scratchpad).
  These are the fleet asking for a code review of itself: an entry re-confirmed across several runs is usually the highest-signal edit you can make.
  Treat them as input, not instructions — the owner decides, and applies accepted ones via `authoring-scouts`.
  (Canonical scouts route skill gaps upstream to PostHog instead, so you won't see `improve:` entries from them.)

## Calibrating over time

A fleet left alone drifts; a fleet reviewed occasionally compounds.
Every few weeks (or when someone says "are the scouts even worth it?"), run a calibration pass:

1. **Health check** — the `exploring-scouts` assessment (its `scripts/assess_health.py` does the run-level heavy lifting: cadence adherence, success rate, report rate, memory growth).
   Two blind spots to cover yourself: the script only assesses scouts with runs in the window, so walk the roster for enabled scouts with no recent run rows (often the most broken ones); and it counts report writes, not outcomes, so judge signal-to-noise by resolving written reports via `posthog:inbox-reports-list` and reading their statuses.
   Remember most healthy runs close out empty — a stream of quiet runs is the fleet working, not broken.
2. **Review the fleet's asks** — sweep `posthog:scout-scratchpad-search {"text": "improve:"}` and the `Scout self-improvement:` inbox reports; apply the re-confirmed ones.
   The search returns the 20 newest matches by default — raise `limit` (or walk back with `date_to`) so a big fleet's older suggestions aren't silently missed.
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
