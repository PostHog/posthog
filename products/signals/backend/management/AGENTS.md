# Signal Pipeline Management Commands

Commands for emitting signals, tracking pipeline processing, and inspecting grouping results.
Use these to test grouping strategies against real signal data end-to-end.

For offline grouping and scout safety evaluations with mocked infrastructure, use the
[pytest suites](../../eval/AGENTS.md), which publish results to offline experiments.

## Full flow

Always clean up before re-ingesting to avoid stale data mixing with new results.

### From pre-processed signals (Signals format)

```bash
# 1. Clean up — removes all signal data, terminates Temporal workflows, and purges Kafka embedding topics
python manage.py cleanup_signals --team-id 1 --yes

# 2. Emit signals from a JSON file (example file)
python manage.py ingest_signals_json playground/signals-grouping-iterations/signals_mini.json --team-id 1

# 3. Wait for the pipeline to fully process all signals
#    Set --expected-signals to the number of signals in the file
python manage.py signal_pipeline_status --team-id 1 --wait --expected-signals 3 --poll-interval 10 --json

# 4. Inspect the grouping results
python manage.py list_signal_reports --team-id 1 --signals --json
```

## What happens during processing

1. Temporal grouping workflow receives signals and processes them sequentially
2. Each signal gets embedded, matched to an existing report or a new one via LLM
3. `SignalReport` rows are created/updated in Postgres
4. Signal embeddings land in ClickHouse `document_embeddings`
5. When a report's total weight reaches the threshold (default 1.0) and `signal_count >= signals_at_run`, a summary workflow runs:
   - default path: summarizes the group, then runs safety + actionability judges
   - feature-flagged path: runs safety first, selects repo, then agentic report research
6. Report reaches a terminal state:
   - `ready` — passed both judges, actionable by a coding agent
   - `pending_input` — needs human judgment before acting
   - `failed` — failed safety review (possible prompt injection)
   - `potential` (reset, weight zeroed) — deemed not actionable
7. On reaching `ready`, the summary workflow starts `signal-report-inbox-notification` to post the Slack inbox notification. If the report auto-started an implementation task, that workflow waits for the PR to open (bounded by `SIGNALS_INBOX_PR_NOTIFICATION_TIMEOUT_SECONDS`) so the card can show a "Review PR" button; if that task never opens a PR (fails, is cancelled, or the wait times out) no notification is sent. Reports with no auto-start task notify immediately.
8. `ready` reports accumulate new signals silently. After enough new signals (`signal_count >= signals_at_run`), the report is re-promoted and the summary workflow runs again — reusing the previous repo selection and lightly validating previous findings instead of re-researching from scratch.

Reports that aren't `ready` still appear in the output with their `error` field explaining why they were filtered, plus `artefacts` containing the full judge reasoning.

## Seeding a pre-researched report

Use `ingest_report_json` to short-circuit the research flow and drop a fully-researched `SignalReport` into the database, so you can test the autostart path without the sandbox.

```bash
# 1. Make sure at least one team user has opted into autonomy. Either set a default
#    threshold for the team via SignalTeamConfig, or have a user POST to
#    /api/users/<id>/signal_autonomy/ with their personal autostart_priority.

# 2. Ingest a research-output fixture — creates a SignalReport, persists artefacts,
#    triggers `maybe_autostart_implementation_task`, then marks the report READY.
python manage.py ingest_report_json \
    products/signals/backend/report_generation/fixtures/insight_scene_logic_mode_property_bug.json \
    --team-id 1
```

The fixture must match the shape in `report_generation/fixtures/` — a JSON object with `repository`, `signal_ids`, and a `result` that parses as `ReportResearchOutput`. Autostart still requires a working GitHub integration (for reviewer resolution) and the commit authors in `relevant_commit_hashes` to map to a user with a `SignalUserAutonomyConfig` whose effective priority threshold (personal or team default) covers the report's priority — otherwise the report will be saved but no `Task` will be created.

## Seeding billable reports (refund testing)

`seed_refund_test_data` drops five minimal reports covering the refund/exemption matrix:
PR-run-today (refund takes the `excluded` path), PR-run-4-days-ago (`credited` path — calls the billing dispute endpoint), PR-run-last-month (out of the billing period — the Refund button renders disabled with the reason), billing-exempt with a PR ("Free" badge with health-check tooltip; refund hidden), and no-PR (target for `exempt_signal_report_billing`). Re-run freely — a report can only be refunded once.

