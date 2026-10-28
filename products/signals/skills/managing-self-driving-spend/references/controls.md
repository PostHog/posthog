# Spend controls

Read the current value before you change anything, and read it back after.
Where no tool exists, give the user the setting name. Most settings are in the Inbox settings, in the Self-driving section.

## How spend builds up

Knowing where money is spent tells you which control can reduce it.

- **Signals.** Each signal a source sends costs a little to process and group. When signals form a report, researching that report costs more, and that cost lands on its signals.
  So a source that sends many signals costs money even when few of them become reports, and a source whose reports get researched costs more per report.
- **Scout runs.** Each scheduled run costs money whether it finds something or not.
  Scout spend grows with the number of runs, so a scout's schedule matters more than what it finds.
- **Automatic pull requests.** An implementation run for an actionable report costs money. This spend is not visible yet.

There are two kinds of control:

- **Volume controls** cut how much work happens: turning a source or scout off, running a scout less often, narrowing a source to some of its parts, and the limits. Their savings can be estimated from past spend.
- **Focus controls** change what the agents spend effort on: steering instructions. Their savings cannot be estimated in advance. Check them again after two weeks.

## Limits

| Control            | How it works                                                                                                                                                                                        | How to change it                                                     | What the user loses                              |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------ |
| Spend limit        | A monthly cap on Self-driving spend. When spend reaches it, Self-driving pauses until the next billing period. It caps the bill but does not make spend more useful.                                | Read with `billing-limits-get`. Set it on the billing page. No tool. | Useful work stops for the rest of the period     |
| Daily report limit | Caps how many new reports become visible each day, in the project timezone. When the cap is reached, ingestion, scouts, and research pause until midnight. It only saves money on days with spikes. | "Daily report limit" setting. No tool.                               | Issues found late in the day wait until tomorrow |

## Sources

| Control           | How it works                                                                                                                       | How to change it                                            | What the user loses               |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | --------------------------------- |
| Turn off a source | Stops new signals from that source. Reports that already exist stay in the inbox. Each signal type has its own config to turn off. | `inbox-source-configs-partial-update` with `enabled: false` | Everything that source would find |

Before you turn off a whole source, check whether one of its parts drives the spend. These controls narrow a source without turning it off:

| Source                         | Control                     | How it works                                                                                                                                                                                                        | How to change it                                                                                                                                                                                                   | What the user loses                                                                    |
| ------------------------------ | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| Error tracking                 | Signal types                | New issues, reopened issues, and spiking issues are three separate signal types, each with its own config.                                                                                                          | `inbox-source-configs-partial-update` on the `issue_created`, `issue_reopened`, or `issue_spiking` config                                                                                                          | Turning off new issues means an issue reaches the inbox only when it spikes or reopens |
| Session replay (Replay Vision) | Scanners                    | Each scanner watches recordings for one thing. `emits_signals` sends one signal per matching recording to the inbox. `sampling_rate` sets the share of recordings it scans. `enabled` stops the scanner completely. | `vision-scanners-update`. Turn off `emits_signals` to keep the scanner's observations in Replay Vision without sending them to the inbox.                                                                          | Findings from the scanners you turn down                                               |
| LLM analytics                  | Evaluation reports          | Each evaluation report runs on a schedule and can send a signal when it finds a problem.                                                                                                                            | `llma-evaluation-report-update` with `enabled`, `frequency`, or `daily_run_cap`                                                                                                                                    | Also changes that report's email and Slack delivery                                    |
| Product analytics              | Anomaly alert investigation | When an alert fires, an agent can investigate it and send the result to the inbox.                                                                                                                                  | Per alert: `alert-update` with `investigation_agent_enabled: false`, or `investigation_inconclusive_action: "suppress"` to hold back unclear results. For all alerts, turn off the `anomaly_investigation` source. | Fewer anomaly reports                                                                  |
| Linear                         | Teams                       | Only issues from the chosen Linear teams become signals.                                                                                                                                                            | `inbox-source-configs-partial-update` with `config.linear_team_ids`                                                                                                                                                | Issues from other teams                                                                |

Other sources, such as support tickets, pganalyze, and Search Console, have no setting that selects part of the source.
For those, the choice is to keep the source, turn it off, or steer it.

## Scouts

| Control                | How it works                                                                                                        | How to change it                                                               | What the user loses              |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | -------------------------------- |
| Pause a scout          | Stops its scheduled runs. Its past reports stay.                                                                    | `scout-config-update` with `enabled: false`                                    | Everything that scout would find |
| Run a scout less often | Spend falls in proportion to runs. Going from hourly to every 6 hours cuts that scout's spend by about five sixths. | `scout-config-update` with a larger `run_interval_minutes`, or a cron schedule | Findings arrive later            |

## Steering instructions

Steering instructions tell the agents what to focus on and what to skip.
There are three, and each applies to the whole project:

- `scout_instructions`: added to every scout run.
- `research_instructions`: used when a report is researched.
- `implementation_instructions`: used when a pull request is written.

There is no prompt for a single source.
To steer one source, name it in the research instructions, for example "Skip support tickets that are low-priority questions about billing."
Steering changes focus, not volume. Signals still arrive and are processed, so do not promise a dollar saving.

Read the current text with `inbox-steering-instructions-get`, then send the full new text with `inbox-steering-instructions-update`.

## Automatic pull requests

| Control            | How it works                                                                                                 | How to change it                                                                  | What the user loses                      |
| ------------------ | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- | ---------------------------------------- |
| PR generation      | Whether actionable reports open a pull request automatically                                                 | "PR generation" setting. No tool.                                                 | Fewer fixes arrive ready to review       |
| Priority threshold | The lowest report priority that opens a pull request automatically (P0 is highest). Users can set their own. | "Priority threshold" setting, for the project or under "Your overrides". No tool. | Lower-priority fixes need a manual start |

The spend on these runs is not visible yet, so say that the saving is not measured.
To judge them, compare pull requests opened with pull requests merged per source in the `system.inbox_report_artefacts` and `system.inbox_report_pull_requests` tables.
