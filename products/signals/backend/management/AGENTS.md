# Signal Pipeline Management Commands

Commands for emitting signals, tracking pipeline processing, and inspecting grouping results.
Use these to test grouping strategies against real signal data end-to-end.

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
7. On reaching `ready`, the summary workflow starts `signal-report-inbox-notification` to post the Slack
   inbox notification. If the report auto-started an implementation task, that workflow waits for the PR to
   open (bounded by `SIGNALS_INBOX_PR_NOTIFICATION_TIMEOUT_SECONDS`) so the card can show a "Review PR"
   button; if that task never opens a PR (fails, is cancelled, or the wait times out) no notification is
   sent. Reports with no auto-start task notify immediately.
8. `ready` reports accumulate new signals silently. After enough new signals (`signal_count >= signals_at_run`),
   the report is re-promoted and the summary workflow runs again — reusing the previous repo selection and
   lightly validating previous findings instead of re-researching from scratch.

Reports that aren't `ready` still appear in the output with their `error` field
explaining why they were filtered, plus `artefacts` containing the full judge reasoning.

## Seeding a pre-researched report

Use `ingest_report_json` to short-circuit the research flow and drop a fully-researched
`SignalReport` into the database, so you can test the autostart path without the sandbox.

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

The fixture must match the shape in `report_generation/fixtures/` — a JSON object with
`repository`, `signal_ids`, and a `result` that parses as `ReportResearchOutput`. Autostart
still requires a working GitHub integration (for reviewer resolution) and the commit authors
in `relevant_commit_hashes` to map to a user with a `SignalUserAutonomyConfig` whose effective
priority threshold (personal or team default) covers the report's priority — otherwise the
report will be saved but no `Task` will be created.

## Session summary (video-based)

Test the SummarizeSingleSessionWorkflow with full video validation:

```bash
python manage.py summarize_single_session <session_id> [--team-id N] [--user-id N]
```

Uses first team/user if omitted. Runs `execute_summarize_session` with video-based summarization.

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

`run_signals_scout` triggers a single `(team, skill)` run end-to-end without waiting
for the Temporal coordinator. Inserts a `SignalScoutRun` row, opens a sandbox, pumps
the agent loop until budget exhaustion or natural completion, finalizes the run.

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
```

The team must have a `SignalScoutConfig` row for the scout (the coordinator auto-creates
one; the command also seeds it). Configs default to `emit=False` — the scout runs and
logs but `emit_finding` writes nothing, so no finding reaches the Signals inbox until you
flip `emit=True` on that scout's config (e.g. via the `signals-scout-config-update` MCP tool).

### Canonical skill sync

`sync_signals_scout_skills` forces a `sync_canonical_skills` pass without waiting for
the next coordinator tick. Reads `products/signals/skills/signals-scout-*/` from disk
and reconciles each scout against the team's `LLMSkill` rows.

```bash
# After merging a SKILL.md change — fan out to every dogfood team now
python manage.py sync_signals_scout_skills --all-enabled

# Onboard one team synchronously
python manage.py sync_signals_scout_skills --team-id 1

# See what would change without writing
python manage.py sync_signals_scout_skills --all-enabled --dry-run
```

Output buckets per team: `created`, `updated`, `diverged` (team-edited or hand-authored rows
left alone), `tombstoned` (rows the team already soft-deleted — left alone, never resurrected),
`pruned` (live rows whose canonical skill was removed from disk — soft-deleted so the
coordinator stops dispatching them). Same function the coordinator and runner call lazily —
this command is just the impatient path.

## Backfilling task_run artefacts

One-off data migration: turn legacy `SignalReportTask` rows (those carrying the old `relationship`
label) into `task_run` log artefacts so the research / implementation / repo-selection runs tied to
a report show up in its artefact timeline. `SignalReportTask` lives on as the unlabelled
task↔report association; rows without a legacy label are skipped — their `task_run` artefact is
written at creation time.

```bash
# Preview, scoped to one team
python manage.py backfill_task_run_artefacts --team-id 1 --dry-run