```bash
python manage.py seed_refund_test_data --team-id 1
```

`seed_inbox_data` reports are billable too (runs are recorded via the production dual-write), but their runs are created "now", so refunds on them always take the excluded path.
`seed_inbox_data --github-optional` seeds the reports GitHub-optional research leaves without a GitHub integration: a `data_only` repo selection with no repository, and no commits, GitHub reviewers, or implementation runs.
Environment prerequisites (feature flag, local billing service): "Testing refunds locally" in `../../ARCHITECTURE.md`.

## Re-ingesting reports

`reingest_signal_report` deletes specific reports and re-emits their signals through the active pipeline (same `SignalReportReingestionWorkflow` as the API `reingest` action), so they regroup and re-research from scratch:

```bash
python manage.py reingest_signal_report --team-id 1 <report-uuid> [<report-uuid> ...]
```

For a full-team wipe + reingest, use `reingest_team_signals --team-id 1` (add `--delete` for delete-only).

## Repository selection (agentic)

Test the repo selection flow in isolation:

```bash
# Using the team's actual GitHub integrations (same as production)
python manage.py select_repo

# With explicit candidate repos (bypasses integrations, useful for quick testing)
python manage.py select_repo --repos PostHog/posthog PostHog/posthog-js PostHog/posthog-python

# Verbose mode — stream raw sandbox logs
python manage.py select_repo --verbose
```

Uses synthetic JS SDK signals by default. The agent uses `gh` CLI to explore candidates and pick the best match.

## Signals agent (headless scout)

Two commands cover the day-to-day loop on the headless `signals-scout-*` scouts.
Background and architecture: `../scout_harness/AGENTS.md` and `../../skills/AGENTS.md`.

### Running one scout locally

`run_signals_scout` triggers a single `(team, skill)` run end-to-end without waiting for the Temporal coordinator. Inserts a `SignalScoutRun` row, opens a sandbox, pumps the agent loop until budget exhaustion or natural completion, finalizes the run.

```bash
# Single specialist run against a dogfood team
python manage.py run_signals_scout \
    --team-id 1 \
    --skill-name signals-scout-ai-observability

# Pin a skill version (default: latest LLMSkill row for the team)
python manage.py run_signals_scout --team-id 1 --skill-name signals-scout-general --skill-version 4

# Optional: pin the sandbox repository
python manage.py run_signals_scout --team-id 1 --skill-name signals-scout-general \
    --repository posthog/posthog --verbose

# Steer this one run without leaving a note that would steer the scheduled ones too
python manage.py run_signals_scout --team-id 1 --skill-name signals-scout-general \
    --note "focus on the checkout regression"
```

The team must have a `SignalScoutConfig` row for the scout (the coordinator auto-creates one; the command also seeds it). Configs default to `emit=False` — the scout runs and logs but `emit_finding` writes nothing, so no finding reaches the Signals inbox until you flip `emit=True` on that scout's config (e.g. via the `scout-config-update` MCP tool).

### Canonical skill sync

`sync_signals_scout_skills` forces a `sync_canonical_skills` pass without waiting for the next coordinator tick. Reads `products/signals/skills/signals-scout-*/` from disk and reconciles each scout against the team's `LLMSkill` rows.

```bash
# After merging a SKILL.md change — fan out to every dogfood team now
python manage.py sync_signals_scout_skills --all-enabled

# Onboard one team synchronously
python manage.py sync_signals_scout_skills --team-id 1

# See what would change without writing
python manage.py sync_signals_scout_skills --all-enabled --dry-run
```

Output buckets per team: `created`, `updated`, `diverged` (team-edited or hand-authored rows left alone), `tombstoned` (rows the team already soft-deleted — left alone, never resurrected), `pruned` (live rows whose canonical skill was removed from disk — soft-deleted so the coordinator stops dispatching them). Same function the coordinator and runner call lazily — this command is just the impatient path.

### Pre-computed scout suggestions

`run_scout_suggestions` drives the headless "Suggested for this project" scan (`../scout_harness/suggestions.py`) without waiting for its Temporal coordinator. `--team-id` runs the scan inline for one team (bypassing the planner and its cap; the org still needs AI data processing approved) and prints the stored batch; `--show` prints the stored batch without running; `--plan` prints what the coordinator would dispatch on the next tick under the current `signals-scout-suggestions` flag payload, and runs the dispatch-time activity check too, so it stamps `low_activity` on the projects it rules out exactly as the tick would.

