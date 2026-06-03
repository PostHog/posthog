# Signal grouping eval

End-to-end evaluation of the signal grouping pipeline.
Measures how well the pipeline clusters incoming signals into reports,
compared against hand-labeled ground-truth groups.

## What it tests

The eval feeds 92 synthetic signals (from 42 ground-truth groups) through the **real** pipeline:
LLM query generation, embedding search, LLM matching, specificity verification, summarization,
safety judging, and actionability judging.
Infrastructure is mocked — an in-memory embedding store (`mock.py`) replaces ClickHouse + Kafka,
and a `ReportStore` replaces Postgres.

Signals arrive in a deterministic random order (seeded RNG),
interleaved across groups to simulate real-world arrival patterns.

### Pipeline stages per signal

1. **Pre-emit** — summarize long descriptions, check actionability (Gemini).
   Signals that fail actionability are dropped.
2. **Match** — generate search queries (LLM), embed queries (OpenAI),
   cosine search against stored signals, LLM match to existing report or create new,
   verify specificity of match (LLM).
3. **Persist** — store the signal + embedding, update report metadata.

After all signals are processed:

4. **Judge** — for each report: summarize signals (LLM),
   judge safety (prompt injection detection), judge actionability.

## How to run

```bash
# Full run — captures eval results to PostHog
pytest products/signals/eval/eval_grouping_e2e.py -xvs

# Quick test — 10 signals, no capture
pytest products/signals/eval/eval_grouping_e2e.py -xvs --limit 10 --no-capture

# Online eval mode (tags results as "online" instead of "offline")
pytest products/signals/eval/eval_grouping_e2e.py -xvs --online
```

### Required environment variables

Set in `.env` at the repo root (loaded automatically):

| Variable                  | Purpose                                                |
| ------------------------- | ------------------------------------------------------ |
| `ANTHROPIC_API_KEY`       | LLM calls (matching, specificity, summarization)       |
| `OPENAI_API_KEY`          | Embeddings (text-embedding-3-small)                    |
| `GEMINI_API_KEY`          | Actionability check                                    |
| `POSTHOG_PROJECT_API_KEY` | Capturing eval results (skip with `--no-capture`)      |
| `POSTHOG_HOST`            | PostHog instance (defaults to `http://localhost:8010`) |

### CLI options

| Flag           | Effect                                                 |
| -------------- | ------------------------------------------------------ |
| `--limit N`    | Process only the first N signals from the stream       |
| `--no-capture` | Skip emitting `$ai_evaluation` events to PostHog       |
| `--online`     | Tag captured results as online eval (default: offline) |

## What it produces

### Progress output (stderr)

Two tqdm progress bars:

- **Matching** — per-signal progress with `processing` (in-flight) and `dropped` (filtered/failed) counters
- **Judging** — per-report progress

Followed by an aggregate results summary table.

### Eval metrics captured to PostHog

All metrics are captured as `$ai_evaluation` events with source `signals-grouping`.
Five eval experiments, each with their own metrics:

| Experiment                     | Granularity | Metrics                                                                                                                                                                                                 |
| ------------------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `match-quality`                | Per-signal  | `correct_match` (binary), `correct_match_pre_specificity` (binary), failure mode: NONE/UNDERGROUP/OVERGROUP, `query_diversity` (numeric, cosine distance), `candidate_diversity` (numeric, 1 − Jaccard) |
| `{source}-actionability-check` | Per-signal  | `correct_classification` (binary) — did pre-emit filter agree with ground truth                                                                                                                         |
| `grouping-quality`             | Per-report  | `purity`, `is_pure`, `group_recall`                                                                                                                                                                     |
| `report-safety-check`          | Per-report  | `correct_classification` (binary) — safety judge vs ground truth                                                                                                                                        |
| `report-actionability-check`   | Per-report  | `correct_classification` (binary) — actionability judge vs ground truth                                                                                                                                 |
| `grouping-aggregate`           | Global      | `ari`, `homogeneity`, `completeness`, `mean_purity`, `group_recall`, `malicious_leaked_rate`                                                                                                            |

### Aggregate metrics explained

- **ARI** (adjusted rand index) — chance-corrected clustering similarity, -1 to 1
- **Homogeneity** — each report contains only signals from one true group (1.0 = no overgrouping)
- **Completeness** — all signals from a true group land in the same report (1.0 = no undergrouping)
- **Mean purity** — average fraction of dominant group per report
- **Mean recall** — average fraction of a group's signals captured by its best report
- **Malicious leaked rate** — fraction of unsafe signals that made it through unblocked

## File structure

