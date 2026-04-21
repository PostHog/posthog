# Prompt ↔ Script Interface

This package separates **reasoning** from **execution**.

- The **skill / prompts / agent** own campaign reasoning.
- The **scripts** own deterministic filesystem and command execution.

## Ownership model

### Agent-owned files

The agent may create or edit:

- `campaign.json` for static campaign metadata
- `state.json` for evolving campaign state
- `query/current.sql` and `query/best.sql`
- `operator-hunches.md`
- `lanes/*.md`
- `hypotheses/*.md`
- `reviews/*.md`
- `autoresearch.md`

### Script-owned files

The scripts create or overwrite:

- `baseline/**`
- `runs/**`
- `runtime/**`
- `autoresearch.sh`
- `autoresearch.checks.sh`
- `adapter.env` on init only if missing

Do not hand-edit `runtime/*.json` unless you are intentionally repairing broken runtime state.

## Workspace layout

```text
.clickhouse-autoresearch/
  adapter.env
  campaign.json
  operator-hunches.md
  state.json
  query/
    original.sql
    current.sql
    best.sql
  baseline/
    result.tsv
    metrics.json
    stdout.log
    profile/
  runs/
    run-0001-baseline-candidate/
      result.tsv
      metrics.json
      comparison.json
      stdout.log
      profile/
  runtime/
    last_run.json
  lanes/
  hypotheses/
  reviews/
  autoresearch.md
  autoresearch.sh
  autoresearch.checks.sh
```

## Deterministic script entrypoints

The package currently ships these as commented scaffolds. They define the workflow boundary and the expected files, but you are expected to replace the TODO sections with your real ClickHouse execution and comparison logic.

### 1. `scripts/ch_campaign_init.sh`

Scaffolds a campaign workspace and root-level `autoresearch.config.json`.

#### Inputs

- `--workspace <path>` required
- `--query-id <id>` required
- `--query-file <path>` optional, copied to `query/original.sql`
- `--primary-metric <name>` optional, default `latency_ms`
- `--metric-unit <unit>` optional, default `ms`
- `--direction <lower|higher>` optional, default `lower`
- `--branch-name <name>` optional, defaults to current git branch
- `--lane-stagnation-window <n>` optional, default `4`
- `--campaign-stagnation-window <n>` optional, default `8`
- `--max-total-iterations <n>` optional, default `30`
- `--significant-improvement-pct <number>` optional, default `3`
- `--repair-budget <n>` optional, default `2`

#### Outputs

Creates the workspace files and wrapper scripts.

### 2. `scripts/ch_capture_baseline.sh`

Runs the environment-specific baseline capture command from `adapter.env`.

#### Inputs

- `--workspace <path>` required
- reads `query/original.sql`
- reads `adapter.env`
- reads `campaign.json`

#### Writes

- `baseline/result.tsv`
- `baseline/metrics.json`
- `baseline/stdout.log`
- `baseline/profile/**`
- `runtime/last_run.json` with `kind: "baseline"`

### 3. `scripts/ch_run_candidate.sh`

Runs the current candidate query, captures artifacts, compares results, and emits `METRIC ...` lines for `pi-autoresearch`.

#### Inputs

- `--workspace <path>` required
- `--label <label>` optional
- reads `query/current.sql`
- reads `adapter.env`
- reads `campaign.json`
- reads `baseline/result.tsv`

#### Writes

- `runs/run-XXXX[-label]/result.tsv`
- `runs/run-XXXX[-label]/metrics.json`
- `runs/run-XXXX[-label]/stdout.log`
- `runs/run-XXXX[-label]/profile/**`
- `runs/run-XXXX[-label]/comparison.json`
- `runtime/last_run.json` with pointers to those files

#### Stdout contract

The script prints:
- a short human-readable summary
- zero or more `METRIC name=value` lines parsed by `pi-autoresearch`

### 4. `scripts/ch_compare_results.sh`

Compares a candidate result set to the saved baseline result set.

#### Inputs

