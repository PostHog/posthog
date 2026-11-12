# Spend controls

Read the current value before you change anything, and read it back after.
Where no tool exists, give the user the setting name. Most settings are in the Inbox settings, in the Self-driving section.
When no tool can read a setting, you do not know its current value. Say so instead of assuming the default.

## How spend builds up

Knowing where money is spent tells you which control can reduce it.

- **Signals.** Each signal a source sends costs a little to process and group. When signals form a report, researching that report costs more, and that cost lands on its signals.
  So a source that sends many signals costs money even when few of them become reports, and a source whose reports get researched costs more per report.
- **Scout runs.** Each scheduled run costs money whether it finds something or not.
  Scout spend grows with the number of runs, so a scout's schedule matters more than what it finds.
  A pre-check can skip a scheduled run before it costs anything.
- **Automatic pull requests.** An implementation run for an actionable report costs money. Its finalized usage appears in the monthly tool's `implementation_credits` and in `system.signal_spend`.
  A fix that a person starts from a report is metered as PostHog AI, so it is not in these numbers.

There are two kinds of control:

- **Volume controls** cut how much work happens: turning a source or scout off, running a scout less often, skipping its empty runs with a pre-check, narrowing a source to some of its parts, and the limits. Their savings can be estimated from past spend, except for source steering, which you must measure after two weeks. For a pre-check, past spend gives only an upper limit.
- **Focus controls** change what the agents spend effort on: project steering instructions. Their savings cannot be estimated in advance. Check them again after two weeks.

## Limits

| Control            | How it works                                                                                                                                                                                                                                        | How to change it                                                             | What the user loses                                                                       |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Spend limit        | A monthly cap on Self-driving spend, on the `inbox` row. When spend reaches it, new signals are dropped, scheduled scout runs are skipped, and research pauses until the next billing period. It caps the bill but does not make spend more useful. | Read with `posthog:billing-limits-get`. Set it on the billing page. No tool. | Signals that arrive after the limit are lost for good. They do not come back next period. |
| Daily report limit | Caps how many new reports become visible each day, in the project timezone. When the cap is reached, new signals are dropped, scheduled scout runs are skipped, and research pauses until midnight. It only saves money on days with spikes.        | "Daily report limit" setting. No tool.                                       | Signals that arrive after the cap are lost for good. They are not held for the next day.  |

