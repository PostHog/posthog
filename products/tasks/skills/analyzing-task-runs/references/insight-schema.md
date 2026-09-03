# report_insight payload — one finding per call

Each `report_insight` call carries exactly one finding (or, once per run, a no-findings report).
Field order matters: state the observation before you classify it — reasoning first, conclusion
second. The tool verifies every quote against the raw run log and rejects the call with a
specific error when something does not check out; fix and retry once, then drop the finding.

## A finding

```json
{
  "observation": "<what happened, 1-3 sentences, 80-500 chars>",
  "evidence": [
    {
      "quote": "<verbatim span copied from your jq query output, 10-300 chars>",
      "evidence_type": "transcript_quote | command_output | measured_count"
    }
  ],
  "occurrence_count": 3,
  "category": "environment_failure | missing_tool | verbose_output | redundant_work | missing_capability | instruction_gap | wasted_retry | other",
  "other_justification": "<required only when category is other, 50-200 chars>",
  "wasted_effort": { "tool_calls": 12, "seconds": 190, "tokens": 22000 },
  "recurrence": "every_run_in_this_repo | runs_touching_this_area | one_off",
  "confidence_basis": "directly_observed | inferred",
  "suggested_fix": {
    "change": "<the specific change, 50-400 chars>",
    "done_when": "<a condition someone could actually check, 30-200 chars>",
    "setup_commands": ["<single-line command>"],
    "required_services": ["<service name>"],
    "env_var_names": ["<NAME only, never a value>"]
  }
}
```

## A no-findings report (once per run, only when there are no findings)

```json
{ "no_findings_reason": "run_was_efficient | too_short_to_judge | insufficient_visibility" }
```

## Rules

- One finding per call, at most 5 calls per run, largest wasted effort first.
- `evidence` holds 1-3 items. Every `quote` must appear in the raw run log — the tool checks
  (JSON escaping is handled) and rejects mismatches. Copy quotes exactly from your jq output,
  never from memory.
- `occurrence_count` is how many times the pattern happened in this run and must be consistent
  with the log.
- `wasted_effort` is required for `environment_failure`, `missing_tool`, `verbose_output`,
  `redundant_work`, and `wasted_retry`. Every dimension is measured from the log, never guessed,
  and you include each one you can measure (at least one):
  - `tool_calls` — count distinct wasted call IDs between the span's start and end lines.
  - `seconds` — subtract the event timestamp at the span's start from the one at its end.
  - `tokens` — sum completed turns wholly inside the wasted span. Pi records `totalTokens` on
    `turn_completed`; ACP may record it in `_posthog/turn_complete`. Omit tokens for a partial
    turn or a completion without usage.
  - `output_bytes` — sum of tool-output sizes across the span (the output-bytes recipe). Works in
    both formats even when the log has no token records.
    If a dimension cannot be measured from the log or its measured value is zero, leave it out —
    do not estimate.
    When the same pattern occurs in separate, non-contiguous spans, measure each span on its own and
    report the sum — never bracket from the first occurrence to the last, because that counts the
    unrelated work in between as waste.
- `recurrence` anchors: `every_run_in_this_repo` — structural to the repo or its sandbox image, any agent there hits it;
  `runs_touching_this_area` — conditional on the task area; `one_off` — specific to this run.
- `confidence_basis`: `directly_observed` — visible in the transcript; `inferred` — plausible but
  not directly evidenced. Never report a numeric confidence.
- `suggested_fix.setup_commands` entries must be single-line (they may become image build steps).
  `env_var_names` carries names only — a value there is a rejected call.
- Do not include any severity or priority — that is derived downstream from `wasted_effort` and
  `recurrence`.

## Worked example

```json
{
  "observation": "The test suite was started three times. The first two attempts failed while the agent installed and started Postgres; only the third attempt exercised the code change.",
  "evidence": [
    {
      "quote": "connection to server at \"localhost\", port 5432 failed: Connection refused",
      "evidence_type": "command_output"
    },
    { "quote": "docker compose up -d postgres", "evidence_type": "transcript_quote" }
  ],
  "occurrence_count": 2,
  "category": "environment_failure",
  "wasted_effort": { "tool_calls": 14, "seconds": 210 },
  "recurrence": "every_run_in_this_repo",
  "confidence_basis": "directly_observed",
  "suggested_fix": {
    "change": "Have Postgres already running in this repo's sandbox before the agent starts.",
    "done_when": "The test suite passes on its first attempt in a fresh sandbox with no service-start commands.",
    "required_services": ["postgres"]
  }
}
```