```bash
# Generate (or regenerate) the batch for one team now, then print it
python manage.py run_scout_suggestions --team-id 1

# Just print what is stored
python manage.py run_scout_suggestions --team-id 1 --show

# What would the next coordinator tick dispatch?
python manage.py run_scout_suggestions --plan
```

## Backfilling task_run artefacts

One-off data migration: turn legacy `SignalReportTask` rows (those carrying the old `relationship` label) into `task_run` log artefacts so the research / implementation / repo-selection runs tied to a report show up in its artefact timeline. `SignalReportTask` lives on as the unlabelled task↔report association; rows without a legacy label are skipped — their `task_run` artefact is written at creation time.

```bash
# Preview, scoped to one team
python manage.py backfill_task_run_artefacts --team-id 1 --dry-run

# Backfill for real (all teams, or add --team-id N)
python manage.py backfill_task_run_artefacts
```

Idempotent — skips any report that already has a `task_run` artefact referencing the same task, so it is safe to re-run. Each artefact carries a `(product, type)` pair: these are signals-pipeline runs, so `product` is `signals` and `type` is the legacy relationship label (`research` / `implementation` / `repo_selection`). Backfilled artefacts are attributed to their task and backdated to their `SignalReportTask.created_at` so the log stays chronologically correct (the artefact row is created now, but the run happened earlier). Live creation paths append the same artefacts at run time going forward — custom agents instead use their own `identifier()` `(product, type)` pair.

## Backfilling report work and pull requests

`uv run manage.py backfill_report_pull_requests --team-id <id>` imports assignment
ownership and legacy PR links into work artefacts and shared `SignalReportPullRequest`
records. `--batch-size` bounds each page; the printed `--after` cursor resumes it.
The command is idempotent and does not call GitHub, change report state, or enqueue
reviewers. See `docs/internal/signals-pr-lifecycle.md` for rollout and cleanup.

## Backfilling inbox summary participants

`uv run manage.py backfill_inbox_summary --team-id <id> --dry-run` previews the next
batch of verified implementation PRs that need participant snapshots. Remove
`--dry-run` to queue the GitHub refresh. `--limit` bounds each invocation (default
100, maximum 1000); use the printed `--after` cursor to continue. Run it without a
cursor again to retry missing snapshots. The worker repairs missing merge times
before checking the seven-day window. Completed snapshots are skipped.

## Repairing a report's cached actionability

`SignalReport.latest_actionability` and `latest_already_addressed` cache the two values of a report's newest `actionability_judgment` artefact, so the inbox list can sort and filter on a column instead of walking the artefact log once per report.
A `post_save` / `post_delete` receiver maintains them and a migration filled the historical rows, so this command is a repair rather than a routine job.
Run it when the columns are suspected to disagree with the artefact log, for example after a bulk write that bypassed Django signals.

```bash
# Every team
uv run manage.py backfill_report_actionability

# One team, smaller pages, resuming after the report id an earlier run printed
uv run manage.py backfill_report_actionability --team-id 1 --batch-size 100 --after <report-id>
```

Idempotent. It recomputes each report from its artefacts and writes only the rows that disagree.

## Filling the cached Inbox ordering values

