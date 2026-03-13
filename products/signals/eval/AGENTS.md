# Signals eval

End-to-end evaluation for the signal grouping pipeline.

## Purpose

Measures how well the grouping pipeline clusters related signals into reports.
Synthetic signals with known ground-truth groupings are fed through the **real** pipeline
(real Anthropic LLM calls for matching/specificity, real OpenAI embeddings)
while only infrastructure is mocked (ClickHouse, Temporal, embedding worker).
Results are emitted as `$ai_evaluation` events viewable in LLM analytics offline evals.

## Usage

```bash
pytest products/signals/eval/eval_grouping_e2e.py -x -s --log-cli-level=WARNING
```

Requires `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `POSTHOG_PROJECT_API_KEY` in the environment (or `.env`).

| Flag           | Description                                         |
| -------------- | --------------------------------------------------- |
| `--limit N`    | Process only the first N signals (faster iteration) |
| `--no-capture` | Skip emitting eval results to PostHog               |

## Synthetic dataset

Defined in `fixtures/grouping_data.py` as a list of `GroupSpec` objects.
Each group represents a distinct scenario (bug, feature request, etc.) with multiple signals
written in different styles and from different sources.

| Group | Scenario                                           | Signals | Sources                 |
| ----- | -------------------------------------------------- | ------- | ----------------------- |
| 0     | Date picker timezone bug                           | 3       | Zendesk, GitHub         |
| 1     | Funnel conversion calculation bug                  | 4       | Zendesk, GitHub, Linear |
| 2     | Feature flag evaluation slow for large orgs        | 2       | Zendesk                 |
| 3     | Session replay click detection issues              | 3       | GitHub, Zendesk, Linear |
| 4     | HogQL missing arrayDistinct (singleton)            | 1       | GitHub                  |
| 5     | Export to CSV/PDF broken                           | 3       | Zendesk                 |
| 6     | Webhook delivery unreliable (singleton)            | 1       | Zendesk                 |
| 7     | Cohort calculation stuck/stale                     | 3       | Zendesk, GitHub         |
| 8     | Group analytics property filter broken (singleton) | 1       | Linear                  |
| 9     | Data warehouse Stripe sync failures                | 2       | Zendesk, GitHub         |

**10 groups, 23 signals total.**
Signals are interleaved randomly (seeded) across groups during the eval to simulate realistic arrival order.

Signals vary by:

- **Source** — Zendesk tickets, GitHub issues, Linear issues
- **Style** — bug reports, support tickets, feature requests
- **Specificity** — some are vague end-user reports, others are detailed engineering investigations

Three groups are singletons (1 signal each) to test that the pipeline creates new reports rather than incorrectly merging unrelated signals.

## Key files

| File                        | Description                                                                  |
| --------------------------- | ---------------------------------------------------------------------------- |
| `eval_grouping_e2e.py`      | Main eval test — emits signals, computes metrics, captures results           |
| `mock.py`                   | Mock infrastructure — in-memory ClickHouse, Temporal bypass, embedding cache |
| `capture.py`                | `EvalMetric` and `capture_evaluation` for emitting `$ai_evaluation` events   |
| `data_spec.py`              | `SignalSpec`, `GroupSpec`, `SourceProducts`, `SourceTypes`                   |
| `fixtures/grouping_data.py` | The synthetic dataset                                                        |
| `conftest.py`               | Pytest config, env loading, API key setup                                    |
| `cache/embeddings.json`     | Disk-backed embedding cache (avoids redundant OpenAI calls)                  |
