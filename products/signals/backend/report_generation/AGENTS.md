# Signals Report Generation

This directory contains the new agentic report-research flow for Signals.
It is exercised locally via management commands, and it is also used by the production Temporal summary flow behind a feature flag. In production, the summary workflow runs the safety judge first, then calls into this flow via a Temporal activity if the report is safe.

## What lives here

- `select_repo.py`
  Selects the most relevant GitHub repository for a set of signals.
  - If the team has 0 repos: returns `None` (report goes to `pending_input`).
  - If the team has 1 repo: returns it directly (no sandbox needed).
  - If the team has N repos: spawns a sandbox agent that uses `gh` CLI to explore candidates and pick the best match. Uses `PostHog/.github` as a small dummy repo for the sandbox clone, since the agent only needs `gh` CLI access (not the repo itself).
  - Output: `RepoSelectionResult(repository: str | None, reason: str)`.
  - Persisted as a `repo_selection` artefact on the report (by the caller activity, not here).
  - On re-promotion, the activity reuses the previous artefact instead of re-running selection.
- `research.py`
  Orchestrates a multi-turn sandbox session over a report's signals.
  The agent researches each signal, then produces:
  - per-signal findings
  - actionability assessment
  - priority assessment when actionable
  - final report title
  - very short factual summary
  - optional charts (see below), when the team is opted in
    The repository used for research is tracked separately via the `repo_selection` artefact.
- `fixtures/analyze_report_funnel_research_output.json`
  Saved previous research output used by local `update` testing.
- `fixtures/insight_scene_logic_mode_property_bug.json`
  Saved research output for a single-signal, `immediately_actionable` P1 report.
  Used by the `ingest_report_json` management command to exercise the autostart path without running the sandbox research flow.

## Mental model

`run_multi_turn_research()` is the main entrypoint.

- `research` behavior:
  start from raw signals only
  research each signal as new
  produce findings + assessments + title/summary
- `update` behavior (re-promoted reports or `analyze_report update`):
  start from raw signals plus a previous `ReportResearchOutput`
  match previous findings by `signal_id`
  lightly validate old findings before reusing them
  fully research only new or stale signals
  show previous actionability, priority, title, and summary as context
  the agent confirms still-correct findings/assessments (via the `*Update` wrapper schemas) instead of regenerating them — `ReportResearchOutput` splits its findings/assessments into `old_artefacts` (confirmed unchanged, already persisted) and `new_artefacts` (produced this run), and the caller activity persists the new ones unconditionally; read the report's effective state via the `effective_*` accessors

When a report was spawned because a signal would have grouped into an already-**resolved** report (resolved reports are terminal and never reopen), the grouping pipeline links the two with symmetric `related_to` artefacts (one on each, pointing at the other). The caller activity finds the linked report that is resolved and passes `resolved_report_title` / `resolved_report_summary`. The initial research prompt then includes a `## Previously resolved report` block so the agent can judge whether the recurrence is a regression, a new dimension of the same issue, or distinct.

In production, the `update` path is triggered automatically when a `ready` report is re-promoted after accumulating enough new signals. The caller activity (`temporal/agentic/report.py`) reconstructs the previous `ReportResearchOutput` from stored artefacts and the report's title/summary fields, then passes it to `run_multi_turn_research()`.

This module is intentionally prompt-orchestration only.
Production persistence is handled outside `run_multi_turn_research()`, in the caller activity, so this module stays isolated from report DB writes.

### Charts

The presentation step can also author `charts` — query nodes the inbox draws on the report body, so a finding about a metric move is visible next to the sentence describing it. They are the same `SignalReport.charts` the scout channel writes (schema + bounds in `report_charts.py`), authored in the same structured response as the title/summary so the summary can place one with a `[label](chart:<id>)` markdown link. This is the pipeline counterpart of the scout `emit_report` charts path.