Both limits drop signals rather than queue them. When you recommend one, say that issues found after it is reached never reach the inbox.

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
| Pause a scout           | Stops its scheduled runs. Its past reports stay.                                                                                       | `posthog:scout-config-update` with `enabled: false`                                                                   | Everything that scout would find                                |
| Run a scout less often  | Spend falls in proportion to runs. Going from hourly to every 6 hours cuts that scout's spend by about five sixths.                    | `posthog:scout-config-update` with a larger `run_interval_minutes`, or a cron schedule                                | Findings arrive later                                           |
| Add a pre-check         | A HogQL query runs before each scheduled run. When it finds nothing new, the run does not start, so there is no sandbox or model call. | Test with `posthog:scout-config-precheck-test`, then save with `posthog:scout-config-update` and `precheck_query`     | A query that is too strict hides real activity from the scout   |
| Trigger from a workflow | A workflow's "Run scout" step starts a run when an event fires. Spend then follows the events, not the clock.                          | Add the step to a workflow, then slow the scout's schedule to a backstop. See [Workflow triggers](#workflow-triggers) | Anything the event does not announce waits for the backstop run |

When `run_cron_schedule` is set, it decides when the scout runs, not `run_interval_minutes`. Read the schedule from the one that applies, and change that one.

### Pre-checks

A pre-check suits a scout that watches data a query can read, such as new events or tickets.
Findings do not arrive later, because the next run that starts still sees everything since the last run that started.
It suits a scout poorly when a query cannot tell whether a run would matter, such as a sweep through a codebase.

- `precheck_query_source` in `posthog:scout-config-list` shows the current state: `config`, `skill_default`, or `off`. Only `off` means no pre-check runs.
- A pre-check gates scheduled runs only. Manual and workflow runs always start.
- A query that fails starts the run, so a broken pre-check saves nothing.
- The dry run reads as you, and a scheduled check reads as the scout's acting user. A query that passes the dry run can still fail on schedule, so read `last_precheck_outcome` after the next scheduled tick. It holds only the latest result.
- Add a backstop when the scout should still run from time to time.

How to write one:

- The query is one HogQL `SELECT`. It stops after 10 seconds and reads at most 50 rows.
- No rows, or one row with one false value such as a zero `count()`, skips the run. Any other result starts it.
  A row with two columns never skips, so use `GROUP BY` or `HAVING` when you select more than one column.
- `{since}` is the start of the last run that started, `{now}` is the current time, and `{interval_minutes}` is the gap between two scheduled runs.
- Test the thing the scout reads, not a proxy for it. A scout that triages new exceptions tests for new `$exception` events, not for any event.

This query runs the scout when new exceptions arrived, and at least once a week:

```sql
SELECT count() > 0 OR {since} < {now} - INTERVAL 7 DAY
FROM events
WHERE event = '$exception' AND timestamp > {since}
```

After you save a pre-check, read `last_precheck_outcome` after the next scheduled tick, and compare the scout's runs and spend after one week.
Many `skip` outcomes with the same number of reports mean it works. No reports at all means the query is too strict.

The `authoring-scouts` skill has the full query rules in `references/scheduled-precheck.md`. Read it before you write a query.

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
   Write the step's note from identifiers, for example `Issue #{event.properties.issue_number}`, so the run handles that subject first.
2. Slow the scout's schedule to a backstop with `posthog:scout-config-update`, for example once a day or once a week.
   Do not pause the scout. A paused scout rejects workflow triggers.
3. After a week, compare the scout's runs and spend with the week before, using "Spend by scout" in [queries-spend.md](queries-spend.md).

What to know before you recommend it:

- A workflow run always starts. The pre-check does not gate it, so the workflow's trigger filters are the only gate. A trigger on a frequent event can cost more than the schedule it replaced.
- A scout starts at most one workflow run every 30 minutes. Triggers that arrive sooner, or during a run, wait and are handled together by the next run. At most 20 wait.
- A run with a note handles the named subject and skips the scout's routine unless the scout's skill says otherwise. Keep a scheduled backstop so the routine still runs.
- The spend limit stops workflow runs too.
- The scout's skill may need a section for workflow-triggered runs. The `authoring-scouts` skill covers it under "Workflow-triggered runs".

Which control to choose:

| Situation                                                     | Control                                |
| ------------------------------------------------------------- | -------------------------------------- |
| A query can tell that nothing is new                          | Pre-check                              |
| Findings are read on a fixed rhythm, such as a morning review | Cron schedule                          |
| A specific event says there is work                           | Workflow trigger, with a slow backstop |
| Nobody reads the reports                                      | Pause                                  |

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

| Control            | How it works                                                                                                 | How to change it                                                                  | What the user loses                      |
| ------------------ | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- | ---------------------------------------- |
| PR generation      | Whether actionable reports open a pull request automatically                                                 | "PR generation" setting. No tool.                                                 | Fewer fixes arrive ready to review       |
| Priority threshold | The lowest report priority that opens a pull request automatically (P0 is highest). Users can set their own. | "Priority threshold" setting, for the project or under "Your overrides". No tool. | Lower-priority fixes need a manual start |

Use implementation receipts for historical cost. Estimate future savings only for the reports the proposed control would exclude, separating exempt credits and acknowledging that future implementation costs vary.
To judge them, compare pull requests linked and merged with "Pull requests linked and merged" in [queries-controls.md](queries-controls.md).
