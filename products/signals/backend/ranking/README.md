# Inbox ranking: serving side

Scores Self-driving Inbox reports with the champion model the training dag publishes (`products/signals/dags/inbox_ranking/training/`). Shadow mode: scores are written, nothing orders the inbox by them yet.

```text
ranking/
├── features.py     # the feature universe; training and serving both build vectors here
├── inventory.py    # which reports are inbox inventory / scorable (shared with the dataset dag)
├── judgments.py    # latest priority/actionability per report (shared with the dataset dag)
├── model_store.py  # S3 key layout, champion loading, feature-contract asserts
├── scorer.py       # SignalReport rows -> feature vectors -> p_<head>
├── sweep.py        # the Temporal workflow + activity that scores due reports
└── schedule.py     # the interval schedule that drives the sweep
```

## What a tick does

`InboxRankingScoringWorkflow` runs every `SIGNALS_RANKING_SWEEP_INTERVAL_MINUTES` on the signals task queue and calls one activity, which:

1. returns immediately unless `SIGNALS_RANKING_SCORING_ENABLED` is on;
2. loads `inbox_ranking_models/v1/champion.json` and the readable heads' boosters from the dataset bucket, refusing any artifact whose `feature_schema_version` or feature names differ from `features.py` (`ModelContractError`) - a silent mismatch would score confidently and wrongly;
3. selects reports due for scoring: scorable inventory (`inventory.py`), created within `SIGNALS_RANKING_SCORE_MAX_AGE_DAYS`, and never scored / changed since the last score (`updated_at` moves on signal ingestion and status changes) / last scored more than `SIGNALS_RANKING_RESCORE_HOURS` ago, oldest first, up to `SIGNALS_RANKING_SCORE_BATCH_LIMIT`;
4. builds the same feature row the dataset dag snapshots (`scorer.report_feature_row`), predicts every readable head, and appends one `SignalReportScore` per report with the feature vector, the head probabilities, the model version and the feature schema version.

`SignalReportScore` is append-only: rows are never updated, so the table is the point-in-time record of what the model believed and when. That is what the online shadow read joins impressions against, and what the next training run learns from once it has accrued.

## Promoting a champion

The training dag writes a candidate every day but only rewrites `champion.json` when `INBOX_RANKING_AUTO_PROMOTE` is on. To promote by hand, copy a candidate's `metadata.json` to `inbox_ranking_models/v1/champion.json` and add a `promoted_at` timestamp; the next tick picks it up.

## Access

The sweep reads the bucket with the same client rules as the dag (`ranking_s3_client`): ambient AWS config when `INBOX_RANKING_DATASET_S3_BUCKET` is set, the deployment's object-storage service otherwise. The Temporal worker's role needs read access to the bucket before the sweep can load anything on Cloud.
