# Weekly flaky report (prototype)

Renders a weekly "top flaky tests" Slack post and an HTML report from CI telemetry, attributed to owning teams via `owners.yaml`.
Backend CI (pytest) only for now; jest/playwright/rust need their suites to emit junit before they can join.

## Pipeline

1. Export three HogQL queries from the dogfood project into the working directory (see `build_flakes.py` inputs): per-test failures from `engineering_analytics_ci_failures`, rerun recovery joined against `github_workflow_runs`, and span `rerun_passed` outcomes from `posthog.trace_spans` (service `ci-backend`).
2. `python build_flakes.py`: resolves each test id to a repo file, attributes the owning team with the `tools/owners` resolver, classifies (confirmed / suspected / co-failing cluster / master burst), writes `flakes.json`.
3. `python render_slack.py`: deterministic Slack message (main table + thread stats), written to `slack_message.txt`.
4. `python render_leaderboard.py`: self-contained `leaderboard.html` with per-test evidence links.

## Classification

- confirmed: failed at attempt N, run went green at attempt N+1 on the same code (or span-level `rerun_passed`)
- suspected: failed on 3+ unrelated branches, no rerun proof
- cluster: 5+ suspected tests in one file, collapsed to one entry
- master burst: majority of failures on master across few branches; excluded (breakage, not flakiness)

No rankings or awards by design: the output routes work to owners and celebrates fixes.

## Status

Prototype for discussion. Open items: run it on a weekly GitHub Actions cron, post via the Slack API (Block Kit, table in section blocks, footer as context block), keep week-over-week `flakes.json` history for new/fixed diffs, and extend suite coverage past pytest.