`uv run manage.py backfill_inbox_sort_cache --team-id <id>` fills the priority and ranking cache in locked batches.
Run it only after all API processes and workers use the cache writers.
Keep `inbox-sort-cache` off until the backfill completes for every team in the organization.
The command can run again after an interruption.
See [Inbox ranking rollout](../../../../../docs/internal/inbox-ranking-training.md#cached-inbox-ordering) for the rollout and rollback steps.

## Filling the cached implementation PR flags

`SignalReport.has_implementation_pr` and `has_active_implementation_pr` cache `implementation_pr_report_filter`, so the inbox filters on a column.
The receivers in `implementation_pr_cache.py` refresh them after every link write.
Run `backfill_report_inbox_state` once after the columns ship, and again as a repair after a bulk write that bypassed Django signals.

```bash
# Every team
uv run manage.py backfill_report_inbox_state

# One team, resuming after the report id an earlier run printed
uv run manage.py backfill_report_inbox_state --team-id 1 --after <report-id>
```

Idempotent. It writes only the rows that disagree with the live filter.

## Resuming operational scouts the setup flow paused

An older self-driving setup flow switched off every scout the user did not pick, including operational scouts such as inbox validation.
Those rows look like a person's pause, so the coordinator's reconcile leaves them alone.
The setup flow paused them over MCP on the user's own session, so `status_changed_by` holds the user and cannot tell the two apart.
`resume_setup_paused_operational_scouts` resumes only operational rows whose pause has an `mcp` activity log entry within a few seconds of `status_changed_at`.
It leaves pauses from the UI, the system, a scout, or with no log entry alone, and prints how many paused rows each source holds.
Pass `--max-gap-seconds` to also require that the pause landed soon after creation. It is off by default.
It skips withheld scouts and does not go past the enabled-scout cap.

```bash
# Dry run (the default): counts per scout and the first team ids
uv run manage.py resume_setup_paused_operational_scouts

# Write, optionally for one team
uv run manage.py resume_setup_paused_operational_scouts --apply --team-id 1
```

Idempotent. A resumed row no longer matches.

## Switching off general scouts nobody chose

Opening the inbox once seeded the general scout enabled for every team, so many teams run one that no person turned on.
`unenroll_unchosen_general_scouts` sets `enabled=False` on a running `signals-scout-general` row only when no person created or enabled it, and the team never completed self-driving setup.
Setup completed on a child project counts for the parent's scout.
It also leaves a row alone when a person or the wizard enabled or created another non-operational scout on the team, or when the row's activity log shows a person changed whether or when it runs (that survives the person's account being deleted, which clears `enabled_by`).
Every skip reason is checked again under the row lock just before the write.
A team that edited the general scout skill is left alone.
Each row saves on its own, so the activity log records it, and `save` moves `status` to `paused_by_user` with no `status_changed_by`.
It prints totals for matched, skipped, and changed rows, split by `managed_by` and `status`.

```bash
# Dry run (the default): totals and the first 50 team ids
uv run manage.py unenroll_unchosen_general_scouts

# Canary on some teams, then write for all
uv run manage.py unenroll_unchosen_general_scouts --apply --team-ids 1 2
uv run manage.py unenroll_unchosen_general_scouts --apply
```

Idempotent. A switched-off row no longer matches.

## Reactivating report checks a paused scout retired

Dispatch once treated a paused scout as a permanent refusal, so three ticks of a pause retired an `agent` check as `errored`.
`reactivate_pause_errored_report_checks` makes such a check active and due again with a clear error count.
A check matches only when its last result is the paused-scout refusal, its report is still resolved, and its horizon has not passed.
If the scout is still paused, the reactivated check waits for the resume without spending errors.

```bash
# Dry run (the default): how many checks match, and the first team ids
uv run manage.py reactivate_pause_errored_report_checks

# Write, optionally for one environment
uv run manage.py reactivate_pause_errored_report_checks --apply --team-id 1
```

Idempotent. A reactivated check no longer matches.

## Building a personal inbox ranking

`run_personal_inbox_ranking` builds one person's ranked inbox list with one LLM call (`../personal_ranking/`) and prints it, with each report's rank, tier and reason.
It reads its limits from the `personal-inbox-ranking` flag payload, and `"enabled": false` there stops every build.
It prints the effective config first: the model, `reasoning_effort`, `rank_top`, `max_candidates`, `timeout_seconds` and `max_completion_tokens`.
The model ranks only the best `rank_top` candidates. The other candidates follow in model order, with `ranked_by: model`.
At most `top_max` entries (default 5) get the `top` tier and at most `worth_a_look_max` (default 15) get `worth_a_look`. An entry past a cap moves down to the next tier with room and keeps its rank.

```bash
# Call the model, but store no PersonalInboxRanking row and capture no event
uv run manage.py run_personal_inbox_ranking --team-id 1 --user-id 1 --dry-run

# Store the row and capture `personal inbox ranking built`, with optional focus text
uv run manage.py run_personal_inbox_ranking --team-id 1 --user-id 1 --focus "checkout errors"
```

Every candidate is tied to the person: routed to them, waiting on their input, or claimed by them.
A person with no such report gets `status: empty` with no model call.

An optional `pools` list in the payload replaces the default candidate pools, in merge order:

