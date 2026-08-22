---
name: analyzing-task-runs
description: >-
  Analyze a completed PostHog task run for inefficiencies — environment failures, missing CLI tools,
  verbose commands, redundant work, wasted retries — and file an evidence-backed report as a task
  artifact. Use when a task asks to analyze a run, produce run insights or a task analysis, or review
  a run's efficiency from an attached run log. Covers the log-handling protocol (the raw log never
  enters context), transcript extraction, the finding taxonomy, evidence verification, and uploading
  the report.
---

# Analyzing task runs

You are analyzing another task run's transcript for things that made it slower or more expensive
than it needed to be. You are not reviewing code quality. Your output is one JSON report uploaded
as an artifact.

The run log arrives as a file attachment on your task — the message contains a `file://` resource
link to a `.jsonl` file already on disk. You never fetch anything.

## The one hard rule: the raw log never enters your context

Run logs can be tens of megabytes. Do not `cat` the log, do not open it in an editor, do not read
it with a file tool, and do not paste any part of it into your reasoning before extraction. The
only way to look at the run is through the extracted transcript below. If you find yourself about
to read the raw log "to check something", run the extractor again with the log path instead.

## Protocol

1. **Locate the attached log.** The attachment path looks like
   `.posthog/attachments/<run-id>/<artifact-id>/<name>.jsonl`. Check it exists and note its size
   (`ls -lh <path>`). Do not open it.
2. **Extract the transcript.** Run the bundled extractor:

   ```sh
   python3 <skill-path>/scripts/extract_transcript.py <log-path> > transcript.md
   ```

   It emits ordered tool calls with titles, final statuses, and user/agent messages, collapses
   streaming-status repeats, and trims oversized runs (marked `TRANSCRIPT TRIMMED`). Typical output
   is a few hundred lines. If it prints `EXTRACTION EMPTY`, go to the failure protocol.

3. **Read `transcript.md` only.** If it is still long, read it in ranged chunks. Everything you
   claim must be visible in this file.
4. **Analyze** against the taxonomy below. Look for patterns, not single events: a command retried
   after environment fixes, a tool the agent clearly wanted but had to work around, output far
   larger than what the agent used from it.
5. **Verify every evidence quote** before reporting: each quote must appear verbatim in
   `transcript.md` — check with `grep -F` against the file, not from memory. Drop or fix any
   finding whose quote does not match. The reporting tool re-verifies quotes against the
   transcript and rejects findings whose evidence does not match, so unverified quotes waste a
   round trip.
6. **Report each finding with the `report_insight` tool — one call per finding**, in order of
   wasted effort (largest first), at most 5 calls. The payload for a single finding is defined in
   [references/insight-schema.md](references/insight-schema.md). Do not batch findings into one
   call and do not write report files.
7. **If there are zero findings**, make exactly one `report_insight` call carrying only
   `no_findings_reason` (`run_was_efficient`, `too_short_to_judge`, or `insufficient_visibility`).
   Zero findings is a valid, complete analysis — never invent one.
8. **Finish** with a one-paragraph summary of what you reported (or that there was nothing to
   report and why).

## Finding taxonomy

Use exactly one category per finding. The criterion line decides membership.

| Category              | Criterion                                                                                                                                                                                                                                           |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `environment_failure` | Verification (tests, build, run) failed for environment reasons — a service not running, a database not migrated, missing dependencies, a build that had to happen first, missing credentials — and the agent had to fix the environment and retry. |
| `missing_tool`        | An installable CLI or binary was absent, so the agent did the same job the long way (e.g. `gh` missing, so it hand-rolled API calls).                                                                                                               |
| `verbose_output`      | A command produced far more output than the agent needed, and the excess was read into context.                                                                                                                                                     |
| `redundant_work`      | The agent re-read or re-derived something already established earlier in the same run.                                                                                                                                                              |
| `missing_capability`  | A workflow capability — a skill or higher-level tool — would have replaced several manual steps. Distinct from `missing_tool`: this is about workflow, not an installable binary.                                                                   |
| `instruction_gap`     | Repository conventions or docs were unclear or wrong, causing a bad first attempt.                                                                                                                                                                  |
| `wasted_retry`        | The agent retried with nothing changed between attempts.                                                                                                                                                                                            |
| `other`               | Anything real that fits none of the above. Requires a justification in the report.                                                                                                                                                                  |

Healthy iteration is not a finding: verify → fail → **edit code** → verify again is how agents work.
Only flag retries where nothing changed or where only the environment changed.

## Failure protocol

If the attachment is missing, the extractor fails, or the transcript is empty: do not improvise an
analysis. Make one `report_insight` call with `no_findings_reason: "insufficient_visibility"` and
finish by stating plainly which step failed and why.

## Judgment notes

- Prefer few, well-evidenced findings over coverage. Report at most 5; if you found more, keep
  the 5 with the largest wasted effort.
- Suggested fixes must be concrete and checkable. "Pre-install the GitHub CLI (gh)" with
  done-when "gh --version succeeds in a fresh sandbox" is the bar; "improve the environment" is
  below it.
- Transcripts from cloud runs may lack the agent's narration; do not treat missing narration as
  evidence of anything.
- The transcript may contain user code and prompts. Use them only to classify; never copy source
  code, secrets, or personal information into the report beyond the short verbatim evidence quotes.