| File                        | Purpose                                                                           |
| --------------------------- | --------------------------------------------------------------------------------- |
| `eval_grouping_e2e.py`      | Test class, pipeline orchestration, metric capture                                |
| `conftest.py`               | pytest fixtures: API clients, CLI options, mock temporal                          |
| `mock.py`                   | `EmbeddingStore` (in-memory vector store) and `ReportStore` (in-memory report DB) |
| `capture.py`                | `capture_evaluation()` helper — formats and sends `$ai_evaluation` events         |
| `data_spec.py`              | `EvalSignalSpec` / `EvalGroupSpec` — signal and group specifications              |
| `fixtures/grouping_data.py` | Ground-truth dataset: 42 groups, 92 signals across Zendesk/GitHub/Linear          |
| `cache/embeddings.json`     | Disk cache for OpenAI embeddings (auto-generated, avoids redundant API calls)     |

## Clearing eval data

To delete captured eval events from ClickHouse (DEBUG mode only):

```bash
python manage.py clear_eval_data --dry-run    # preview counts
python manage.py clear_eval_data --yes         # delete all
python manage.py clear_eval_data --source X    # filter by eval source tag
```

## Concurrency model

- Signals run through the pipeline concurrently (semaphore-bounded, 70 max).
- The match + persist step is serialized behind `asyncio.Lock` —
  this ensures the embedding store and report store see a consistent view
  when deciding whether a signal joins an existing report or creates a new one.
- Report judging runs concurrently (all reports at once).

# Reports

## HogQL queries

All queries filter on `$ai_eval_source = 'signals-grouping'` and `$ai_evaluation_type = 'offline'`.
Run these in the PostHog SQL editor.

### Aggregate metrics

ARI, homogeneity, completeness, purity, recall, malicious leak rate.

```sql
SELECT
    properties.$ai_metric_name AS metric,
    properties.$ai_score AS score,
    properties.$ai_metric_description AS description,
    properties.$ai_reasoning AS reasoning,
    properties.$ai_input AS input,
    properties.$ai_output AS output,
    properties.$ai_expected AS expected
FROM events
WHERE event = '$ai_evaluation'
  AND properties.$ai_eval_source = 'signals-grouping'
  AND properties.$ai_evaluation_type = 'offline'
  AND properties.$ai_experiment_name = 'signals-grouping/grouping-aggregate'
ORDER BY metric
```

### Match quality failure mode breakdown

```sql
SELECT
    multiIf(
        properties.$ai_score = 1.0, 'CORRECT',
        properties.$ai_reasoning LIKE '%UNDERGROUP%', 'UNDERGROUP',
        properties.$ai_reasoning LIKE '%OVERGROUP%', 'OVERGROUP',
        'UNKNOWN'
    ) AS failure_mode,
    count() AS cnt,
    round(count() * 100.0 / (SELECT count() FROM events WHERE event = '$ai_evaluation' AND properties.$ai_eval_source = 'signals-grouping' AND properties.$ai_evaluation_type = 'offline' AND properties.$ai_experiment_name = 'signals-grouping/match-quality'), 1) AS pct
FROM events
WHERE event = '$ai_evaluation'
  AND properties.$ai_eval_source = 'signals-grouping'
  AND properties.$ai_evaluation_type = 'offline'
  AND properties.$ai_experiment_name = 'signals-grouping/match-quality'
  AND properties.$ai_metric_name = 'correct_match'
GROUP BY failure_mode
ORDER BY cnt DESC
```

### Specificity judge impact

Compares pre- and post-specificity correctness to show
how often the specificity judge helps (prevents overgroup),
hurts (causes undergroup), or has no effect.

```sql
SELECT
    multiIf(
        pre.score = 1.0 AND post.score = 1.0, 'no_effect_correct',
        pre.score = 0.0 AND post.score = 0.0 AND pre.reasoning = post.reasoning, 'no_effect_wrong',
        pre.score = 0.0 AND post.score = 1.0, 'prevented_overgroup',
        pre.score = 1.0 AND post.score = 0.0, 'caused_undergroup',
        pre.score = 0.0 AND post.score = 0.0, 'changed_failure_mode',
        'unknown'
    ) AS specificity_impact,
    count() AS cnt
FROM (
    SELECT properties.$ai_experiment_item_name AS item, properties.$ai_score AS score, properties.$ai_reasoning AS reasoning
    FROM events
    WHERE event = '$ai_evaluation' AND properties.$ai_eval_source = 'signals-grouping' AND properties.$ai_evaluation_type = 'offline'
      AND properties.$ai_experiment_name = 'signals-grouping/match-quality' AND properties.$ai_metric_name = 'correct_match_pre_specificity'
) pre
JOIN (
    SELECT properties.$ai_experiment_item_name AS item, properties.$ai_score AS score, properties.$ai_reasoning AS reasoning
    FROM events
    WHERE event = '$ai_evaluation' AND properties.$ai_eval_source = 'signals-grouping' AND properties.$ai_evaluation_type = 'offline'
      AND properties.$ai_experiment_name = 'signals-grouping/match-quality' AND properties.$ai_metric_name = 'correct_match'
) post ON pre.item = post.item
GROUP BY specificity_impact
ORDER BY cnt DESC
```

