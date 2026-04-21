# pi-clickhouse-autoresearch

Reusable pi package for orchestrating ClickHouse query optimization campaigns on top of `pi-autoresearch`.

## What this package contains

- **Skill**: `clickhouse-autoresearch-campaign`
- **Prompt templates**:
  - `/next-experiment`
  - `/lane-review`
  - `/campaign-review`
- **Helper scripts** for campaign scaffolding plus commented workflow placeholders for baseline capture, candidate runs, and result comparison
- **Workspace templates** showing the contract between prompts and scripts

## Design goals

- One **campaign** per git branch
- One canonical **best query** per campaign
- A dynamic backlog of **lanes** and **hypotheses**
- Deterministic scripts for evidence capture and comparison
- Agent-driven reasoning for prioritization, reflection, repair, and closure

## Quick start

1. Install `pi-autoresearch`
2. Install this package
3. Start a new branch for the query campaign
4. Run the init helper to scaffold `.clickhouse-autoresearch/`
5. Fill in `.clickhouse-autoresearch/adapter.env`
6. Capture the baseline
7. Run the skill

Example:

```bash
git checkout -b autoresearch/query-abc123
pi install /path/to/pi-clickhouse-autoresearch
bash /path/to/pi-clickhouse-autoresearch/scripts/ch_campaign_init.sh \
  --workspace .clickhouse-autoresearch \
  --query-id query-abc123 \
  --query-file /tmp/slow-query.sql
bash /path/to/pi-clickhouse-autoresearch/scripts/ch_capture_baseline.sh \
  --workspace .clickhouse-autoresearch
```

Then in pi:

```text
/skill:clickhouse-autoresearch-campaign
```

## Package layout

```text
pi-clickhouse-autoresearch/
  docs/
    orchestration.md
    interface.md
  prompts/
    next-experiment.md
    lane-review.md
    campaign-review.md
  scripts/
    ch_campaign_init.sh
    ch_capture_baseline.sh
    ch_run_candidate.sh
    ch_compare_results.sh
    lib/common.sh
  skills/
    clickhouse-autoresearch-campaign/
      SKILL.md
  templates/
    workspace/
      ...
```

## Where the boundary is

- **The skill / prompts** decide:
  - what bottleneck to pursue
  - which lane is active
  - what hypothesis to test next
  - whether a wrong-but-fast result deserves repair
  - whether a lane or campaign should continue

- **The scripts** do deterministic work:
  - create campaign files
  - invoke environment-specific ClickHouse commands via `adapter.env`
  - capture baseline artifacts
  - run candidate queries
  - emit `METRIC ...` lines for `pi-autoresearch`
  - compare candidate results to the saved baseline result set

## Environment-specific integration

This package is intentionally generic. The shipped workflow scripts are scaffolds with comments and file contracts, not finished ClickHouse integrations. You provide the real ClickHouse commands and logic in:

```text
.clickhouse-autoresearch/adapter.env
```

The helper scripts expand placeholders like:

- `{workspace}`
- `{query_file}`
- `{candidate_file}`
- `{result_file}`
- `{metrics_file}`
- `{profile_dir}`
- `{stdout_file}`
- `{baseline_result_file}`
- `{comparison_file}`
- `{run_dir}`

See `docs/interface.md` for the complete contract.