# Backfill for real (all teams, or add --team-id N)
python manage.py backfill_task_run_artefacts
```

Idempotent — skips any report that already has a `task_run` artefact referencing the same task, so it
is safe to re-run. Each artefact carries a `(product, type)` pair: these are signals-pipeline runs, so
`product` is `signals` and `type` is the legacy relationship label (`research` / `implementation` /
`repo_selection`). Backfilled artefacts are attributed to their task and backdated to their
`SignalReportTask.created_at` so the log stays chronologically correct (the artefact row is created
now, but the run happened earlier). Live creation paths append the same artefacts at run time going
forward — custom agents instead use their own `identifier()` `(product, type)` pair.

## Offline grouping replay

The export, replay, and import commands form a deliberately offline path for evaluating the frozen grouping pipeline.
They do not enqueue the production grouping or research workflows.

### Export a bounded source dataset

`export_signals_grouping_data` reads the latest version of each signal from team-scoped HogQL, including its full 1,536-dimensional embedding.
The lower timestamp bound is mandatory and the signal count has a hard cap.
Deleted signals are filtered only after latest-version deduplication, so a tombstone cannot expose an older live version.

```bash
python manage.py export_signals_grouping_data /tmp/signals-export \
    --team-id 1 \
    --since 2026-06-01T00:00:00Z \
    --until 2026-07-01T00:00:00Z \
    --max-signals 10000
```

The destination must not exist.
It is installed atomically with mode `0700`; `signals.jsonl`, `reports.jsonl`, and `manifest.json` use mode `0600`.
The manifest records source bounds, counts, warnings, and SHA-256 integrity data for both JSONL files.
Command output contains counts and paths only, never signal content.
The export and replay commands enforce a 10,000-signal ceiling because the current proof-of-concept retrieval loop is not designed for an unbounded team history.
Use narrower time ranges for larger evaluations.

### Run the frozen replay

`run_signals_grouping_pipeline` accepts an export directory or a standalone signals JSONL file and writes one portable `posthog-signals-grouping-replay/v1` JSON bundle.
Provider results and intermediate cache entries live in an append-only work directory, which makes retries resumable and auditable.
`reports.jsonl` preserves the observed production partition for labeling and comparison; it never seeds replay assignment.

```bash
python manage.py run_signals_grouping_pipeline \
    /tmp/signals-export \
    /tmp/replay-oracle-off.json \
    --team-id 1 \
    --work-dir /tmp/signals-replay-work \
    --mode oracle-off \
    --haiku-concurrency 128 \
    --embedding-concurrency 8

# Validate input and integrity without provider calls, cache writes, or output.
python manage.py run_signals_grouping_pipeline \
    /tmp/signals-export /tmp/replay.json --dry-run
```

`--team-id` attributes uncached Haiku or embedding requests to a team through the PostHog gateway.
Embedding retries are isolated per text and a shared eight-request ceiling covers both signal and concern-signature embeddings.
`oracle-on` is experimental and also requires `--experimental-oracle-on`:

```bash
python manage.py run_signals_grouping_pipeline \
    /tmp/signals-export /tmp/replay-oracle-on.json \
    --team-id 1 --mode oracle-on --experimental-oracle-on
```

### Import a portable bundle for local display

`import_signals_grouping_pipeline` accepts only a portable v1 bundle and only runs with `DEBUG=True`.
Before any write, it validates bundle integrity, complete one-to-one membership, timestamps, counts, and every embedding value.
It also requires an explicit namespace and checks both the ClickHouse embedding table and ingestion buffer for target document ID collisions.
It creates fresh report IDs, clearly labels safety/actionability/priority artefacts as display defaults, and inserts the bundled vectors directly into ClickHouse.
It never invokes the live matcher, Temporal, report research, or judging.

```bash
# Full validation, no writes.
python manage.py import_signals_grouping_pipeline /tmp/replay-oracle-off.json \
    --team-id 1 --document-id-prefix replay-a: --dry-run

# Materialize the largest eligible reports for UI review.
python manage.py import_signals_grouping_pipeline /tmp/replay-oracle-off.json \
    --team-id 1 \
    --min-signals 2 \
    --limit-reports 100 \
    --document-id-prefix replay-a: \
    --max-signal-age-days 80 \
    --yes
```

Use a unique document ID prefix when comparing multiple imports in one team.
The command refuses a blank prefix or a prefix that produces any existing target document ID.
Timeline compression keeps old replay data inside the embeddings table TTL while preserving order and relative spacing.
Postgres report and artefact writes are atomic, but ClickHouse is a separate store.
If the ClickHouse phase fails after Postgres commits, remove the newly imported display reports before retrying.

## Tips

- Compare runs by saving output: `list_signal_reports --json > run_baseline.json`
- Read each command's source for all available flags — they are in this directory
- If you are looking for the local-only debug commands `analyze_report.py`, `select_repo.py`, or `parse_sandbox_log.py`, those are documented in `../report_generation/AGENTS.md`
- **If you change any command or the flow, update this file to match**
