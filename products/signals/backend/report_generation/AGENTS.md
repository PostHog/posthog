# Signals Report Generation

This directory contains the new agentic report-research flow for Signals.
It is exercised locally via management commands, and it is also used by the production
Temporal summary flow behind a feature flag. In production, the summary workflow runs
the safety judge first, then calls into this flow via a Temporal activity if the report is safe.

## What lives here

- `select_repo.py`
  Selects the most relevant GitHub repository for a set of signals.
  - If the team has 0 repos: returns `None` (report goes to `pending_input`).
  - If the team has 1 repo: returns it directly (no sandbox needed).
  - If the team has N repos: spawns a sandbox agent that uses `gh` CLI to explore
    candidates and pick the best match. Uses `PostHog/.github` as a small dummy repo
    for the sandbox clone, since the agent only needs `gh` CLI access (not the repo itself).
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
    The repository used for research is tracked separately via the `repo_selection` artefact.
- `fixtures/analyze_report_funnel_research_output.json`
  Saved previous research output used by local `update` testing.
- `fixtures/insight_scene_logic_mode_property_bug.json`
  Saved research output for a single-signal, `immediately_actionable` P1 report.
  Used by the `ingest_report_json` management command to exercise the autostart
  path without running the sandbox research flow.

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
  regenerate those outputs only as much as needed

In production, the `update` path is triggered automatically when a `ready` report is
re-promoted after accumulating enough new signals. The caller activity (`temporal/agentic/report.py`)
reconstructs the previous `ReportResearchOutput` from stored artefacts and the report's
title/summary fields, then passes it to `run_multi_turn_research()`.

This module is intentionally prompt-orchestration only.
Production persistence is handled outside `run_multi_turn_research()`, in the caller activity,
so this module stays isolated from report DB writes.

## Local debug commands

These commands are debug-only local-dev tools.
They are not production entrypoints.

### `analyze_report`

File: `../management/commands/analyze_report.py`

Local dev tool (DEBUG only). Runs the agentic research/update flow against synthetic signals.
Will be reworked into an eval harness — keeping it now preserves coverage of the multi-turn
research path while the eval infrastructure is built.

- `python manage.py analyze_report research`
  Fresh research run from the hardcoded synthetic signals.
- `python manage.py analyze_report update`
  Loads `fixtures/analyze_report_funnel_research_output.json` as previous report research,
  appends one extra synthetic signal,
  and tests the re-research path.

Use this command when changing prompt logic in `research.py`.

### `select_repo`

File: `../management/commands/select_repo.py`

Local dev tool (DEBUG only). Tests repo selection in isolation against synthetic JS SDK signals.
Will be reworked into an eval harness — keeping it now preserves coverage of the sandbox-based
repo selection path.

- `python manage.py select_repo`
  Uses the team's actual GitHub integrations to list candidate repos.
- `python manage.py select_repo --repos PostHog/posthog PostHog/posthog-js PostHog/posthog-python`
  Bypasses integrations and uses an explicit candidate list.

Use this command when changing prompt logic in `select_repo.py`.

### `parse_sandbox_log`

File: `../management/commands/parse_sandbox_log.py`

Local dev/testing tool (DEBUG only). Extracts key events from verbose sandbox logs
without consuming the full stream — useful for both human inspection and agentic use
(e.g., agents reviewing sandbox runs without reading raw S3 log streams).

Renders a concise timeline of: prompts, tool calls, tool outputs, agent messages,
and optional thought chunks.

## When editing this flow

- Keep the roles separate:
  summary/title describe what the report is about;
  actionability/priority explain what to do and how urgent it is.
- If you change the output shape of `ReportResearchOutput`,
  update `fixtures/analyze_report_funnel_research_output.json` too.
- Keep persistence out of `run_multi_turn_research()`.
  If production needs new report artefacts or state transitions, do that in the caller activity/workflow.
- If you change how local debug commands exercise this flow,
  update this file and `../management/AGENTS.md`.
- **If you change any command or the flow, update this file to match**