- **Opt-in.** Gated per team by the `signals-report-charts` flag (`_team_report_charts_enabled` in the caller activity; on in DEBUG). When off, both the chart guidance and the `charts` field itself are dropped from the presentation prompt (chart-free schema), and the caller drops anything the model returns anyway — so an un-opted team is never shown or steered toward charts on the delicate fleet-wide path.
- **Replace, not append.** `charts` is the report's whole set. On a re-research the previous charts are shown back as context (loaded from `SignalReport.charts` by `_load_previous_research`); the run keeps, refreshes, or drops them and the caller replaces the column with the result.
- **Persistence is atomic with the prose.** `run_agentic_report_activity` only _resolves_ the charts payload (`_resolve_report_charts_payload`) and returns it on `RunAgenticReportOutput.charts`; the column is written by the transition activity that also writes the title/summary (`mark_report_ready_activity` / `mark_report_pending_input_activity`), inside the same `transition_to` transaction. So charts and the prose they illustrate land together — a failed run or the not-actionable reset (neither writes the new prose) leaves the charts alone by construction, with no separate-transaction window. The resolver yields three outcomes: a valid non-empty set (replace the column); `None` when the team isn't opted in **or** the run authored no charts (leave the column alone — the presentation field is optional, so an omitted key and a deliberate "drop everything" both arrive empty and are indistinguishable, and wiping user-visible charts on that ambiguity is the worse failure, so the pipeline never auto-clears to zero; a human can clear from the inbox); and `[]` when the set busts the whole-set caps (clear, so a stale set can't sit under the new summary).
- **Not safety-judged.** The pipeline's safety judge screens the input signals before research runs, so it never sees research-authored charts — the same as it never sees research-authored title/summary. Charts are agent output derived from already-screened signals, consistent with that model. (This differs from the scout emit path, where charts and prose are judged together.)

The caller activity passes `has_business_knowledge=True` when the team's business knowledge product is both feature-flagged on and has at least one READY source (via `products.business_knowledge.backend.logic.is_available_for_team`). When true, the research prompt includes a `## Business knowledge` block that instructs the agent to search the team's curated knowledge base via MCP tools.

## Local debug commands

These commands are debug-only local-dev tools.
They are not production entrypoints.

### `analyze_report`

File: `../management/commands/analyze_report.py`

Local dev tool (DEBUG only). Runs the agentic research/update flow against synthetic signals.
Will be reworked into an eval harness — keeping it now preserves coverage of the multi-turn research path while the eval infrastructure is built.

- `python manage.py analyze_report research`
  Fresh research run from the hardcoded synthetic signals.
- `python manage.py analyze_report update`
  Loads `fixtures/analyze_report_funnel_research_output.json` as previous report research, appends one extra synthetic signal, and tests the re-research path.

Use this command when changing prompt logic in `research.py`.

### `select_repo`

File: `../management/commands/select_repo.py`

Local dev tool (DEBUG only). Tests repo selection in isolation against synthetic JS SDK signals.
Will be reworked into an eval harness — keeping it now preserves coverage of the sandbox-based repo selection path.

- `python manage.py select_repo`
  Uses the team's actual GitHub integrations to list candidate repos.
- `python manage.py select_repo --repos PostHog/posthog PostHog/posthog-js PostHog/posthog-python`
  Bypasses integrations and uses an explicit candidate list.

Use this command when changing prompt logic in `select_repo.py`.

### `parse_sandbox_log`

File: `../management/commands/parse_sandbox_log.py`

Local dev/testing tool (DEBUG only). Extracts key events from verbose sandbox logs without consuming the full stream — useful for both human inspection and agentic use (e.g., agents reviewing sandbox runs without reading raw S3 log streams).

Renders a concise timeline of: prompts, tool calls, tool outputs, agent messages, and optional thought chunks.

## When editing this flow

- Keep the roles separate:
  summary/title describe what the report is about;
  actionability/priority explain what to do and how urgent it is.
- If you change the output shape of `ReportResearchOutput`,
  update `fixtures/analyze_report_funnel_research_output.json` and
  `fixtures/insight_scene_logic_mode_property_bug.json` too.
- Keep persistence out of `run_multi_turn_research()`.
  If production needs new report artefacts or state transitions, do that in the caller activity/workflow.
- If you change how local debug commands exercise this flow,
  update this file and `../management/AGENTS.md`.
- **If you change any command or the flow, update this file to match**