### Query and candidate diversity

```sql
SELECT
    properties.$ai_metric_name AS metric,
    count() AS n,
    round(avg(properties.$ai_score), 3) AS mean,
    round(min(properties.$ai_score), 3) AS min,
    round(max(properties.$ai_score), 3) AS max
FROM events
WHERE event = '$ai_evaluation'
  AND properties.$ai_eval_source = 'signals-grouping'
  AND properties.$ai_evaluation_type = 'offline'
  AND properties.$ai_experiment_name = 'signals-grouping/match-quality'
  AND properties.$ai_metric_name IN ('query_diversity', 'candidate_diversity')
GROUP BY metric
ORDER BY metric
```

### Pre-emit actionability by source type

```sql
SELECT
    replaceOne(properties.$ai_experiment_name, 'signals-grouping/', '') AS check_name,
    count() AS total,
    countIf(properties.$ai_score = 1.0) AS correct,
    countIf(properties.$ai_score != 1.0) AS failures,
    round(countIf(properties.$ai_score != 1.0) * 100.0 / count(), 1) AS failure_pct,
    countIf(properties.$ai_score != 1.0 AND properties.$ai_output = 'ACTIONABLE') AS false_positives,
    countIf(properties.$ai_score != 1.0 AND properties.$ai_output = 'NOT_ACTIONABLE') AS false_negatives
FROM events
WHERE event = '$ai_evaluation'
  AND properties.$ai_eval_source = 'signals-grouping'
  AND properties.$ai_evaluation_type = 'offline'
  AND properties.$ai_experiment_name IN (
      'signals-grouping/zendesk-actionability-check',
      'signals-grouping/github-actionability-check',
      'signals-grouping/linear-actionability-check'
  )
  AND properties.$ai_metric_name = 'correct_classification'
GROUP BY check_name
ORDER BY check_name
```

### Report-level judges (safety + actionability)

```sql
SELECT
    replaceOne(properties.$ai_experiment_name, 'signals-grouping/', '') AS judge,
    count() AS total,
    countIf(properties.$ai_score = 1.0) AS correct,
    round(countIf(properties.$ai_score = 1.0) * 100.0 / count(), 1) AS accuracy_pct,
    countIf(properties.$ai_score != 1.0 AND properties.$ai_output IN ('SAFE', 'IMMEDIATELY_ACTIONABLE')) AS false_positives,
    countIf(properties.$ai_score != 1.0 AND properties.$ai_output NOT IN ('SAFE', 'IMMEDIATELY_ACTIONABLE')) AS false_negatives
FROM events
WHERE event = '$ai_evaluation'
  AND properties.$ai_eval_source = 'signals-grouping'
  AND properties.$ai_evaluation_type = 'offline'
  AND properties.$ai_experiment_name IN (
      'signals-grouping/report-safety-check',
      'signals-grouping/report-actionability-check'
  )
  AND properties.$ai_metric_name = 'correct_classification'
GROUP BY judge
ORDER BY judge
```

### Per-report grouping quality

Purity, is_pure, group_recall distributions.

```sql
SELECT
    properties.$ai_metric_name AS metric,
    count() AS n,
    round(avg(properties.$ai_score), 3) AS mean_score,
    round(min(properties.$ai_score), 3) AS min_score,
    round(max(properties.$ai_score), 3) AS max_score,
    countIf(properties.$ai_score = 1.0) AS perfect_count
FROM events
WHERE event = '$ai_evaluation'
  AND properties.$ai_eval_source = 'signals-grouping'
  AND properties.$ai_evaluation_type = 'offline'
  AND properties.$ai_experiment_name = 'signals-grouping/grouping-quality'
GROUP BY metric
ORDER BY metric
```

### Detailed match failures (for debugging)

```sql
SELECT
    properties.$ai_experiment_item_name AS item,
    properties.$ai_reasoning AS failure_mode,
    properties.$ai_input AS signal_description,
    properties.$ai_expected AS expected,
    JSONExtractString(properties.$ai_output, 'report') AS actual_decision
FROM events
WHERE event = '$ai_evaluation'
  AND properties.$ai_eval_source = 'signals-grouping'
  AND properties.$ai_evaluation_type = 'offline'
  AND properties.$ai_experiment_name = 'signals-grouping/match-quality'
  AND properties.$ai_metric_name = 'correct_match'
  AND properties.$ai_score != 1.0
ORDER BY properties.$ai_reasoning, item
```