- `--workspace <path>` required
- `--candidate-result <path>` optional; defaults to the last run result from `runtime/last_run.json`
- reads `baseline/result.tsv`
- optionally reads `adapter.env`

#### Writes

- a comparison JSON file either inside the current run directory or at the caller-provided path

#### Exit code

- `0` means results match
- `1` means results differ
- `>1` means the comparison process failed

If `CH_COMPARE_RESULTS_CMD` is not configured, the default behavior is exact byte comparison.

## `adapter.env` contract

`adapter.env` is the environment-specific integration layer.

It is sourced by the scripts and may define:

```bash
CH_CAPTURE_BASELINE_CMD='...'
CH_RUN_CANDIDATE_CMD='...'
CH_COMPARE_RESULTS_CMD='...'
```

Each command is a shell template. The scripts replace placeholders before execution.

### Supported placeholders

- `{workspace}`
- `{campaign_file}`
- `{query_file}`
- `{candidate_file}`
- `{result_file}`
- `{metrics_file}`
- `{profile_dir}`
- `{stdout_file}`
- `{baseline_result_file}`
- `{comparison_file}`
- `{run_dir}`
- `{label}`

### Example shape

```bash
CH_RUN_CANDIDATE_CMD='clickhouse-client --queries-file {candidate_file} > {result_file} 2> {stdout_file}; ./collect-metrics.sh {stdout_file} > {metrics_file}'
```

The package does not prescribe one ClickHouse transport. You can use:
- `clickhouse-client`
- HTTP API
- a wrapper script
- a remote SSH command
- a Kubernetes exec wrapper

## JSON output schemas

### `metrics.json`

Expected shape:

```json
{
  "primary": {
    "name": "latency_ms",
    "value": 1834.2,
    "unit": "ms"
  },
  "secondary": {
    "rows_read": 12700344,
    "bytes_read": 934002112,
    "peak_memory_mb": 512
  },
  "notes": "optional short machine-readable summary"
}
```

Rules:
- `primary.name` should match the name used in the autoresearch session
- `primary.value` must be numeric
- `secondary` values must be numeric if present

### `comparison.json`

Expected shape:

```json
{
  "matches": true,
  "mode": "adapter",
  "summary": "exact match",
  "details": {
    "rows_baseline": 124,
    "rows_candidate": 124
  }
}
```

Minimal valid shape:

```json
{
  "matches": false,
  "summary": "candidate produced 3 extra rows"
}
```

### `runtime/last_run.json`

Expected shape:

```json
{
  "kind": "candidate",
  "run_id": "run-0007-pruning",
  "label": "pruning",
  "run_dir": ".clickhouse-autoresearch/runs/run-0007-pruning",
  "result_file": ".clickhouse-autoresearch/runs/run-0007-pruning/result.tsv",
  "metrics_file": ".clickhouse-autoresearch/runs/run-0007-pruning/metrics.json",
  "comparison_file": ".clickhouse-autoresearch/runs/run-0007-pruning/comparison.json"
}
```

## `autoresearch.sh` and `autoresearch.checks.sh`

The workspace wrappers are generated by `ch_campaign_init.sh`.

### `autoresearch.sh`

Responsibility:
- call `ch_run_candidate.sh`
- let that script emit `METRIC ...` lines

### `autoresearch.checks.sh`

Responsibility:
- read `runtime/last_run.json`
- read the referenced `comparison.json`
- exit `0` when `matches == true`
- exit `1` with a concise summary when `matches == false`

This keeps correctness checks separate from benchmark timing while preserving enough signal for the agent to decide whether a wrong-but-fast candidate is worth repairing.

## Agent responsibilities at runtime

The agent should:
1. update `query/current.sql`
2. maintain `state.json`, lane notes, and hypothesis notes
3. invoke `run_experiment` against `./autoresearch.sh`
4. inspect the latest `runs/**` artifacts when needed
5. use `autoresearch.checks.sh` for correctness backpressure
6. record durable learning in `autoresearch.md` and `autoresearch.jsonl`

The scripts should not decide what to optimize next.