```json
{
  "pools": [
    { "source": "assigned", "size": 5 },
    { "source": "for_you_recommended", "size": 10 },
    { "source": "for_you_updated", "size": 0 }
  ]
}
```

Each entry takes a `source` (`for_you_recommended`, `for_you_updated` or `assigned`), a `size` (0 turns it off) and an optional `name`.
The build logs and drops an invalid entry, such as one with the removed `scored` or `priority` source, and uses the default pools when no entry is valid.

A person with no ready activity summary gets a list in model order with no model call, marked `personalized: False` and `fallback_reason: no_activity_summary`.
When the model call fails or answers outside the schema, the list is in model order and `fallback_reason` says why.
The `personal inbox ranking built` event records `model_called`, so builds with and without a model call can be counted apart.
The command spends no build limit, so use it only for single runs.

`GET /api/projects/:id/signals/reports/for_me/` (`../personal_ranking/serve.py`) serves the same list to the user it describes, when the flag is on for that user.
It reuses the latest row for `freshness_minutes` after the row was built or last checked by the tick, while the input hash matches.
Otherwise it queues one `build_personal_inbox_ranking` Celery task per person behind a cache lock, and serves the latest row as stale, or the candidates in inbox order with `fallback_reason: building`.
The input hash covers the model, `reasoning_effort` and the rendered system prompt, so a payload change to a lever the prompt names, such as `rank_top`, a tier cap or a reason limit, rebuilds each list at its next check.
It limits builds per person with `build_burst`, `builds_per_hour` and `builds_per_day` from the same payload.
`max_builds_per_day` (default 500, at most 10000) limits the builds that call the model across every person, in one Redis token bucket per region (`../personal_ranking/build_budget.py`).
A build with no ready activity summary, or for an organization that has not approved AI data processing, does not call the model and does not spend that limit.
When a limit refuses a build, the read serves the latest row as stale, or the candidates in inbox order with `fallback_reason: rate_limited`.
The scheduled tick spends from the same bucket.

When the activity summary tick stores a person's first summary and the person has no list, it queues the same Celery task with `trigger: first_summary`, so the first list does not wait for the personal ranking tick.
That build takes the per-person lock, needs `"enabled"` in the payload, and runs only when it calls the model, so it also needs candidates and AI approval, and it spends the shared `max_builds_per_day`.
It does not need tick enrollment. A build that a gate refuses leaves the pair to the tick.

### Scheduled personal ranking tick

`personal-inbox-ranking-tick` (`../personal_ranking/tick.py`) is a Temporal schedule on `SELF_DRIVING_TASK_QUEUE` with overlap `SKIP`.
It runs every `PERSONAL_INBOX_RANKING_TICK_INTERVAL_MINUTES` (default 15) in every environment, and builds lists ahead of the first `for_me` read.
The `tick` object of the `personal-inbox-ranking` payload holds its levers. Without `"enabled": true` in that object the tick does nothing, and `"enabled": false` at the top level stops it too.

```json
{
  "tick": {
    "enabled": true,
    "self_driving_organization_percentage": 5,
    "organization_ids": ["<organization uuid>"],
    "deny_organization_ids": [],
    "skip_team_ids": [],
    "target_interval_minutes": 60,
    "active_days": 7,
    "max_pairs_per_tick": 20,
    "max_concurrency": 4,
    "max_tick_builds_per_day": 100,
    "max_org_share": 0.25,
    "max_error_rate": 0.5
  }
}
```

