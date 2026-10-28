# Signal grouping eval

Offline runs publish to PostHog's offline experiments API through the shared eval-harness publisher.
Read [offline evaluation reporting](../../../docs/internal/ai-offline-evaluation-reporting.md#signals-pytest-suites)
for the two suites, pinned scorer versions, upload credentials, and result layout.

End-to-end evaluation of the signal grouping pipeline.
Measures how well the pipeline clusters incoming signals into reports, compared against hand-labeled ground-truth groups.

## What it tests

The eval feeds 111 synthetic signals (from 48 ground-truth groups) through the **real** pipeline:
LLM query generation, embedding search, LLM matching, specificity verification, summarization, safety judging, and actionability judging.
Infrastructure is mocked — an in-memory embedding store (`mock.py`) replaces ClickHouse + Kafka, and a `ReportStore` replaces Postgres.

Signals arrive in a deterministic random order (seeded RNG),
interleaved across groups to simulate real-world arrival patterns.

### Pipeline stages per signal

1. **Pre-emit** — summarize long descriptions, check actionability (Claude Haiku via the Go ai-gateway).
   Signals that fail actionability are dropped.
2. **Match** — generate search queries (LLM), embed queries (OpenAI),
   cosine search against stored signals, LLM match to existing report or create new, verify specificity of match (LLM).
3. **Persist** — store the signal + embedding, update report metadata.

After all signals are processed:

4. **Judge** — for each report: summarize signals (LLM),
   judge safety (prompt injection detection), judge actionability.

## How to run

```bash
# Full run — uploads results to PostHog offline experiments
pytest products/signals/eval/eval_grouping_e2e.py -xvs

# Quick test — 10 signals, no capture
pytest products/signals/eval/eval_grouping_e2e.py -xvs --limit 10 --no-capture
```

### Required environment variables

Set in `.env` at the repo root (loaded automatically).
The gateway token expires, so pass it per run instead: `AI_GATEWAY_API_KEY=$(hogli gateway:token) pytest ...`.

| Variable                       | Purpose                                                                                        |
| ------------------------------ | ---------------------------------------------------------------------------------------------- |
| `OPENAI_API_KEY`               | Embeddings (text-embedding-3-small)                                                            |
| `AI_GATEWAY_URL`               | Go ai-gateway base URL with `/v1`, e.g. `https://ai-gateway.us.posthog.com/v1` (all LLM calls) |
| `AI_GATEWAY_API_KEY`           | Developer-mode `phe_` token from `hogli gateway:token` (8h TTL, $25 per token, $50 per day)    |
| `SIGNALS_EVAL_TEAM_ID`         | Team id used for LLM cost attribution headers (defaults to `1`)                                |
| `POSTHOG_OFFLINE_EVAL_API_KEY` | Offline result uploads; requires `offline_evaluation_ingestion:write`                          |
| `POSTHOG_OFFLINE_EVAL_HOST`    | Offline API origin (defaults to `https://us.posthog.com`; project `2`)                         |
| `POSTHOG_PROJECT_API_KEY`      | Optional LLM trace capture                                                                     |
| `POSTHOG_HOST`                 | Trace destination (defaults to `http://localhost:8010`)                                        |

### CLI options

| Flag           | Effect                                           |
| -------------- | ------------------------------------------------ |
| `--limit N`    | Process only the first N signals from the stream |
| `--no-capture` | Skip offline uploads and trace capture           |

## What it produces

### Progress output (stderr)

Two tqdm progress bars:

- **Matching** — per-signal progress with `processing` (in-flight) and `dropped` (filtered/failed) counters
- **Judging** — per-report progress

Followed by an aggregate results summary table.

### Eval metrics uploaded to PostHog

Offline runs produce one experiment per suite, with items for each stage and aggregate statistics.
The table below lists grouping stage names. Inspect each run in the offline experiments UI.

| Stage                          | Granularity | Metrics                                                                                                                                                                                                 |
| ------------------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `match-quality`                | Per-signal  | `correct_match` (binary), `correct_match_pre_specificity` (binary), failure mode: NONE/UNDERGROUP/OVERGROUP, `query_diversity` (numeric, cosine distance), `candidate_diversity` (numeric, 1 − Jaccard) |
| `signal-safety-filter`         | Per-signal  | `signal_safety_correct_classification` (binary) — safety filter vs ground truth                                                                                                                         |
| `{source}-actionability-check` | Per-signal  | `actionability_correct_classification` (binary) — pre-emit filter vs ground truth                                                                                                                       |
| `grouping-quality`             | Per-report  | `purity`, `is_pure`, `group_recall`                                                                                                                                                                     |
| `report-safety-check`          | Per-report  | `report_safety_correct_classification` (binary) — safety judge vs ground truth                                                                                                                          |
| `grouping-aggregate`           | Global      | `ari`, `homogeneity`, `completeness`, `mean_purity`, `mean_group_recall`, `malicious_leaked_rate`                                                                                                       |

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
| `eval_grouping_e2e.py`      | Test class, pipeline orchestration, metric recording                              |
| `eval_scout_safety.py`      | Scout safety cases and aggregate metrics                                          |
| `conftest.py`               | pytest fixtures: API clients, CLI options, mock temporal                          |
| `mock.py`                   | `EmbeddingStore` (in-memory vector store) and `ReportStore` (in-memory report DB) |
| `offline.py`                | Adapts completed metrics to the shared offline publisher                          |
| `offline_config.py`         | Destination project and pinned scorer versions                                    |
| `data_spec.py`              | `EvalSignalSpec` / `EvalGroupSpec` — signal and group specifications              |
| `fixtures/grouping_data.py` | Ground-truth: 48 groups, 111 signals across Zendesk/GitHub/Linear/error tracking  |
| `cache/embeddings.json`     | Disk cache for OpenAI embeddings (auto-generated, avoids redundant API calls)     |

## Concurrency model

- Signals run through the pipeline concurrently (semaphore-bounded, 70 max).
- The match + persist step is serialized behind `asyncio.Lock` —
  this ensures the embedding store and report store see a consistent view when deciding whether a signal joins an existing report or creates a new one.
- Report judging runs concurrently (all reports at once).
