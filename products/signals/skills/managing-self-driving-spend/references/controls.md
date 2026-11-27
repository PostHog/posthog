# Spend controls

Read the current value before you change anything, and read it back after.
Where no tool exists, give the user the setting name. Most settings are in the Inbox settings, in the Self-driving section.
When no tool can read a setting, you do not know its current value. Say so instead of assuming the default.

## How spend builds up

Knowing where money is spent tells you which control can reduce it.

- **Signals.** Each signal a source sends costs a little to process and group. When signals form a report, researching that report costs more, and that cost lands on its signals.
  So a source that sends many signals costs money even when few of them become reports, and a source whose reports get researched costs more per report.
- **Scout runs.** Each run costs money whether it finds something or not.
  Scout spend grows with the number of runs, so a scout's schedule matters more than what it finds.
  A pre-check can skip a scheduled run before it costs anything.
  Runs that a person, a workflow, or a report check starts cost the same, and the schedule does not control them (see [Runs a schedule does not control](#runs-a-schedule-does-not-control)).
- **Automatic pull requests.** An implementation run for an actionable report costs money. Its finalized usage appears in the monthly tool's `implementation_credits` and in `system.signal_spend`.
  A fix that a person starts from a report is metered as PostHog AI, so it is not in these numbers.

There are two kinds of control:

- **Volume controls** cut how much work happens: turning a source or scout off, running a scout less often, skipping its empty runs with a pre-check, starting it from a workflow instead of the clock, narrowing a source to some of its parts, and the limits. Their savings can be estimated from past spend, except for source steering, which you must measure after two weeks. For a pre-check, past spend gives only an upper limit.
- **Focus controls** change what the agents spend effort on: project steering instructions. Their savings cannot be estimated in advance. Check them again after two weeks.

## Limits

| Control            | How it works                                                                                                                                                                                                                              | How to change it                                                             | What the user loses                                                                       |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Spend limit        | A monthly cap on Self-driving spend, on the `inbox` row. When spend reaches it, new signals are dropped, scout runs are skipped, and research pauses until the next billing period. It caps the bill but does not make spend more useful. | Read with `posthog:billing-limits-get`. Set it on the billing page. No tool. | Signals that arrive after the limit are lost for good. They do not come back next period. |
| Daily report limit | Caps how many new reports become visible each day, in the project timezone. When the cap is reached, new signals are dropped, scout runs are skipped, and research pauses until midnight. It only saves money on days with spikes.        | "Daily report limit" setting. No tool.                                       | Signals that arrive after the cap are lost for good. They are not held for the next day.  |

Both limits drop signals rather than queue them. When you recommend one, say that issues found after it is reached never reach the inbox.

`posthog:scout-metadata-get` shows the scout run limits the project runs under: `max_runs_per_tick`, `max_runs_per_day` (null means no daily cap), `runs_today`, and `runs_remaining_today`.
PostHog sets these limits, and the user cannot change them. Use them to check whether a proposed schedule fits, not as a control.

## Trials

An organization can claim one Self-driving trial, in one project.
A trial grants an allowance and a report limit, and ends when either one runs out. The standard trial is $10 and 5 reports, but billing can set other values.
The trial state shows in the Inbox. No tool reads it.

- Receipts paid by the trial are exempt, so trial spend shows in `exempt_credits` and not in billed spend.
- While a trial runs, savings in dollars matter less than making the allowance and the report limit last. Say so, and rank by what each change does to those.

## Sources

| Control           | How it works                                                                                                                                                              | How to change it                                                                                                                                                     | What the user loses                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Turn off a source | Stops new signals from that source. Reports that already exist stay in the inbox. Each signal type has its own config to turn off.                                        | `posthog:inbox-source-configs-partial-update` with `enabled: false`                                                                                                  | Everything that source would find                            |
| Source steering   | Plain-language rules on what to skip in one source. A model checks each record against them and drops matches before they become signals. It applies to new records only. | `posthog:inbox-source-configs-partial-update` with `config_set.steering`, up to 2,000 characters. Read the current text with `posthog:inbox-source-configs-retrieve` | Records the rules exclude. A broad rule can hide real issues |

Prefer `config_set` and `config_remove` to `config` on every source update, because `config` replaces the whole object.

These sources read `steering`: error tracking, health checks, product analytics alerts, support tickets, and most data warehouse imports, such as GitHub, Linear, Zendesk, and pganalyze.
Other sources store the text but do not read it, including Replay Vision, LLM analytics, and Search Console.
When the check is unavailable, it keeps the record. New rules do not remove signals that already exist.

Before you turn off a whole source, check whether one of its parts drives the spend. These controls narrow a source without turning it off:

| Source                         | Control                     | How it works                                                                                                                                                                                                        | How to change it                                                                                                                                                                                                   | What the user loses                                                                    |
| ------------------------------ | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| Error tracking                 | Signal types                | New issues, reopened issues, and spiking issues are three separate signal types, each with its own config.                                                                                                          | `posthog:inbox-source-configs-partial-update` on the `issue_created`, `issue_reopened`, or `issue_spiking` config                                                                                                  | Turning off new issues means an issue reaches the inbox only when it spikes or reopens |
| Session replay (Replay Vision) | Scanners                    | Each scanner watches recordings for one thing. `emits_signals` sends one signal per matching recording to the inbox. `sampling_rate` sets the share of recordings it scans. `enabled` stops the scanner completely. | `posthog:vision-scanners-update`. Turn off `emits_signals` to keep the scanner's observations in Replay Vision without sending them to the inbox.                                                                  | Findings from the scanners you turn down                                               |
| LLM analytics                  | Evaluation reports          | Each evaluation report runs on a schedule and can send a signal when it finds a problem.                                                                                                                            | `posthog:llma-evaluation-report-update` with `enabled`, `frequency`, or `daily_run_cap`                                                                                                                            | Also changes that report's email and Slack delivery                                    |
| Product analytics              | Anomaly alert investigation | When an alert fires, an agent can investigate it and send the result to the inbox.                                                                                                                                  | Per alert: `alert-update` with `investigation_agent_enabled: false`, or `investigation_inconclusive_action: "suppress"` to hold back unclear results. For all alerts, turn off the `anomaly_investigation` source. | Fewer anomaly reports                                                                  |
| Product analytics              | Alert scope                 | `alert_scope` selects which firing alerts become signals: `investigated_only` (default), `all_firing_alerts`, or `off`. `alert_allow_patterns` and `alert_block_patterns` filter by alert or insight name.          | `posthog:inbox-source-configs-partial-update` on the `anomaly_investigation` config with `config_set`                                                                                                              | Alerts the scope or patterns exclude. Alert checks and notifications still run         |
| Linear                         | Teams                       | Only issues from the chosen Linear teams become signals.                                                                                                                                                            | `posthog:inbox-source-configs-partial-update` with `config_set.linear_team_ids`                                                                                                                                    | Issues from other teams                                                                |

The `alert_firing` signal type has no config row of its own. The `anomaly_investigation` row controls it: its `enabled` flag, `alert_scope`, and patterns all apply.
The `signals_check` source comes from report monitoring and has no config row.

Other sources, such as support tickets and pganalyze, have no setting that selects a fixed part of the source, so use source steering to describe the records to skip.
Search Console has neither, so the choice is to keep it or turn it off.

## Scouts

| Control                 | How it works                                                                                                                           | How to change it                                                                                                      | What the user loses                                             |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| Pause a scout           | Stops its scheduled runs and its workflow runs. Its past reports stay.                                                                 | `posthog:scout-config-update` with `enabled: false`                                                                   | Everything that scout would find                                |
| Run a scout less often  | Spend falls in proportion to runs. Going from hourly to every 6 hours cuts that scout's spend by about five sixths.                    | `posthog:scout-config-update` with a larger `run_interval_minutes`, or a cron schedule                                | Findings arrive later                                           |
| Add a pre-check         | A HogQL query runs before each scheduled run. When it finds nothing new, the run does not start, so there is no sandbox or model call. | Test with `posthog:scout-config-precheck-test`, then save with `posthog:scout-config-update` and `precheck_query`     | A query that is too strict hides real activity from the scout   |
| Trigger from a workflow | A workflow's "Run scout" step starts a run when an event fires. Spend then follows the events, not the clock.                          | Add the step to a workflow, then slow the scout's schedule to a backstop. See [Workflow triggers](#workflow-triggers) | Anything the event does not announce waits for the backstop run |

When `run_cron_schedule` is set, it decides when the scout runs, not `run_interval_minutes`. Read the schedule from the one that applies, and change that one.

### Scout status

Read `status` and `pause_reason` in `posthog:scout-config-list` before you recommend anything for a scout.
The system pauses and warns scouts on its own, and a recommendation that repeats what it did saves nothing.

- `active`: runs on its schedule.
- `pending_pause`: still runs, but the system warned it. With `pause_reason` `ignored`, nobody acted on its reports, and the system pauses it after a grace period unless someone does. With `no_output`, it produced nothing judgeable. That reason only warns, because a quiet scout can be doing its job.
- `paused_by_system`: the system stopped it. `ignored` is the inactivity pause, `repeated_failures` is the failure breaker, `retired` means PostHog retired the scout, and `background_removed` means PostHog stopped running it for the project. A scout paused for `repeated_failures` still runs one probe from time to time, which can cost a little.
- `paused_by_user`: a person switched it off. Nothing runs it on a schedule.

For a scout that is `pending_pause` with `ignored`, say that it will pause on its own and its spend will stop, and recommend nothing more unless the user wants it to stop sooner.
For a paused scout, explain its past spend and recommend no control.

### Pre-checks

A pre-check suits a scout that watches data a query can read, such as new events or tickets.
Findings do not arrive later, because the next run that starts still sees everything since the last run that started.
It suits a scout poorly when a query cannot tell whether a run would matter, such as a sweep through a codebase.

- `precheck_query_source` in `posthog:scout-config-retrieve` shows the current state: `config`, `skill_default`, or `off`. Only `off` means no pre-check runs.
- Most scouts that PostHog ships come with a default pre-check, so `skill_default` is the normal state. A `precheck_query` saved on the config replaces the default, and does not add to it.
  `skill_default` with a null `effective_precheck_query` means a check in code runs instead of a query.
- A scout that PostHog ships can show `off` when it has no default, when its default is not rolled out to the project yet, or when `precheck_disabled` is true. A team's own scout has no default.
- A pre-check gates scheduled runs only. Manual, report check, Monitoring, and workflow runs always start. A scheduled run that carries queued workflow fires also skips the pre-check.
- A query that fails starts the run, so a broken pre-check saves nothing.
- The dry run reads as you, and a scheduled check reads as the scout's acting user. A query that passes the dry run can still fail on schedule, so read `last_precheck_outcome` after the next scheduled tick. It holds only the latest result.
- Add a backstop when the scout should still run from time to time.

After you save a pre-check, read `last_precheck_outcome` after the next scheduled tick, and compare the scout's runs, spend, and reports after one week.
Many `skip` outcomes with the same reports as before mean it works.
No reports at all does not prove that the query is too strict, because a quiet source, or a scout that mostly edits reports, gives the same result with a correct query.
Before you loosen the query, check two things: whether the data the scout watches had activity that the query did not see in the week, and whether the scout's runs still edit reports (`edited_report_ids`).

The `authoring-scouts` skill has the query rules, the placeholders, and a backstop example in `references/scheduled-precheck.md`. Read it before you write a query.

### Schedules

Each run costs about the same, so the schedule sets most of a scout's spend.

- `run_interval_minutes` takes 30 to 43200 (30 days). The default is 1440, one run a day.
- `run_cron_schedule` is a five-field cron expression in the project's timezone, with runs at least 30 minutes apart. Set it to null to return to the interval.
- A cron schedule can drop the hours when nobody acts on a report. `0 9 * * 1-5` runs once each weekday morning, which is 5 runs a week where an hourly scout makes 168.
- Match the schedule to how fast someone acts on a finding. A scout whose reports are read once a day gains nothing from hourly runs.
- A slower schedule delays findings. A pre-check does not. When a query can tell that nothing is new, use the pre-check first, and slow the schedule only for what remains.

### Workflow triggers

Use a workflow trigger when a known event says there is work, for example a new GitHub issue, a merged pull request, a deploy, or an alert that fires.
The scout then runs when the event arrives, and its schedule only has to catch what the event misses.

1. Build a workflow whose trigger is the event, with a "Run scout" step that names the scout. The `building-workflows` skill has the steps.
2. Slow the scout's schedule to a backstop with `posthog:scout-config-update`, for example once a day or once a week.
   Do not pause the scout. A paused scout rejects workflow triggers.
3. After a week, compare the scout's workflow runs and scheduled runs with the week before, using "Spend by scout and trigger" in [queries-spend.md](queries-spend.md).

What to know before you recommend it:

- A workflow run always starts. The pre-check does not gate it, so the workflow's trigger filters are the only gate. A trigger on a frequent event can cost more than the schedule it replaced.
- A scout starts at most one workflow run every 30 minutes, the coordinator's tick. A fire that arrives while the scout is busy, inside those 30 minutes or while one of its runs is live, waits in a queue of up to 20 per scout, and the oldest drops first when the queue is full.
  The coordinator drains the queue on its next tick: the scout's next scheduled run takes the waiting fires, or one extra workflow run starts for them. Either way, a burst of fires costs about one run per tick, not one run per fire.
  When the step sets `when_busy` to `skip`, a busy scout drops the fire instead of queueing it.
- The spend limit and the daily report limit stop workflow runs too.

The `authoring-scouts` skill covers the step's note, the queue of waiting triggers, and what the scout's skill must say, under "Workflow-triggered runs". Read it before you set one up.

### Which control to choose

| Situation                                                     | Control                                |
| ------------------------------------------------------------- | -------------------------------------- |
| The system already paused or warned the scout                 | None. Say what the system did          |
| A query can tell that nothing is new                          | Pre-check                              |
| Findings are read on a fixed rhythm, such as a morning review | Cron schedule                          |
| A specific event says there is work                           | Workflow trigger, with a slow backstop |
| Nobody reads the reports                                      | Pause                                  |

### Runs a schedule does not control

Every scout run has a receipt of kind `scout_run`, whatever started it.
Its trigger is in `system.scout_runs.metadata.triggered_by`, and an absent value means the schedule.

| Trigger      | What starts it                                                    | What reduces it                                                      |
| ------------ | ----------------------------------------------------------------- | -------------------------------------------------------------------- |
| `schedule`   | The coordinator, on the scout's interval or cron                  | A pre-check, a slower schedule, or a pause                           |
| `workflow`   | A workflow's "Run scout" step                                     | The workflow's trigger filters, or turning off the workflow's step   |
| `manual`     | A person who clicks "Run now" or calls the run endpoint           | Running it less. A pause does not stop a person's manual run         |
| `check`      | A report check, which asks a scout to confirm that a fix held     | Cancelling the check. Most checks run on the report validation scout |
| `monitoring` | A check that verifies a report in Monitoring after its fix merged | Cancelling the check, which only a person can do                     |
| `onboarding` | The one-time first-report investigation when Self-driving starts  | Nothing. It runs once                                                |

Runs of the report validation scout and the health checks scout, as PostHog ships them, are exempt from billing whatever started them.
Neither a schedule nor a pre-check changes the off-schedule runs. When they hold much of a scout's spend, say so, and name what starts them instead of recommending a schedule change.

### Scout report actions

A scout can be granted report actions, such as fixing a failing check or resolving merge conflicts on a report's pull request.
Each action starts a separate agent run as the scout's acting user. That run is metered as PostHog AI, like a fix a person starts, so it has no Self-driving receipt and is not in these numbers.

- `report_actions` on the scout config lists the granted actions, and is empty by default.
- `max_report_actions_per_day` caps how many actions the scout starts in a rolling 24 hours, across all its runs.
- Read both with `posthog:scout-config-retrieve`. Change them with `posthog:scout-config-update`. Only the scout's acting user can add an action, and a project admin can only remove one.

When the user asks why their PostHog AI usage grew with their scouts, check these. Do not count them as Self-driving savings.
This is not the `scout_triggered_implementation` kind: that kind is the automatic pull request for a report that a scout wrote, and the controls under [Automatic pull requests](#automatic-pull-requests) govern it.

## Project steering instructions

Project steering instructions tell the agents what to focus on and what to skip.
There are three, and each applies to the whole project:

- `scout_instructions`: added to every scout run.
- `research_instructions`: used when a report is researched.
- `implementation_instructions`: used when a pull request is written.

They change focus, not volume. Signals still arrive and are processed, so do not promise a dollar saving.
To stop records from one source before they become signals, use source steering instead.
Where a source does not read `steering`, name it in the research instructions, for example "Skip scanner findings about the settings page."

Read the current text with `posthog:inbox-steering-instructions-get`, then send the full new text with `posthog:inbox-steering-instructions-update`.

## Automatic pull requests

| Control                     | How it works                                                                                                                                | How to change it                                                                                                                 | What the user loses                      |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| PR generation               | Whether actionable reports open a pull request automatically                                                                                | "PR generation" setting. No tool.                                                                                                | Fewer fixes arrive ready to review       |
| Priority threshold          | The lowest report priority that opens a pull request automatically (P0 is highest), for the whole project                                   | "Priority threshold" setting. No tool.                                                                                           | Lower-priority fixes need a manual start |
| Personal priority threshold | `autostart_priority` replaces the project threshold for the reports that suggest one person as reviewer. Null follows the project threshold | `posthog:inbox-my-settings-get`, then `posthog:inbox-my-settings-update`. Both act on the person who calls them, and nobody else | That person's lower-priority fixes       |

Automatic pull requests have two receipt kinds: `scout_triggered_implementation` for a report that a scout wrote, and `reviewer_triggered_implementation` for the rest. The same settings govern both.
A personal threshold changes only the caller's own reports. To lower spend for the whole project, change the project threshold, or ask each reviewer to set their own.

Use implementation receipts for historical cost. Estimate future savings only for the reports the proposed control would exclude, separating exempt credits and acknowledging that future implementation costs vary.
To judge them, compare pull requests linked and merged with "Pull requests linked and merged" in [queries-controls.md](queries-controls.md).