- **Enrollment:** every project of the listed organizations, plus the salted `self_driving_organization_percentage` of the organizations with a project that has an enabled signal source. The percentage enrolls only those projects, and a higher percentage keeps the organizations of a lower one. The organization must approve AI data processing, and the activity summary must be readable for the project. A summary is readable for every project that activity summary generation enrolls, including its own percentage rollout. The deny list and `skip_team_ids` win. Enrollment decides who gets scheduled builds. It does not change who can read `for_me`.
- **Due pairs:** a member with a ready activity summary, activity in the last `active_days`, and a latest list that was built or checked longer ago than `target_interval_minutes`, or no list.
- **Order:** paying organizations first, then the most recent activity, then the oldest list. One organization takes at most `max_org_share` of `max_pairs_per_tick`.
- **Unchanged inputs:** the pair activity compares the input hash first. A match calls no model and sets `checked_at` on the latest row, so the pair is not due again until `target_interval_minutes` passes, and `for_me` serves that row as fresh. An enabled tick raises `freshness_minutes` to at least `target_interval_minutes`, so a plain read does not rebuild a list inside the tick's interval. A row whose model call failed, timed out or answered outside the schema, or that skipped the model without AI approval, is built again instead.
- **Limits:** a build that calls the model spends `max_tick_builds_per_day` (one Redis token bucket per region, closed when Redis is unreachable) and then the shared `max_builds_per_day`. `max_tick_builds_per_day` is limited to 80% of `max_builds_per_day`, so `refresh` and `focus` requests keep a reserve. To run the tick above that, raise the shared limit too. The tick stops at the first refusal, at `max_error_rate` after 10 model calls, and when 60% of its interval has passed.
- **Locks:** the pair takes the same per-person lock as `for_me`, so a tick skips a person whose build is running.
- **Concurrency:** the tick keeps `max_concurrency` pairs running and starts the next pair as soon as any pair finishes. A stop starts no further pair, and the pairs already running finish. The pairs never started stay due for the next tick.
- **Bounds:** the payload can set `max_pairs_per_tick` up to 2000, `max_concurrency` up to 50, and `max_tick_builds_per_day` and `max_builds_per_day` up to 50000. Larger values clamp to these.

Each enabled tick captures `personal inbox ranking tick` with the due pairs, the pairs it picked, a count per pair status (`built`, `failed`, `unchanged`, `running`, `not_enrolled`, `tick_limited`, `shared_limited`), the stop reason, `oldest_due_hours`, `fresh_share`, the enrolled organizations and teams, and the duration.
It also carries `unchanged_pair_seconds_p50`, `unchanged_pair_seconds_p95`, `built_pair_seconds_p50` and `built_pair_seconds_p95`: the seconds from the start of a pair to its result, for sizing `max_concurrency` and `max_pairs_per_tick`.
`personal inbox ranking built` and the model call's trace carry `trigger` (`tick`, `on_demand` or `first_summary`), so cost can be split by what started a build.

`due_pairs`, `due_without_list` and `oldest_due_hours` are read when the tick plans, before it does any work.
A healthy tick reads `oldest_due_hours` a little above `target_interval_minutes`, and one old list that just became due makes it spike, so do not alert on it.
`oldest_due_activity_hours` and `oldest_due_summary_hours` are the hours since the last activity and since the activity summary of the pair behind `oldest_due_hours`, to show whether that pair just became eligible again.

The backlog after the tick is in `remaining_due_pairs`, `remaining_due_without_list` and `remaining_oldest_due_hours`. Alert on these:

- A due pair of the plan leaves the backlog when its result is `built`, `unchanged` or `not_enrolled`. Every other result, a pair that raised, a pair a stop never started, and a due pair past `max_pairs_per_tick` or `max_org_share` stay in it.
- `remaining_oldest_due_hours` is the hours at the end of the tick since the oldest remaining list was built or checked. It ignores remaining pairs with no list, which `remaining_due_without_list` counts.
- An empty backlog reads 0, 0 and null. A backlog of only pairs with no list also has a null age, so read the age with `remaining_due_pairs`.
- A pair that becomes due while the tick runs is not in the plan, so it counts in the next tick.
- The three fields are null for a tick planned before the deploy that added them.

## Publishing signal filter catalogs

`publish_signal_filter_catalogs` publishes the checked-in field catalogs in `../filter_catalog_seeds.py` to the instance-global filter catalog tables.
Run it once in each region after a change to a seed.
An unchanged catalog creates no version, and a changed one becomes the next active version.
It sets the rollout state only when it creates a source, and it never sets filter eligibility.

```bash
uv run manage.py publish_signal_filter_catalogs
```

## Tips

- Compare runs by saving output: `list_signal_reports --json > run_baseline.json`
- `emit_signals_from_fixture` and `emit_signals_from_llm` apply the team's `SignalSourceConfig.config` steering keys (`steering`, `default_not_actionable`) like production does — clear them on the source's config row for an unsteered baseline
- Read each command's source for all available flags — they are in this directory
- If you are looking for the local-only debug commands `analyze_report.py`, `select_repo.py`, or `parse_sandbox_log.py`, those are documented in `../report_generation/AGENTS.md`
- **If you change any command or the flow, update this file to match**
