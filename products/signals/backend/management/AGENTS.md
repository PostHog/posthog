# Signal Pipeline Management Commands

Commands for emitting signals, tracking pipeline processing, and inspecting grouping results.
Use these to test grouping strategies against real signal data end-to-end.

## Full flow

Always clean up before re-ingesting to avoid stale data mixing with new results.

```bash
# 1. Clean up — removes all signal data and terminates Temporal workflows
python manage.py cleanup_signals --team-id 1 --yes

# 2. Emit signals from a JSON file (example file)
python manage.py ingest_signals_json playground/signals-grouping-iterations/signals_mini.json --team-id 1

# 3. Wait for the pipeline to fully process all signals
#    Set --expected-signals to the number of signals in the file
python manage.py signal_pipeline_status --team-id 1 --wait --expected-signals 3 --poll-interval 10 --json

# 4. Inspect the grouping results
python manage.py list_signal_reports --team-id 1 --signals --json
```

Processing 3 signals typically takes 1-3 minutes depending on LLM response times.

## What happens during processing

1. Temporal grouping workflow receives signals and processes them sequentially
2. Each signal gets embedded, matched to an existing report or a new one via LLM
3. `SignalReport` rows are created/updated in Postgres
4. Signal embeddings land in ClickHouse `document_embeddings`
5. When a report's total weight reaches the threshold (default 1.0), a summary workflow runs:
   summarizes the group, runs safety + actionability judges
6. Report reaches a terminal state:
   - `ready` — passed both judges, actionable by a coding agent
   - `pending_input` — needs human judgment before acting
   - `failed` — failed safety review (possible prompt injection)
   - `potential` (reset, weight zeroed) — deemed not actionable

Reports that aren't `ready` still appear in the output with their `error` field
explaining why they were filtered, plus `artefacts` containing the full judge reasoning.

## Tips

- Compare runs by saving output: `list_signal_reports --json > run_baseline.json`
- Read each command's source for all available flags — they are in this directory
- **If you change any command or the flow, update this file to match**
