# Stamphog prompt backtest

Offline eval for the PR-approval agent: replay captured production review prompts under a candidate system prompt and score verdicts against real PR outcomes. Any behavior-affecting change to the engine, scaffold, or review guidance (anything that bumps `STAMPHOG_VERSION`) should ship with a backtest table in its PR — see #69185 for the pattern.

How it stays faithful: the reviewer's full prompt at review time (PR description, reviews, comments, assurance digest, exactly as composed) is stored in `posthog.ai_events` for every production run. Replaying from those frozen inputs means all arms see identical context, so between-arm deltas isolate the prompt change. Diffs and outcome labels come from local git only — no GitHub API traffic.

## Runbook

```bash
cd tools/pr-approval-agent/backtest

# 1. Manifest: one row per (repo, PR, version-cohort) with latest verdicts + trace id
POSTHOG_PERSONAL_API_KEY=phx_... uv run harvest_manifests.py --days 30

# 2. Frozen prompts (time-sensitive: ai_events retention is ~30 days)
POSTHOG_PERSONAL_API_KEY=phx_... uv run pull_traces.py

# 3. Diffs at review-time head + outcome labels, pure git
python3 prep_prs.py

# 4. Replay arms (~$0.14/review): control first, then the working-tree prompt
ANTHROPIC_API_KEY=... uv run replay.py --cohort 2.0.0b1 --arm asrun
ANTHROPIC_API_KEY=... uv run replay.py --cohort 2.0.0b1 --arm current

# 5. Compare
python3 score.py
```

Everything is resumable: existing traces, diffs, and per-trace results are skipped on rerun. Add `--rep 2` for repeat samples (verdicts are stochastic; `score.py` aggregates reps by modal verdict and reports flip rate). `data/` is gitignored; set `STAMPHOG_BACKTEST_DATA` to keep datasets elsewhere.

## Reading the results

- `approve` per arm is the headline, but read it against the `asrun` control run, not against production numbers: replay conditions (newer checkout, fresh sampling) shift both arms equally.
- `false-ref` is the velocity cost: PRs the arm refused/escalated that reality then merged unchanged.
- The risk side has no single number: read the flip list for PRs the candidate newly approves and check their outcomes (`merged_unchanged` vs merged-with-changes vs unmerged) in `data/labels.jsonl`.
- Single-rep verdict flips on individual PRs are noise; aggregates at n≈50+ are stable.

## Sharp edges

- Cohorts are `stamphog_version` values ('unmarked' = pre-2.0). PostHog/posthog PRs only, by design.
- Two instrumentation generations exist in the traces (direct-SDK with span names and per-run UUID trace ids vs ai-gateway with per-turn 32-hex ids); `pull_traces.py` and `backtest_lib.split_trace_input` handle both. Gateway traces may store no system message — the `asrun` arm then needs `data/systems/asrun_fallback.txt` (copy the system message from any traced-path trace of the same version).
- Post-review rebases rewrite committer dates, so `prep_prs.py`'s date walk can miss the reviewed head; rows whose events carried `stamphog_commit` fall back to it automatically.
- Repo state drifts: a replay greps today's checkout, so refusals that depended on then-missing code (stacked bases) won't reproduce. Both arms are affected equally.
- `replay.py` strips gateway/PostHog env vars so backtest runs never emit production analytics events.
