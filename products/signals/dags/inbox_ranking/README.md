# Inbox ranking Dagster dags

Dagster jobs for the Self-driving Inbox report-ranking model: the **dataset** dag (daily snapshots), the **training** dag (daily per-head XGBoost candidates + champion pointer) and the **shadow** dag (the model's order against the order the inbox serves), sibling subpackages sharing `common.py`.

```text
inbox_ranking/
├── common.py       # shared: S3 destination config, daily partition def, gating, Parquet IO
├── dataset/
│   ├── dag.py      # the five dataset assets + job + schedule
│   └── queries.py  # HogQL label SQL, embeddings SQL, stream merging
├── training/
│   ├── dag.py        # examples → candidate → champion assets + job + schedule
│   ├── examples.py   # birth-grain training examples over the snapshots
│   ├── heads.py      # the v0 outcome heads
│   ├── train.py      # per-head XGBoost fit + holdout/null metrics
│   └── promotion.py  # the champion promotion rule
├── shadow/
│   ├── dag.py        # the shadow eval asset + job + schedule
│   ├── metrics.py    # served lists, outcome attribution, NDCG/MRR over three orders
│   ├── queries.py    # HogQL for the served lists and the engagements that followed
│   └── telemetry.py  # the shadow grade as an event
└── tests/
```

Registered via `posthog/dags/locations/signals.py` (US only) and loaded locally through `.dagster_home/workspace.yaml`.

## The dataset dag

`inbox_ranking_dataset_job` runs daily at 02:30 UTC (schedule default: running on prod US, stopped everywhere else — including hosted DEV and E2E, which have no dogfood project to read labels from) and builds six assets on one daily partition, each a Parquet object in S3:

```text
s3://<bucket>/<prefix>/
├── inbox_report_state/v1/dt=YYYY-MM-DD/       # Postgres spine + report state + tabular features
├── inbox_report_embeddings/v1/dt=YYYY-MM-DD/  # report_id -> small-1536 vector as of snapshot end
├── inbox_report_labels/v1/dt=YYYY-MM-DD/      # cumulative label columns from dogfood telemetry
├── inbox_report_model_data/v1/
│   ├── dt=YYYY-MM-DD/                         # materialized join of the three (the training table)
│   └── latest/                                # rewritten by the newest partition; warehouse tables point here
├── inbox_signal_embeddings/v1/dt=YYYY-MM-DD/  # one row per signal emitted during the day (signal grain)
└── inbox_report_title_embeddings/v1/dt=YYYY-MM-DD/  # the same shape, for the title-only rendering
```

The first four are report grain and land in one table. `inbox_signal_embeddings` is signal grain, feeds the group-level model, and is read on its own — training joins it to `inbox_report_model_data` by `report_id`.

`inbox_report_title_embeddings` is a report-grain leaf. It snapshots the `title_v1` rendering the same way `inbox_report_embeddings` snapshots `title_summary_v1`, and nothing joins it: the training side pairs the two by `report_id` when it measures one rendering against the other, and each carries its own `embedding_inserted_at`, because a summary-only edit re-emits only `title_summary_v1`. Its dependency on `inbox_report_model_data` is for ordering, not data — it holds a vector per live report, so it runs last and alone in the run pod.

### Partition semantics

- Partition `dt=D` snapshots the eligible report inventory (promoted before `D+1 00:00 UTC`, or referenced by any label event before it). Every label aggregate is bounded `event_time < D+1 00:00 UTC`.
- Label columns are **cumulative**: later partitions strictly dominate earlier ones, so training reads features from `dt=D` and labels from any later partition, choosing the label-maturity window at read time. Late labels are never backfilled into old partitions.
- `latest/` advances **monotonically**: each write stamps a `snapshot-date` in S3 object metadata, and a partition rewrites `latest/` only when it is at or ahead of what `latest/` holds. Delayed retries of the newest day repair it; backfills of older days never clobber it.
- Rows for reports **outside this dag's region** are label-only: no Postgres state, no embedding, and `report_team_id` null (a US team id and an EU team id of the same number are different teams, so the label stream's id can't be merged in). `status_event_team_id` carries the team the transition itself reported, which is the tenant attribution those rows do have.
- **Backfills are not fully point-in-time**: labels are exact for any past day, embeddings are exact within the source table's 3-month TTL, but report state is read from Postgres as of the run (`features_observed_at` flags this per row). The title snapshot has the same guarantee and the same limit as the report snapshot, through the same `inserted_at < snapshot_end` bound.
- **The `inserted_at` bound does not cover a re-embedded rendering.** The source replaces on a key that includes the rendering and the document id, so a partition rebuilt *later* for an earlier day finds only the newer row, whose `inserted_at` is past the cutoff, and the report reads as having no vector that day. That loses coverage and never leaks a future vector. Forward-run daily partitions are not affected. A partition before `title_v1` emission shipped holds zero rows, which is written as an empty Parquet with the full schema rather than skipped.
- Report-state mutability reaches **inclusion**, not just feature values: `promoted_at` is cleared on suppression and snooze, so a report promoted before the cutoff and suppressed after it leaves the spine unless a label event referenced it before the cutoff. Forward runs see this only for the 2.5 hours between the cutoff and the schedule; backfills see the full accumulated effect. Deriving the spine from immutable promotion history (`signal_report_status_changed` carries `promoted_at`) is the v2 fix.

### Signal-grain partitions

`inbox_signal_embeddings` is the one asset here whose partitions are **not** full snapshots. `dt=D` holds only the signal documents inserted during D — an emission log — because a cumulative copy at signal grain means a 1536-float vector per signal, fleet-wide, rewritten every day.

- Read the **union** of partitions and take the latest row per `(team_id, signal_id)` at or before the cutoff. `signal_id` (the ClickHouse `document_id`) is caller-supplied and only unique within a team, so the tenant key is part of the identity. That is the same `(team_id, document_id)` latest-wins the report assets do in SQL, moved to read time.
- **The log is best-effort, not complete.** The source is a ReplacingMergeTree versioned by `inserted_at`, and a retraction re-emits the signal under the same sort key, so a merge between the two writes keeps only the retraction. A signal whose report is deleted in the same window it was inserted reaches no partition in its live form, and no query shape recovers it: the merge has already dropped the row.
- The reverse gap is the TTL. A retraction inherits the original event timestamp, so retracting a signal more than three months old writes a row that is already expired and may never be scanned. **Absence of an `is_deleted` row is not proof that a signal is live**, and this archive is not authoritative for deletion — see the retention section below.
- The vectors' source TTL runs from **signal event time**, so this asset is also where signal vectors become durable. Whatever a partition does not capture before its signals age out is gone.
- Consequently **a re-run is additive**: it unions the fresh scan into the rows the partition already holds, keyed by `(team_id, signal_id, embedding_inserted_at)`, so a row the source can no longer supply survives. Overwriting with the scan alone would delete it permanently, and a row count cannot police that — a scan can lose one emission and gain another and land on the same total.
- The count check remains as a backstop: a union can only grow, so a smaller result means the merge itself is broken and the write is refused. Row counts are stamped in S3 object metadata at write time to make that check a `head_object`. A deliberate shrink still means deleting the object by hand.
- Signal text never leaves ClickHouse: the query selects the vector and the structured metadata (weight, source, match graph), not `content` or the free-text metadata fields.

## The training dag

`inbox_ranking_training_job` runs daily at 06:00 UTC on the same partition definition (gated like the dataset job) and writes:

```text
s3://<bucket>/<prefix>/
├── inbox_ranking_training_examples/v1/<feature_set>/dt=YYYY-MM-DD/  # one row per report at its birth, all heads, one parquet per feature set
├── inbox_ranking_models/v1/<model_name>/
│   ├── dt=YYYY-MM-DD/<head>.ubj + <head>.holdout.ubj    # the day's candidate: serving fit + train-only fit
│   │                  + metadata.json                     # (a re-run replaces this prefix in full)
│   └── champion.json                                     # pointer the scoring sweep loads (the only object written across partitions)
└── inbox_ranking_unseen_scores/v1/dt=YYYY-MM-DD/       # the day's models on the reports born that day
```

- **A model is a `(model_name, model_version, model_role)`.** `model_name` is the family: which features and which learner, `tabular_xgb` for the per-head XGBoost trained here. `model_version` is the partition day it was fit on, and `model_role` is `candidate` or `champion`. Each family owns a prefix under the models path and its own `champion.json`, so two families trained on the same day cannot collide, and promotion stays inside a family. A richer family is a second candidate graded on the same unseen rows, not a competitor for the tabular family's pointer.
- **A feature set is one feature universe.** `products/signals/backend/ranking/features.py` holds a `FeatureSet` per universe: its name, its schema version, its ordered feature names, the report-state columns it reads, `build_matrix`, and how many rows it wants per report and per head. `tabular` and `report_embeddings` are the two today. A candidate records the set it was fit on in its `metadata.json`, so the grader checks a model against its own set rather than one global contract, the examples asset writes one Parquet per set, and the unseen scorer builds one matrix per set and shares it across the families that read it. Adding a set means an entry in `FEATURE_SETS`; a model naming a set this build cannot produce is logged and left unscored.
- **Examples are one row per report at its birth, by default.** For partition `dt=D` the examples asset reads the report-state and labels snapshots `dt=D-lookback..D` and emits one row per report, on the snapshot of the day it was created, labeled from the snapshot `horizon_days` later (3 for open, 7 for action / pr_created / discuss, 14 for dismiss_wrong / pr_merged / refund). Features are built by the feature set from that snapshot's state columns plus `age_hours`, the report's age at the snapshot. Labels are aligned to the state spine, so a report with no label event is a negative (all-zero labels), not absent. Label-only rows (no Postgres state) are skipped, as are state rows read long after their snapshot day (backfills carry current Postgres state; see `features_observed_at`) and, for the `dismiss_wrong` head, rows whose status telemetry fails the dataset's `label_provenance_ok` check. Birth is the moment serving scores a report, and the label that comes out is a per-report probability, which is what the inbox ordering needs. A report born before the window, or one whose birth-day snapshot is missing from it, is no example; `reports_missing_birth_snapshot` on the asset counts the second case, which is a gap in the partitions.
- **An outcome already visible on the birth day is a future positive.** A report born on day D has no scoring moment before D, so an outcome visible at D belongs to the moment being built rather than to an earlier one; the labels of D therefore read as their defaults for a report born on D. Most outcomes land on the birth day, so this is where the positives are: censoring on them costs the `pr_created` head most of its training signal. `<set>_<head>_birth_day_positives` on the examples asset, and `birth_day_positives` on the `inbox_ranking_examples_built` event, say how many positives the rule keeps. These rows carry a hindsight the other rows do not: the state snapshot reads `signal_count`, `total_weight`, `run_count` and the text sizes live from Postgres a few hours after day D ends, so a birth-day outcome happened before its own feature read. Both the holdout AUC and the newborn unseen grade therefore read optimistically on these rows, until the scoring sweep's timestamped score log replaces the daily snapshot as this table's source.
- **Every head asks whether the outcome happened within N days of the scoring moment.** `pr_merged` includes every report, so the label covers the whole report-to-merge path without requiring a PR at birth or at the horizon.
- **A set may ask for another grain**, and cap the rows one head keeps (`max_examples_per_head`, all positives first, then a seeded sample of the negatives). The scoring-moment grain is one row per (report, snapshot) whose head label is still 0 on that snapshot: the serving situation replayed over history, but its label is a hazard conditional on the report still being live, and one long-lived report contributes dozens of near-duplicate rows. The report grain is the first snapshot of the window where the report is a usable moment, which is later than birth only when a side input landed late. Both stay selectable for re-scoring families; nothing ships on them today. The row budget changes the base rate a set's scores are calibrated to, not the ranking the unseen AUC reads. The lookback is the tabular set's whatever the grain, so positives accrue over the whole window.
- **`tabular` is the serving set** (the state counters, title/summary length, age, one-hot priority/actionability). No embedding, no impression-derived columns, so the scoring sweep needs only the `SignalReport` row and its judgment artefacts. The sweep must build features through the same module; the booster's `feature_names` are checked against it at load.
- **`report_embeddings` is the report's own vector and nothing else**, read from the dt=D `inbox_report_embeddings` snapshot as a side input. Age is deliberately left out: it is the whole signal of the `recency_auc` line the unseen read already reports, so a gap to that line is content rather than recency. The scoring sweep does not serve this set: it is an offline candidate, and serving it needs the report vector at scoring time.
- **A moment only takes a vector that already existed for it.** The snapshot holds the latest vector per report, and a report is re-embedded whenever its text changes (the summary workflow and every re-research run rewrite it), so the latest vector often postdates an earlier moment. Each row carries `embedding_inserted_at`, and a moment keeps the vector only when it landed at or before that snapshot's end; at the birth grain a report whose birth-day snapshot holds only a later vector is no example, and at the report grain it moves to the first snapshot where the vector was already its own. Without that check the family would train on text that did not exist when the report was supposedly scored. A report the snapshot has no vector for at all is not an example either, because the source table's TTL runs from report creation and a long-lived report loses its vector while still live. The scores asset records each set's coverage of the newborn pool, so a thin side input is visible rather than silent.
- **A set whose side input is unavailable is skipped, not rebuilt from nothing.** The examples asset writes no object for it, the candidate asset leaves that family's partition as it stands, and the unseen scorer drops its models for the day. Rebuilding would write an empty examples object, then an empty candidate, and the candidate's prefix cleanup would delete boosters a champion pointer can name.
- **Candidate**: one per family, per-head XGBoost with fixed params, holdout = the last `holdout_days` of reports (cut by report, never by row), AUC + a label-permutation null. Each family trains on the examples of the feature set its registry entry names, and a family whose examples or metadata are missing that day is logged and skipped rather than failing the asset. A head is _readable_ when it has enough holdout positives and clears its null by 0.05. The shipped booster (`<head>.ubj`) is refit on everything; the train-only fit is kept as `<head>.holdout.ubj` so a later candidate can grade this model on its own holdout.
- **Metrics telemetry**: each asset also captures its metrics as events into the dogfood project (the same project the label events land in), through `training/telemetry.py`: `inbox_ranking_examples_built` once per head and feature set, `inbox_ranking_candidate_trained` once per head (`head`, `model_role` always `candidate`, holdout / train AUC, average precision, logloss, positive rate, mean predicted score, the row-weighted decile calibration error, the permutation-null mean and spread, counts, `readable`), `inbox_ranking_holdout_calibration` once per head and holdout score decile and `inbox_ranking_promotion_decided` once per run, all carrying `model_name` and `model_version` and stamped midday UTC on the partition day so re-runs and backfills chart on the day they describe. Per-head stability is a trends insight with a `head` breakdown; a readability drop is an insight alert. `metadata.json` stays the durable record. Capture is best-effort. Local dev runs (`DEBUG`) emit too, under `distinct_id` `inbox_ranking_training_local` with `environment=local`, so filter or break down on `environment` when reading the prod series; any other non-Cloud deployment emits nothing.
- **Champion**: one decision per family against that family's own pointer. `promotion.decide_promotion` — promote when the candidate has a readable head, is within 0.02 AUC of the champion on every head the champion could read, and the champion is at least `INBOX_RANKING_PROMOTION_MIN_DAYS` old. The champion's AUCs come from its `<head>.holdout.ubj` scored on the candidate's holdout (`paired_champion_aucs`), so both models are compared on one set of reports; a champion without that file falls back to its stored AUC. The pointer is rewritten only when `INBOX_RANKING_AUTO_PROMOTE` is on; otherwise the decision is logged and surfaced as asset metadata, so the daily candidate series is monitoring while the first shadow read runs on a frozen champion. To promote by hand, copy a candidate's `metadata.json` to `champion.json` with a `promoted_at`.

### Outcome heads

| Head            | Cohort at the horizon | Horizon (days) |
| --------------- | --------------------- | -------------- |
| `open`          | Impressed reports     | 3              |
| `action`        | Impressed reports     | 7              |
| `dismiss_wrong` | Impressed reports     | 14             |
| `pr_created`    | Every report          | 7              |
| `pr_merged`     | Every report          | 14             |
| `discuss`       | Impressed reports     | 7              |
| `refund`        | Every report          | 14             |

Every training series resets on the first partition after deploy.
Before and after holdout numbers are not comparable because the example population changes.
See [training example semantics](../../../../docs/internal/inbox-ranking-training.md) for gap handling and snapshot boundaries.

### The unseen read

The holdout grades the recipe, not the model that ships: the shipped booster is refit on train plus holdout, and every holdout row comes from the same snapshots the trainer saw.
Two assets add the missing number, an offline batch proxy for performance on reports the model never saw.

- **`inbox_ranking_unseen_scores` (dt=D)** takes the dt=D state rows of the reports **created on D**, the pool the events tag `pool=newborn`. A newborn has no scoring moment before D, and the dt=D examples stop at D minus the head's horizon (3 days at the shortest), so no example can cover it: leakage-freedom is structural, not a property of what the example builder did that day. The set difference against the examples Parquet stays as a runtime guard — a non-empty overlap fails the asset instead of publishing the number. Every newborn is scored, not a sample, with the day's candidate and, when the pointer names a different version, the champion. Only readable heads are scored, and a model whose feature contract has moved on is logged and left out. Every family scores the whole pool, including reports whose side input has no row for them, because grades are only comparable on paired rows; the `<set>_pool_coverage` metadata says how much of the pool each set could build a real vector for. One Parquet row per (report, model, head) carries the score, `age_hours`, `label_at_scoring` (the head outcome that had already happened when the report was scored, which for a newborn is one that landed on its own birth day, so the grade keeps it; an older pool's rows are still dropped on it, and so are a status-label head's rows in every pool, because no scores column carries the scoring-day `label_provenance_ok` that the example builder checks), `model_name`, and `pool`, the pool definition that produced the row. A re-run that scores nothing is refused when the partition already holds rows, so a day with no loadable model cannot erase the scores a later grade reads. A scores object written before `model_name` existed reads as `tabular_xgb`, the same way one written before `pool` existed keeps the old pool name.
- **`inbox_ranking_unseen_graded` (dt=D)** reads each head's scores back from `D - horizon_days` and grades them against the dt=D labels. It keeps the rows whose cohort holds at D, reads the outcome with `Head.label`, and reports the AUC per model and head next to two comparison lines on the same rows: `recency_auc`, the AUC of ranking newest first, and `null_auc` / `null_auc_std`, the mean and spread of the AUC over seeded permutations of the scores. The mean is 0.5 by construction; the spread is the noise band a per-day AUC has to clear before a gap between two families means anything. It also reads the calibration of those scores, which no AUC can see: the in-cohort rows are cut into score deciles by rank (`training/calibration.py`, shared with the trainer so both sides cut them the same way), and each decile's mean score is compared against the rate the outcome actually happened at. A run of equal scores stays in one decile, so a head reports fewer deciles rather than a gap that only reflects the row order. That read spans the whole pool, the reports whose side input has no row for them included, and the examples drop those rows, so on a thin `<set>_pool_coverage` day the unseen error carries a population the holdout error cannot: read the two per family.

Because the cohort, the label, the horizon and the provenance rules are the trainer's own, the unseen AUC is directly comparable to the holdout AUC of the same head and model version. The gap between the two series is the overfitting read the promotion gate cannot see.

Four events carry it to the dashboard, next to the training events: `inbox_ranking_unseen_report_scored` per (report, model) with `p_<head>`, the raw feature inputs, and `pool` (which pool definition produced the row), `inbox_ranking_unseen_head_graded` per (model, head) with `rows`, `positives`, `birth_day_positives` (of the positives, how many landed on the report's birth day), `base_rate`, `mean_score`, `expected_calibration_error`, `auc` and `recency_auc`, `inbox_ranking_unseen_calibration` per (model, head, decile) with `bucket`, `rows`, `positives`, `mean_score` and `realized_rate` (one event per decile, because a table on the head event would be an array no insight can break down), and `inbox_ranking_unseen_report_graded` per (report, model, horizon) with `p_<head>`, `in_cohort_<head>` and `outcome_<head>` for a calibration read on the raw rows. Both graded events are stamped on the day the outcome was read and carry `scoring_partition`, the day the report was scored, so a chart can be built on either axis. Both also carry `pool`, read back from the scores object, so an AUC series never mixes two pool definitions: the grader reads scores from up to 14 days earlier, so the days after a pool change grade both populations. A scores object written before the column existed reads as `sampled`, the pool the old seeded sample defined.

### Running the training job locally

The training job is S3-only, so it can run on a laptop against copies of the prod snapshots. The dataset job cannot: it needs the dogfood project's ClickHouse and cross-region Postgres.

1. With the dev stack up (`bin/start`; the script waits for object storage to accept requests), sync the two prefixes the job reads into the local object-storage bucket. This needs an SSO session with the `secrets-editor` role on `prod-us-secrets`, and the Secrets Manager id of the dataset reader credential (provisioned with the bucket; ask the owning team):

   ```bash
   aws sso login --profile prod-us-secrets
   INBOX_RANKING_READER_SECRET_ID=<secret id> products/signals/dags/inbox_ranking/bin/sync_snapshots_local.sh
   ```

   This copies `inbox_report_state/v1/dt=*` and `inbox_report_labels/v1/dt=*` to `~/.cache/posthog/inbox_ranking/` and from there into `s3://posthog/inbox_ranking/` on SeaweedFS (`localhost:19000`). `INBOX_RANKING_SYNC_EMBEDDINGS=1` adds `inbox_report_embeddings`, which the `report_embeddings` family needs; it is off by default because that table carries a vector per live report per partition. Without it the job still runs, and that family builds no examples. `INBOX_RANKING_SYNC_TITLE_EMBEDDINGS=1` adds `inbox_report_title_embeddings` on its own switch, for the same reason. It prints the partition days present in both tables; pick the **newest** of those as the partition to run. The examples asset reads the `INBOX_RANKING_TRAINING_LOOKBACK_DAYS` snapshots behind the partition it runs for, so an early day has little history behind it and trains on almost nothing. Re-runs only move new days.

   Note that the dev stack's object storage accepts unsigned requests and publishes port 19000 on every host interface, so anything synced here (and the disk cache) is readable by whoever can reach your machine. The snapshots are internal dogfood telemetry, not customer data, but run the sync on a network you trust.

2. Make sure `INBOX_RANKING_DATASET_S3_BUCKET` is unset for the Dagster process: `common.s3_client()` then talks to SeaweedFS and `dataset_bucket()` is `posthog`. Checking your shell (`env | grep INBOX_RANKING`) is not enough, because `bin/start` sources `.env.local` into the processes it starts; check that file too. If the variable reaches Dagster, the dag uses your ambient AWS credentials against that bucket, and the read-only credential the sync used protects nothing.

3. `bin/start` runs `dagster dev` on http://localhost:3030 with the signals location loaded; materialize `inbox_ranking_training_job` for that partition from the UI, or from the CLI:

   ```bash
   dagster job launch -w .dagster_home/workspace.yaml --location posthog.dags.locations.signals \
       -j inbox_ranking_training_job --tags '{"dagster/partition": "2026-08-25"}'
   ```

   The schedule is stopped outside prod US, so nothing runs unasked. If the run sits in `QUEUED`, check the daemon log for `Maximum is 10, won't launch more`: runs from a killed `dagster dev` stay `STARTED` forever and count against the local queue. Terminate them from the Runs page (force termination).

4. Read the result from `s3://posthog/inbox_ranking/inbox_ranking_models/v1/tabular_xgb/dt=<day>/metadata.json` (per-head AUCs, readability); the examples are at `s3://posthog/inbox_ranking/inbox_ranking_training_examples/v1/tabular/dt=<day>/part-00000.parquet`:

   ```bash
   AWS_ACCESS_KEY_ID=object_storage_root_user AWS_SECRET_ACCESS_KEY=object_storage_root_password \
       aws --endpoint-url http://localhost:19000 s3 cp s3://posthog/inbox_ranking/inbox_ranking_models/v1/tabular_xgb/dt=2026-08-25/metadata.json -
   ```

Nothing here touches the prod bucket: the reader credential is read-only and the dag writes only to the local bucket.

## The shadow dag

`inbox_ranking_shadow_job` runs daily at 09:30 UTC on the same partition definition (gated like the other two) and writes one object:

```text
s3://<bucket>/<prefix>/
└── inbox_ranking_shadow_eval/v1/dt=YYYY-MM-DD/   one row per (model, outcome, order)
```

Every other read of this model is offline. The holdout grades the recipe, the unseen read grades the model on reports it never saw, and neither compares the model against the list people actually get. That list is sorted without a model: the inbox asks for `priority,status,-updated_at` by default, a person can change the field and the direction, and the flat view re-sorts the merged per-state responses on the client with the same keys. (`-is_suggested_reviewer,status,-updated_at` in `products/signals/backend/views.py` is only the fallback for a caller that sends no ordering. The inbox always sends one, and reviewer scope is deliberately not a tiebreak there.) Nothing serves a model rank, so the model cannot be measured by what people clicked on it. What can be measured is the counterfactual, from data already flowing.

- **Grade only complete reconstructed render windows.** An `Inbox reports impressed` event holds only newly shown rows. Union events by absolute rank for the same `distinct_id`, `$session_id`, `scope`, normalized `tab` and five-second UTC bucket, keeping the maximum `list_size`. State-section tabs normalize to `reports`, because the merged Reports view emits a different tab per section. Grade only windows with every rank from 1 through `list_size` and one distinct report per rank. Exclude missing sessions and conflicting assignments. Pagination inside a bucket extends the earlier list; an incomplete page in a later bucket is excluded. Exact repeats collapse only inside the bucket, so later visits remain separate. Without a render ID this is an approximation: a boundary can split one render, and nearby visits can combine. It does not recover every served list.
- **A report is relevant to a list when the same person opened it or acted on it within 30 minutes of seeing it there.** `open` and `action` name the heads whose scores order them, so a head is graded against the outcome it was fit toward. The relevance is a list-scoped proxy for that head's label, not the label itself: the `open` head predicts that anyone opens the report within three days, and `action` the same over seven, both counted per report rather than per viewer. A shadow NDCG and an unseen AUC of the same name therefore answer different questions. A window of hours would credit a list for a report the person came back to from a link. One engagement counts for one list, the last one the person saw the report in before it: changing a filter or a sort re-impresses the same rows at new ranks, so one person can hold several live lists holding the same report, and only one of them can have caused the open.
- **A list uses only scores available when each row was impressed.** Availability comes from S3 `LastModified` on the same GET response as the score data, not the training schedule. Delayed writes and backfills cannot backdate scores; a rewrite conservatively loses coverage before its new write time. Unscored reports keep their outcomes and rank last in the model order, tied on served rank. `score_coverage` is the scored share for each family, role and head; `positive_coverage` is the scored share of its engaged rows, and `full_list_coverage` is the share of served lists with every row scored. A group with no available scores is not graded.
- **Three orders are graded on exactly the same rows**: `model` (descending score of the head, ties broken on the served rank), `heuristic` (the rank the list served), and `random` (seeded permutations, reported with their spread — the chance line a gap has to clear). Each gets NDCG@5, NDCG@10 and MRR, averaged over the lists that had the outcome. A list with no outcome has no ideal ranking to normalize against, and a list of one is ordered identically by everything, so neither is graded.
- **Position bias is not corrected for, and cannot be.** Every recorded open happened under the served order, so a report the heuristic put first had more chance of being opened than one it put twentieth, whatever either order thinks of it. That flatters the heuristic line. `positive_served_rank_mean` reports how concentrated the outcomes were at the top of the served list, so the size of the effect sits next to the numbers it distorts. A gap that survives it is real; a narrow one is not evidence of anything.
- **The heuristic line pools every order that was served.** The impression event records the ranks a list showed but not the sort that produced them, so the default order, a person's chosen order and each client's own all average into one line. The gap therefore answers "would one global order beat the mix of orders people get", not "would it beat the inbox default". Nothing recovers the split later: with no sort on the event, a past partition cannot be separated after the fact.
- **A grade groups by family and role, not by version.** `model_versions` counts the score versions mixed across a day's lists. When a partition has no champion rows for a family and head, the read uses that partition's candidate rows as the champion fallback. This includes days when both share a version and preserves existing champion rows. Missing rows can also mean unreadable champion metadata, so the fallback is an evaluation convention, not proof of the historical champion pointer.

`inbox_ranking_shadow_ranking_graded` carries each grade to the dashboard: `model_name`, `model_role`, `outcome`, `ranking_order`, the three metrics (plus `_std` on the random line), `positive_served_rank_mean`, the grade's own `score_coverage`, `positive_coverage` and `full_list_coverage`, and the run-level `served_lists`, `served_rows` and `run_score_coverage` on every row, so a thin line can be filtered out without a join. **Filter a single line on `score_coverage`, not on `run_score_coverage`**: a head is scored only on the partitions the training job found it readable on, and a family is skipped on a partition it has no metadata for, so the run figure is a union that a thin grade hides behind. The chart is a trends insight broken down on `ranking_order`. `inbox_ranking_shadow_run_completed` lands once per partition whether or not anything was graded, carrying the same run-level fields plus `grades`, so a day that graded nothing reads as a zero rather than the gap a failed run leaves.

Like the dataset job, this one reads the dogfood project's ClickHouse, so it cannot run on a laptop against S3 copies the way the training job can. It reads; it changes nothing anyone sees. Whether a model rank is stamped onto the list response, behind a flag, is the serving decision this read exists to inform.

## Configuration

| Setting                                    | Default         | Meaning                                                                                                                                                                                                             |
| ------------------------------------------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `INBOX_RANKING_DATASET_S3_BUCKET`          | unset           | Destination bucket. Unset on Cloud makes every asset log and skip, so the dag can deploy before the bucket exists. Unset elsewhere falls back to the deployment's object-storage service (SeaweedFS in dev and CI). |
| `INBOX_RANKING_DATASET_S3_PREFIX`          | `inbox_ranking` | Key prefix under the bucket.                                                                                                                                                                                        |
| `INBOX_RANKING_TRAINING_LOOKBACK_DAYS`     | `60`            | How many daily snapshots back the training examples reach.                                                                                                                                                          |
| `INBOX_RANKING_TRAINING_HOLDOUT_DAYS`      | `7`             | Trailing days of reports that grade a candidate.                                                                                                                                                                    |
| `INBOX_RANKING_AUTO_PROMOTE`               | `false`         | Whether a winning candidate rewrites `champion.json`; off, the decision is only logged.                                                                                                                             |
| `INBOX_RANKING_PROMOTION_MIN_DAYS`         | `3`             | Minimum age of the champion before another promotion.                                                                                                                                                               |
| `INBOX_RANKING_SHADOW_SCORE_LOOKBACK_DAYS` | `60`            | How many scores partitions back the shadow read looks for a score that already existed when a list was served.                                                                                                      |

Writes use boto3: ambient AWS config (the node role) when the dedicated bucket is set, the `OBJECT_STORAGE_*` endpoint and credentials otherwise. Readers (project-level warehouse tables, model training) use a separate read-only credential provisioned with the bucket.

## ClickHouse posture

All reads route to the offline cluster replicas on Cloud (`etl_workload()`), carry the dagster run in `log_comment`, and the cross-team embeddings scan runs under explicit time/memory/spill guards (see `queries.py` for why that scan has no `team_id` sort-key prefix and why that is acceptable).

## Operating it

- Backfill any day range from the Dagster UI; partitions start 2026-04-01 (the label epoch). Every asset sits in the `inbox_ranking_etl` pool so concurrent partitions don't each start their own fleet-wide embeddings scan — the pool's limit is a Dagster deployment setting, provisioned with the bucket.
- Failures alert `#alerts-self-driving` (owner `team-self-driving`); assets retry twice with a 60s delay before failing a run. A UI-launched materialization runs under Dagster's implicit `__ASSET_JOB`, which carries no owner tag, so alert routing falls back to matching the `inbox_report_`, `inbox_signal_`, and `inbox_ranking_` asset-name prefixes.
- Runtime budgets are per job (`dagster/max_runtime`): 3h for the dataset and training jobs, 1h for the shadow job. The 3h figure is what the dataset needs — its seven label streams run sequentially, each allowed up to 600s, and the join and S3 writes come after them. The shadow read is one day of two event families plus the scores objects in its lookback, so it gets an hour.

## Deletion and retention

Partitions are immutable history, so a report deleted later keeps its rows (and vector) in partitions written before the deletion.
The embedding tombstone nulls the vector in every partition built after it, and `status='deleted'` flows through state from then on.
**A re-run does not scrub a deleted report.** Label telemetry lives in the dogfood project and outlives the Postgres row, so a re-run regenerates the report as a label-only row: the id, its action/status/dismissal labels, and its team id come back, only the state columns go null.
Scrubbing therefore means deleting the affected `dt=` objects (and rebuilding `latest/`), not re-running the partitions.
The same holds for signal rows, with one addition: a retraction can expire out of the source before any run scans it, so a scrub cannot be driven off `is_deleted` in this archive and has to work from the deleted report's id.
Nothing in the team-deletion path knows about this prefix today, so the purge is manual until that is wired up - tracked with the bucket provisioning, and nothing is at risk before then because the assets write nothing until the bucket exists.
The bucket is internal-only and access-restricted; a lifecycle policy for old partitions is a provisioning-time decision.
