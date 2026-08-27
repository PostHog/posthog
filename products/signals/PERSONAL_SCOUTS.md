# Personal scouts

Status: idea. None of this is built. The doc exists so the parts land in a compatible order rather than being retrofitted onto a team-shaped scout.

Origin: [Slack thread](https://posthog.slack.com/archives/C09SK2PAGKF/p1787830287435859?thread_ts=1787830287.435859&cid=C09SK2PAGKF).

## The idea

A scout today is a property of a project. One config row per `(team, skill_name)`, one shared inbox, one fleet everyone on the team sees. Every report is addressed to the team, and reaching a specific person is a hint (`suggested_reviewers`) layered on a shared surface.

A **personal scout** inverts that. It belongs to one person, watches something only they care about, and delivers only to them. The team never sees it, and its noise costs nobody else attention.

Two consequences make this worth building rather than approximating with tags and reviewer routing:

1. **The noise budget stops being shared.** A team scout must clear a high evidence bar, because a weak finding spends everyone's attention. A personal scout only has to be worth its owner's time, so it can watch far pettier things: my own dropped follow-ups, my PRs going stale, the one number I check every Monday.
2. **The fleet gets large.** Once a scout is cheap to justify, one person plausibly wants tens of them. At that scale the scout replaces the artifact people build today — a dashboard they have to remember to open — with something that comes to them. That is the ambition worth designing for: scouts as a primary way a person consumes PostHog, not a sidecar to insights and dashboards.

Whether that ends as many narrow scouts or one wide "watch my stuff" scout is open. See [Open questions](#open-questions).

## What already exists to build on

- `SignalScoutConfig.created_by` records who made a scout. Attribution exists; ownership semantics do not.
- Slack delivery can target people directly. `output_destinations.slack.users` (see `scout_harness/slack_delivery.py`) sends per-recipient DMs, so a scout can already reach one person without a channel standing in the way.
- `tags` is the nearest thing to a per-person fleet filter today.
- Per-scout scheduling (`run_interval_minutes`, `run_cron_schedule`) already expresses a weekly personal digest.
- Scratchpad memory, the dedupe conventions, and `SignalScoutNote` give a scout private continuity and a steer channel that needs no code change.
- `structured_output_schema` lets a scout record a metric per run, which covers the "a number I want tracked, not a report I want read" half of the use case.
- The per-team skills store lets a scout body be authored without shipping repo code. Without it, bespoke scouts per person would not be possible at all.

## What is missing

1. **Ownership on the config.** `created_by` is attribution, and nothing reads it for scheduling, visibility, or budget. A personal scout needs an owner the system honors.
2. **Somewhere private for a report to land.** `SignalReport` is team-scoped and the inbox shows a team its reports. A personal scout's finding has no private destination. Either it never enters the inbox (DM-only delivery) or the inbox grows a per-user scope. **Decide this first** — it constrains every other part.
3. **The `(team, skill_name)` uniqueness constraint.** `unique_scout_config_per_team_skill` means two people cannot run the same skill with different scopes on one project, and fifty personal scouts means fifty distinct skill names sitting in the team's shared skills store. Either the constraint takes the owner into account, or personal scouts get their own per-user skill namespace.
4. **Budget.** Runs are gated per team (`quota.py`, `daily_limit.py`, `SignalTeamConfig.max_reports_per_day`). One enthusiast's fifty scouts spend the whole team's allowance. Per-user attribution of spend, and probably a per-user allowance, is the fair version.
5. **The inactivity sweep's assumptions.** `scout_harness/inactivity.py` pauses a scout nobody engages with, judged from inbox engagement. A DM-only personal scout generates no inbox engagement at all, so it would be swept as ignored. It needs a liveness signal of its own.
6. **Fleet UX at N=50.** The roster, tag filter, and config UI are built for a couple of dozen team scouts. A personal fleet an order of magnitude larger needs grouping, bulk pause and resume, and per-scout cost visible at a glance.
7. **Per-user access to what the scout watches.** The most-wanted personal scouts watch their owner's own activity, much of it outside PostHog. That is a credential problem, not a project-data problem, and it runs against a deliberate current choice: `mcp_gateway_server_ids` mounts only team-shared grants precisely so a run behaves the same no matter who created the scout. A personal scout wants the opposite. Inverting it needs its own answers on consent, revocation, and what happens to the scout when its owner leaves the org.

## A rough order

A suggestion, not a commitment. Each step is useful on its own and none of them blocks on the ones after it.

1. Owner on the config, plus a "my scouts" view of the roster. Cheap, and everything else reads it.
2. Settle delivery: DM-only, or a per-user scope in the inbox. Point 2 above.
3. Namespace the skill, or relax the uniqueness constraint. Unblocks more than one personal scout on the same idea.
4. Attribute spend to the owner, then decide whether a per-user allowance is needed.
5. Teach the sweep about scouts with no inbox footprint.
6. Fleet UX for the large-N case.

## Open questions

- **Many scouts or one?** Fifty narrow scouts are individually easy to reason about, easy to pause, and easy to price, but fifty runs is fifty times the cost of one and the roster becomes its own maintenance job. One wide scout with a personal brief amortizes the run, but loses per-watch scheduling, per-watch pausing, and per-watch dedupe state. There is likely a middle shape (one scout, several watches, one run) that neither the config model nor the report contract expresses today.
- **Does a personal finding ever escalate?** If a scout notices something the team should know, is promoting it to the team inbox a manual action by the owner, or something the scout can do itself?
- **Does the owner see the run, or only the output?** Personal scouts invite pettier watches, which means more false starts, which raises the value of reading what the run actually did.
- **What does a personal scout cost, and who is told?** A person adding their thirtieth scout should be able to see what the previous twenty-nine spent.
- **Can a personal scout be shared or forked?** A good one is exactly the thing a teammate would want to copy.
