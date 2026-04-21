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
7. `ready` reports accumulate new signals silently. After enough new signals (`signal_count >= signals_at_run`),
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
#    triggers `_maybe_autostart_task_for_report`, then marks the report READY.
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

Uses first team/user if omitted. Runs `execute_summarize_session` with `video_validation_enabled='full'`.

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

## Tips

- Compare runs by saving output: `list_signal_reports --json > run_baseline.json`
- Read each command's source for all available flags — they are in this directory
- If you are looking for the local-only debug commands `analyze_report.py`, `select_repo.py`, or `parse_sandbox_log.py`, those are documented in `../report_generation/AGENTS.md`
- **If you change any command or the flow, update this file to match**
