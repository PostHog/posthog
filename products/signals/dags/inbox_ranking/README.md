# Inbox ranking Dagster dags

Dagster jobs for the Self-driving Inbox report-ranking model: the **dataset** dag (daily snapshots), and the **training** dag (daily per-head XGBoost candidates, champion pointer, serving manifest and online grades), sibling subpackages sharing `common.py`.

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
└── tests/
```

Registered via `posthog/dags/locations/signals.py` (US only) and loaded locally through `.dagster_home/workspace.yaml`.

## The dataset dag

`inbox_ranking_dataset_job` runs daily at 02:30 UTC (schedule default: running on prod US, stopped everywhere else — including hosted DEV and E2E, which have no dogfood project to read labels from) and builds six assets on one daily partition, each a Parquet object in S3:

```text
s3://<bucket>/<prefix>/
├── inbox_report_state/v1/dt=YYYY-MM-DD/       # Postgres spine + report-state columns
├── inbox_report_embeddings/v1/dt=YYYY-MM-DD/  # report_id -> small-1536 vector as of snapshot end
├── inbox_report_labels/v1/dt=YYYY-MM-DD/      # cumulative label columns from dogfood telemetry
├── inbox_report_model_data/v1/
│   ├── dt=YYYY-MM-DD/                         # materialized join of the three (the training table)
│   └── latest/                                # rewritten by the newest partition; warehouse tables point here
├── inbox_signal_embeddings/v1/dt=YYYY-MM-DD/  # one row per signal emitted during the day (signal grain)
└── inbox_report_title_embeddings/v1/dt=YYYY-MM-DD/  # the same shape, for the title-only rendering
```

The first four are report grain and land in one table. `inbox_signal_embeddings` is signal grain, feeds the group-level model, and is read on its own — training joins it to `inbox_report_model_data` by `report_id`.

`inbox_report_title_embeddings` is a report-grain leaf. It snapshots the `title_v1` rendering the same way `inbox_report_embeddings` snapshots `title_summary_v1`, and nothing joins it: the training side pairs the two by `report_id` when it measures one rendering against the other, and each carries its own `embedding_inserted_at`, because a summary-only edit re-emits only `title_summary_v1`. Its dependency on `inbox_report_model_data` is for ordering, not data — it holds a vector per live report, so it runs last and alone in the run pod. That edge has a cost: a failed join, or a run that hits the job's runtime cap, skips the title snapshot for the day, and the schedule never revisits a day. Repair such a gap with a single-asset backfill while the source rows are inside their 3-month TTL.

### Partition semantics

- Partition `dt=D` snapshots the eligible report inventory (promoted before `D+1 00:00 UTC`, or referenced by any label event before it). Every label aggregate is bounded `event_time < D+1 00:00 UTC`.
- Label columns are **cumulative**: later partitions strictly dominate earlier ones, so training reads features from `dt=D` and labels from any later partition, choosing the label-maturity window at read time. Late labels are never backfilled into old partitions.
- `latest/` advances **monotonically**: each write stamps a `snapshot-date` in S3 object metadata, and a partition rewrites `latest/` only when it is at or ahead of what `latest/` holds. Delayed retries of the newest day repair it; backfills of older days never clobber it.
- Rows for reports **outside this dag's region** are label-only: no Postgres state, no embedding, and `report_team_id` null (a US team id and an EU team id of the same number are different teams, so the label stream's id can't be merged in). `status_event_team_id` carries the team the transition itself reported, which is the tenant attribution those rows do have.
- **Backfills are not fully point-in-time**: labels are exact for any past day apart from the server-side action counts (see below), embeddings are exact within the source table's 3-month TTL, but report state is read from Postgres as of the run (`features_observed_at` flags this per row). The title snapshot has the same guarantee and the same limit as the report snapshot, through the same `inserted_at < snapshot_end` bound.
- **The `inserted_at` bound does not cover a re-embedded rendering.** The source replaces on a key that includes the rendering and the document id, so a partition rebuilt _later_ for an earlier day finds only the newer row, whose `inserted_at` is past the cutoff, and the report reads as having no vector that day. That loses coverage and never leaks a future vector. A forward run carries the same loss over a shorter window: the schedule fires at 02:30 UTC for the previous day, so the query starts at least 2.5 hours after the cutoff, and the title snapshot runs after the join, which makes its window the wider of the two. A partition before `title_v1` emission shipped holds zero rows, which is written as an empty Parquet with the full schema rather than skipped.
- Report-state mutability reaches **inclusion**, not just feature values: `promoted_at` is cleared on suppression and snooze, so a report promoted before the cutoff and suppressed after it leaves the spine unless a label event referenced it before the cutoff. Forward runs see this only for the 2.5 hours between the cutoff and the schedule; backfills see the full accumulated effect. Deriving the spine from immutable promotion history (`signal_report_status_changed` carries `promoted_at`) is the v2 fix.
- **The server-side action counts read current artefact rows**, bounded by `created_at < snapshot_end`. A report merge moves the source's notes and linked PRs to the survivor and keeps their `created_at`, and a note can be deleted. A partition rebuilt after either change gives that action to the survivor, or loses it. Claims and Slack discussions stay on the source report. Forward runs see this only for the 2.5 hours between the cutoff and the schedule.
- **`signal_report_status_changed` names the actor of each transition.** `actor_kind` is `user`, `agent`, `task` or `system`, and `actor_user_uuid`, `actor_distinct_id`, `actor_agent` and `actor_task_id` identify it. A transition no caller attributed (the pipeline, the PR-merge webhook, an unresolved Slack click) is `system`. The event `distinct_id` stays the team uuid. Events before this change carry no actor keys, so a per-user feature must treat a missing `actor_kind` as unknown, not as `system`.

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

`inbox_ranking_training_job` runs daily at 05:00 UTC on the same partition definition (gated like the dataset job) and writes:

```text
s3://<bucket>/<prefix>/
├── inbox_ranking_training_examples/v1/<feature_set>/dt=YYYY-MM-DD/  # one row per report at its birth, all heads, one parquet per feature set
├── inbox_ranking_models/v1/<model_name>/
│   ├── dt=YYYY-MM-DD/<head>.ubj + <head>.holdout.ubj    # the day's candidate: serving fit + train-only fit
│   │                  + metadata.json                     # (a re-run replaces this prefix in full)
│   └── champion.json                                     # pointer the scoring sweep loads (the only object written across partitions)
└── inbox_ranking_served_scores/v1/dt=YYYY-MM-DD/       # the scoring sweep's scores of the reports born that day, per model key
```

- **A model is a `(model_name, model_version, model_role)`.** `model_name` is the family: which features and which learner: `report_embeddings` and `title_embeddings`, both per-head XGBoost, are the two trained here. `model_version` is the partition day it was fit on, and `model_role` is the role it was scored or trained under (`candidate` on the training events; `served`, `daily_candidate` or `cross_family` on the online grade). Each family owns a prefix under the models path and its own `champion.json`, so two families trained on the same day cannot collide, and promotion stays inside a family. A second family is a second model graded on the same online rows, not a competitor for another family's pointer.
- **A feature set is one feature universe.** `products/signals/backend/ranking/features.py` holds a `FeatureSet` per universe: its name, its schema version, its ordered feature names, the report-state columns it reads, `build_matrix`, and how many rows it wants per report and per head. `report_embeddings` and `title_embeddings` are the two today. A candidate records the set it was fit on in its `metadata.json`, so the grader checks a model against its own set rather than one global contract, the examples asset writes one Parquet per set, and the unseen scorer builds one matrix per set and shares it across the families that read it. Adding a set means an entry in `FEATURE_SETS`; a model naming a set this build cannot produce is logged and left unscored.
- **Examples are one row per report at its birth, by default.** For partition `dt=D` the examples asset reads the report-state and labels snapshots `dt=D-lookback..D` and emits one row per report, on the snapshot of the day it was created, labeled from the snapshot `horizon_days` later (3 for open, 7 for action / pr_created / discuss / thumbs_up, 14 for pr_merged / refund / reviewer_fix, 21 for dismiss_wrong / fixed / dismiss_lowvalue). Features are built by the feature set from that snapshot's state columns plus `age_hours`, the report's age at the snapshot. Labels are aligned to the state spine, so a report with no label event is a negative (all-zero labels), not absent. Label-only rows (no Postgres state) are skipped, as are state rows read long after their snapshot day (backfills carry current Postgres state; see `features_observed_at`) and, for the heads that read the status stream (`dismiss_wrong`, `action`, `fixed` and `dismiss_lowvalue`), rows whose status telemetry fails the dataset's `label_provenance_ok` check. Birth is the moment serving scores a report, and the label that comes out is a per-report probability, which is what the inbox ordering needs. A report born before the window, or one whose birth-day snapshot is missing from it, is no example; `reports_missing_birth_snapshot` on the asset counts the second case, which is a gap in the partitions.
- **An outcome already visible on the birth day is a future positive.** A report born on day D has no scoring moment before D, so an outcome visible at D belongs to the moment being built rather than to an earlier one; the labels of D therefore read as their defaults for a report born on D. Most outcomes land on the birth day, so this is where the positives are: censoring on them costs the `pr_created` head most of its training signal. `<set>_<head>_birth_day_positives` on the examples asset, and `birth_day_positives` on the `inbox_ranking_examples_built` event, say how many positives the rule keeps. These rows carry a hindsight the other rows do not: the state snapshot reads `signal_count`, `total_weight`, `run_count` and the text sizes live from Postgres a few hours after day D ends, so a birth-day outcome happened before its own feature read. Both the holdout AUC and the newborn unseen grade therefore read optimistically on these rows, until the scoring sweep's timestamped score log replaces the daily snapshot as this table's source.
- **Every head asks whether the outcome happened within N days of the scoring moment.** `pr_merged` includes every report, so the label covers the whole report-to-merge path without requiring a PR at birth or at the horizon.
- **A set may ask for another grain**, and cap the rows one head keeps (`max_examples_per_head`, whole report-creation days, newest first). The scoring-moment grain is one row per (report, snapshot) whose head label is still 0 on that snapshot: the serving situation replayed over history, but its label is a hazard conditional on the report still being live, and one long-lived report contributes dozens of near-duplicate rows. The report grain is the first snapshot of the window where the report is a usable moment, which is later than birth only when a side input landed late. Both stay selectable for re-scoring families; nothing ships on them today. The row budget shortens the history a head is fit on and keeps each kept day whole, so the scores stay calibrated to the population of that window. The lookback is the training job's whatever the grain, so positives accrue over the whole window until the budget binds.
- **The embedding sets are the serving contract.** Each reads one rendering's vector and nothing else, so the scoring sweep needs only the report's latest vector for that rendering. The sweep must build features through the same module; the booster's `feature_names` are checked against it at load. A model whose metadata names no set is left unscored.
- **`report_embeddings` is the report's own vector and nothing else**, read from the dt=D `inbox_report_embeddings` snapshot as a side input. Age is deliberately left out: it is the whole signal of the `recency_auc` line the unseen read already reports, so a gap to that line is content rather than recency. The scoring sweep does not serve this set: it is an offline candidate, and serving it needs the report vector at scoring time.
- **`title_embeddings` is the same set over the title-only vector**, read from the dt=D `inbox_report_title_embeddings` snapshot, a separate leaf partition with its own `embedding_inserted_at`. One `ReportEmbeddingsFeatureSet` class parameterized by the input it reads, so the two renderings share this width, this grain, this row budget and the trainer's booster params by construction: the pair measures the text choice, and a recipe that drifted on one side would read as a text effect. A set reads its own input only and never falls back to the other rendering's vector, so a report present in one snapshot and absent from the other is an example for one family and not the other. The inbox title is what a person reads before opening a report and the summary is read after, which is the question the pair answers: whether the summary carries `open` signal or only post-open signal.
- **A moment only takes a vector that already existed for it.** The snapshot holds the latest vector per report, and a report is re-embedded whenever its text changes (the summary workflow and every re-research run rewrite it), so the latest vector often postdates an earlier moment. Each row carries `embedding_inserted_at`, and a moment keeps the vector only when it landed at or before that snapshot's end; at the birth grain a report whose birth-day snapshot holds only a later vector is no example, and at the report grain it moves to the first snapshot where the vector was already its own. Without that check the family would train on text that did not exist when the report was supposedly scored. A report the snapshot has no vector for at all is not an example either, because the source table's TTL runs from report creation and a long-lived report loses its vector while still live. The scores asset records each set's coverage of the newborn pool, so a thin side input is visible rather than silent.
- **A set whose side input is unavailable is skipped, not rebuilt from nothing.** The examples asset writes no object for it, the candidate asset leaves that family's partition as it stands, and the unseen scorer drops its models for the day. Rebuilding would write an empty examples object, then an empty candidate, and the candidate's prefix cleanup would delete boosters a champion pointer can name.
- **Missing and empty are different inputs.** The case above is a snapshot object that is absent. A snapshot that exists and carries no usable vector keeps its key, so the family builds no row and the ordinary thin-input path applies. Each rendering is a separate dependency of the examples and scores assets, so a failed title snapshot costs the title family's day and nothing else.
- **One rendering's vectors are held at a time.** The examples asset loads a set's side inputs, builds that set's object, and releases them before the next set. Each snapshot carries a vector per live report, so a further embedding family costs runtime rather than peak memory. The scores asset narrows each snapshot to the newborn pool it scores for the same reason. Raising the pod memory limit is not the first move here.
- **Candidate**: one per family, per-head XGBoost with fixed params, holdout = the last `holdout_days` of reports (cut by report, never by row), AUC + a label-permutation null. Each family trains on the examples of the feature set its registry entry names, and a family whose examples or metadata are missing that day is logged and skipped rather than failing the asset. A head is _readable_ when it has enough holdout positives and clears its null by 0.05. The shipped booster (`<head>.ubj`) is refit on everything; the train-only fit is kept as `<head>.holdout.ubj` so a later candidate can grade this model on its own holdout.
- **Metrics telemetry**: each asset also captures its metrics as events into the dogfood project (the same project the label events land in), through `training/telemetry.py`: `inbox_ranking_examples_built` once per head and feature set, `inbox_ranking_candidate_trained` once per head (`head`, `model_role` always `candidate`, holdout / train AUC, average precision, logloss, positive rate, mean predicted score, the row-weighted decile calibration error, the permutation-null mean and spread, counts, `readable`), `inbox_ranking_holdout_calibration` once per head and holdout score decile `inbox_ranking_promotion_decided` once per run and `inbox_ranking_serving_manifest_published` once per run, all carrying `model_name` and `model_version` and stamped midday UTC on the partition day so re-runs and backfills chart on the day they describe. Per-head stability is a trends insight with a `head` breakdown; a readability drop is an insight alert. `metadata.json` stays the durable record. Capture is best-effort. Local dev runs (`DEBUG`) emit too, under `distinct_id` `inbox_ranking_training_local` with `environment=local`, so filter or break down on `environment` when reading the prod series; any other non-Cloud deployment emits nothing.
- **Champion**: one decision per family against that family's own pointer. `promotion.decide_promotion` — promote when the candidate has a readable head, is within 0.02 AUC and 0.02 holdout ECE of the champion on every head the champion could read, and the champion is at least `INBOX_RANKING_PROMOTION_MIN_DAYS` old. The quality gates run before the wait: `gates_passed` on the decision event and the `<family>_gates_passed` asset metadata say whether the candidate passed them, also on a day the wait blocks it, and `would_promote` stays the final decision. The champion's AUCs and ECEs come from its `<head>.holdout.ubj` scored on the candidate's holdout (`paired_champion_grades`), so both models are compared on one set of reports; a champion without that file falls back to its stored AUC and skips the calibration check. A head whose shared holdout has fewer than its `min_holdout_positives` is skipped rather than blocking, and is listed in `skipped_heads` on the decision event and the asset metadata; a head the candidate did not train still blocks. The pointer is rewritten only when `INBOX_RANKING_AUTO_PROMOTE` is on; otherwise the decision is logged and surfaced as asset metadata, so the daily candidate series is monitoring. To promote by hand, copy a candidate's `metadata.json` to `champion.json` with a `promoted_at`.

- **Serving manifest**: the dag's decision about what the scoring sweep runs, published where the sweep can read it. The Temporal workers have no credential for the dataset bucket, so `inbox_ranking_serving_manifest` copies the models the sweep needs into the deployment's own object store and writes a manifest naming them:

```text
s3://<object-storage bucket>/<prefix>/serving/
├── models/<model_name>@<model_version>/metadata.json + <head>.ubj   # the refit boosters only
└── manifest.json                                                    # the models one scoring pass runs
```

The manifest holds one entry per model with its `roles`: `served` for the champion of `INBOX_RANKING_SERVED_FAMILY`, `daily_candidate` for that family's candidate on this partition when it is a different, readable model, `pinned` for each model the `pin` override keeps (see [Overrides](#overrides)), and `cross_family` for every other family's champion that has a readable head. A pass scores all of them, so an online paired read and a later interleaving need no rescoring; the entry count is capped at the `ranking_score` artefact's own limit, dropping `cross_family` entries first and `pinned` entries next. The schema, the role names and the object keys live in `products/signals/backend/ranking/serving_manifest.py`, and its validators run at write time, so the dag refuses a manifest the sweep could not act on. A model version is immutable, so a version already in the store is not copied again, and `manifest.json` is written last: a failed copy leaves the previous manifest and the previous models serving. No family has a champion until the first promotion, so until then the asset writes nothing and says why.

A region that does not train serves the same models through a mirror. When `INBOX_RANKING_SERVING_MIRROR_BUCKET` is set, the asset repeats the publish into that bucket after the primary publish succeeds, in the same order and with the same skip of versions already there. A mirror failure does not fail the asset: it logs, and the `inbox_ranking_serving_manifest_published` event carries `mirror_published=false`. The property is absent when no mirror is set.

The reader is `score_reports` in `products/signals/backend/ranking/scorer.py`. It loads every model the manifest names through `model_store.py`, reads each report's latest vector once per rendering, builds each model's matrix with its own `FeatureSet.build_matrix`, and writes one `ranking_score` artefact per report plus one `inbox_ranking_report_scored` event per report and model. The dag and the reader decide whether a model can be scored with the same functions, in `products/signals/backend/ranking/model_contract.py`. A served model that cannot load stops the pass. Any other model that cannot load, or has no vector for a report, is a `skipped` result. No scheduled caller runs the reader yet.

### Overrides

An owner can change serving and promotion without a training run, through the payload of the `inbox-ranking-overrides` feature flag in the internal PostHog project. The flag is inert by default. When the flag is off, the payload is empty, or the lookup fails, the sweep and the dag run as they do without the flag. The parser is `products/signals/backend/ranking/overrides.py`, and the sweep and the dag share it.

Every key is optional, but no key applies without `expires_at`:

```json
{
  "expires_at": "2026-10-11T00:00:00Z",
  "served": "report_embeddings@2026-10-03",
  "pin": ["report_embeddings@2026-09-26"],
  "promotion": {
    "freeze": ["report_embeddings"],
    "force": ["report_embeddings"],
    "skip_gates": { "report_embeddings": ["min_days", "ece", "min_holdout_positives"] }
  }
}
```

| Key                    | Read by                                | Effect                                                                                                                                                                                                                                    |
| ---------------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `expires_at`           | sweep and dag                          | Required. After this time the sweep and the dag ignore the payload and log `inbox_ranking_override_expired`. A payload with no `expires_at`, or one more than 14 days ahead, is invalid.                                                  |
| `served`               | sweep, once per pass                   | Gives this model key the `served` role for the pass. The key must name a model in the current manifest, a pinned one included. No `champion.json` changes, and removing the key reverts on the next tick.                                 |
| `pin`                  | dag (`inbox_ranking_serving_manifest`) | Keeps these model keys in the manifest with the `pinned` role, so a `served` override survives the next manifest rewrite and can roll back to an older model.                                                                             |
| `promotion.freeze`     | dag (`inbox_ranking_model_champion`)   | For these families, the run trains, grades and records the decision, but never writes `champion.json`.                                                                                                                                    |
| `promotion.force`      | dag (`inbox_ranking_model_champion`)   | For these families, the run promotes the day's candidate when `decide_promotion` refuses it. The candidate must still be newer than the champion and have a readable head. This is a lasting champion change.                             |
| `promotion.skip_gates` | dag (`inbox_ranking_model_champion`)   | Waives named checks of `decide_promotion` for one family: `min_days` (the `INBOX_RANKING_PROMOTION_MIN_DAYS` wait), `ece` (`ECE_TOLERANCE`), `min_holdout_positives` (a head whose candidate holdout is too thin to read does not block). |

`freeze` wins over `force` and `skip_gates` for the same family. `force` and `skip_gates` still need `INBOX_RANKING_AUTO_PROMOTE` on, so the flag cannot promote where promotion is off. An unknown key, an unknown gate, or a model key that is not `<model_name>@<YYYY-MM-DD>` makes the whole payload invalid: it is never partly applied, and `inbox_ranking_override_invalid` logs the reason.

The worst result of a bad payload is a warning, never a stopped pass or an unpublished manifest:

- A `served` key that is not in the manifest, that did not load (missing files, a feature contract mismatch, an untrained head), that has fewer heads than the manifest's served model is rejected. The sweep logs `inbox_ranking_override_rejected` and scores with the manifest's served model. The override only moves the `served` role among models the pods already load, so it never adds memory.
- A pinned key whose `metadata.json` or boosters are missing in the dataset bucket, or that fails `model_mismatch`, is dropped before composition. The manifest still publishes, and the asset metadata lists `pinned_keys` and `dropped_pins` with reasons.

During a `served` override, the override model carries the roles `served` and `served_override`, and the manifest's served model carries `manifest_served` in place of `served`. The sweep compares the served key on the latest `ranking_score` with the effective one, so setting or removing an override rescores every report in the window. The `inbox_ranking_sweep_finished` log and each `inbox_ranking_report_scored` event carry `override_served` and `override_expires_at`. The `inbox_ranking_promotion_decided` event carries `override` (`frozen`, `forced`, `skipped_gates` or null) and `override_skipped_gates`, next to the `reason` the rule gave, so a forced promotion still records why the rule refused it.

Examples, each with an `expires_at` at most 14 days ahead:

- Serve today's candidate now: set `served` to the `daily_candidate` key of the current manifest.
- Roll back to an older champion: add its key to `pin`, wait for the next manifest run (or rematerialize `inbox_ranking_serving_manifest`), then set `served` to the same key.
- Pause promotion while a regression is investigated: `"promotion": {"freeze": ["report_embeddings"]}`.
- Promote a candidate the rule refused for a harmless reason: `"promotion": {"force": ["report_embeddings"]}`, or the narrower `skip_gates` with the gate that refused it.

Both regions read the same flag, so one override applies everywhere, if the region's `posthoganalytics` client evaluates flags in the internal project. A region that cannot read the flag runs with no override. Nothing deletes old model prefixes in the dataset bucket or old `serving/models/<key>/` copies. If the bucket has a lifecycle rule, a rollback through `pin` works only while the model files are still there.

### Outcome heads

| Head               | Cohort at the horizon | Horizon (days) |
| ------------------ | --------------------- | -------------- |
| `open`             | Every report          | 3              |
| `action`           | Every report          | 7              |
| `dismiss_wrong`    | Every report          | 21             |
| `pr_created`       | Every report          | 7              |
| `pr_merged`        | Every report          | 14             |
| `fixed`            | Every report          | 21             |
| `discuss`          | Every report          | 7              |
| `refund`           | Every report          | 14             |
| `thumbs_up`        | Every report          | 7              |
| `reviewer_fix`     | Every report          | 14             |
| `dismiss_lowvalue` | Every report          | 21             |

`action` counts intent from every surface, not only the cloud inbox list.
A report is a positive when someone clicked an intent action in the inbox UI (create PR, implement, copy the prompt, discuss, open or view a PR, edit the reviewers, restore), or when a person or an external agent claimed it, linked a PR, left a note, discussed it in Slack, or resolved it with a reason.
Self-driving's own `task` and `system` writes do not count: they are internal operational work.
A resolve without a reason is the automatic resolve after a tracked PR merges, so it does not count either.

The Today home sends the same client events as the Inbox, with `surface: 'today'` and a `list` property (`briefing` or `sidebar_more`) on impressions and opens.
Filter on `surface` where a metric must stay Inbox-only.
Today sets a verdict first and sends its optional reason in a second state call, which does not change the status.
For that call the server emits `signal_report_status_changed` with `previous_status` equal to `status` and `reason_added: true`, so the reason reaches the status-stream heads.

`thumbs_up` (a positive rating on the report body) and `reviewer_fix` (a suggested reviewer added or removed) are the explicit human-feedback pair.
Both are rare, so neither clears its holdout bar on a single day.
They are carried for the pooled newborn grade and as scorer inputs, not for a holdout AUC, and the promotion gate keeps ignoring an unreadable head.

Every training series resets on the first partition after deploy.
Before and after holdout numbers are not comparable because the example population changes.
See [training example semantics](../../../../docs/internal/inbox-ranking-training.md) for gap handling and snapshot boundaries.

### The online read

The model is read in three layers: **training** (train metrics), **test** (the random-by-report holdout, which drives promotion) and **online** (the scoring sweep's live scores, graded at each head's horizon).
The holdout grades the recipe, not the model that ships: the shipped booster is refit on train plus holdout, and every holdout row comes from the same snapshots the trainer saw.
Two assets add the missing number, from the scores the sweep actually wrote for reports no model trained on.

- **`inbox_ranking_served_scores` (dt=D)** (`training/served.py`) takes the dt=D state rows of the reports **created on D**, the pool the rows tag `pool=newborn`. A newborn has no scoring moment before D, and the dt=D examples stop at D minus the head's horizon (3 days at the shortest), so no example can cover it. It reads this deployment's `inbox_ranking_report_scored` events for that pool inside D and keeps the earliest `scored` event per (report, model key), so every model the manifest named is graded: the served champion, the served family's `daily_candidate`, and the other families' `cross_family` champions. `model_role` comes from the event's roles: `served` when they hold it, else the first role, else `candidate`. The sweep scores a candidate only after a manifest names it, so a candidate's online cohort starts the day after it was trained. Every head a model fit is scored, readable or not, and each row carries `head_readable` and the model's own `classification_threshold`. One Parquet row per (report, model key, head) carries the score, `age_hours`, `label_at_scoring` (the head outcome that had already happened when the report was scored, which for a newborn is one that landed on its own birth day, so the grade keeps it; a status-label head's rows are still dropped on it, because no scores column carries the scoring-day `label_provenance_ok` that the example builder checks), `model_name`, `model_role`, and `pool`. `served_pool_coverage` and `pool_coverage_by_model` say how much of the pool each model covered. A re-run that reads no event is refused when the partition already holds rows, and so is one that reads fewer families than the object already holds. Rows of a retired family (`RETIRED_MODEL_NAMES`) are dropped on read, and the rewrite guard does not require them.
- **`inbox_ranking_unseen_graded` (dt=D)** reads saved scores from D back through each head's horizon and evaluates them against the dt=D labels. Daily head evaluations include both unbaked and baked metrics, marked by `is_mature`; existing head, report and calibration grade events remain baked-only at `D - horizon_days`. See [baked and unbaked unseen metrics](../../../../docs/internal/inbox-ranking-training.md#baked-and-unbaked-unseen-metrics) for the event contract and chart revision rules. It keeps the rows whose cohort holds at D, reads the outcome with `Head.label`, and reports the AUC per model and head next to two comparison lines on the same rows: `recency_auc`, the AUC of ranking newest first by `report_created_at`, and `null_auc` / `null_auc_std`, the mean and spread of the AUC over seeded permutations of the scores. The mean is 0.5 by construction; the spread is the noise band a per-day AUC has to clear before a gap between two families means anything. It also reads the calibration of those scores, which no AUC can see: the in-cohort rows are cut into score deciles by rank (`training/calibration.py`, shared with the trainer so both sides cut them the same way), and each decile's mean score is compared against the rate the outcome actually happened at. A run of equal scores stays in one decile, so a head reports fewer deciles rather than a gap that only reflects the row order. Read each grade with the model's `pool_coverage_by_model`: a key that joined the manifest part of the way through D grades only part of the pool.

At the full horizon, the cohort, label and provenance rules are the trainer's own, so the baked online AUC is directly comparable to the holdout AUC of the same head and model version. The gap between the two series is the overfitting read the promotion gate cannot see.

The event names keep the `unseen` prefix so existing dashboard tiles keep reading. Three events carry the baked results, next to the daily `inbox_ranking_unseen_head_evaluated`: `inbox_ranking_unseen_head_graded` per (model, head) with `readable` (whether the head's holdout could be read on the model that wrote the scores), `model_role`, `rows`, `positives`, `birth_day_positives` (of the positives, how many landed on the report's birth day), `base_rate`, `mean_score`, `expected_calibration_error`, `auc` and `recency_auc`, `inbox_ranking_unseen_calibration` per (model, head, decile) with `bucket`, `rows`, `positives`, `mean_score` and `realized_rate` (one event per decile, because a table on the head event would be an array no insight can break down), and `inbox_ranking_unseen_report_graded` per (report, model, horizon) with `p_<head>`, `in_cohort_<head>` and `outcome_<head>` for a calibration read on the raw rows. Both graded events are stamped on the day the outcome was read and carry `scoring_partition`, the day the report was scored, so a chart can be built on either axis. Both also carry `pool`, read back from the scores object, so an AUC series never mixes two pool definitions: the grader reads scores from up to the longest head horizon (21 days) earlier, so the days after a pool change grade both populations. A scores object written before the column existed reads as `sampled`, the pool the old seeded sample defined.

#### Reading one rendering against another

The `title_embeddings` and `report_embeddings` families are trained and graded to be compared, not promoted. The read:

- **Pair the rows, then take the difference.** The sweep scores each report with both families when both are in the manifest, so for one head and one day they are mostly graded on the same reports. Break the unseen grade down by `model_name` and difference the two AUCs on the rows both grades had. An unpaired difference of two full-population AUCs is not this comparison: keep each family's full-population number, and the matched one, as separate figures.
- **Read the uncertainty before the sign.** `null_auc_std` on each grade is the spread a per-day AUC has on those rows. A difference inside that band is inconclusive, not evidence that the two renderings carry the same signal. Pool about 30 days before treating a direction as real.
- **Carry coverage and positives with every figure.** `pool_coverage_by_model` on the scores asset says how much of the pool each model scored, and `rows` / `positives` / `birth_day_positives` on each grade say how much outcome the AUC rests on. A family graded largely on its missing branch reads low for a reason that is not the text.
- **Keep the baselines on the same rows.** `recency_auc` and the other embedding family are reported on the same grade, so the reading is title against combined against newest-first, not against numbers from another day.
- **Read `open` first.** It has the shortest horizon (3 days), so its labels mature first; `action` and `pr_created` follow at 7 days. Emission is forward-only and a moment only takes a vector that had already landed, so both families accrue from the first partition after their input starts flowing.
- **This is not an online experiment.** Every row is a live birth-day score graded against a later snapshot, and the outcomes it grades happened under the order the inbox actually served. A gap between two families is a difference in rank quality on logged outcomes, not a causal claim about what the inbox would do differently.

Nothing in this read changes what the inbox serves. The scoring sweep serves the family the manifest names (`INBOX_RANKING_SERVED_FAMILY`), promotion stays inside a family, and `INBOX_RANKING_AUTO_PROMOTE` gates the pointer rewrite; a rendering that wins here earns a separate decision, not an automatic promotion.

### Running the training job locally

The training job is S3-only, so it can run on a laptop against copies of the prod snapshots. The dataset job cannot: it needs the dogfood project's ClickHouse and cross-region Postgres.

1. With the dev stack up (`bin/start`; the script waits for object storage to accept requests), sync the two prefixes the job reads into the local object-storage bucket. This needs an SSO session with the `secrets-editor` role on `prod-us-secrets`, and the Secrets Manager id of the dataset reader credential (provisioned with the bucket; ask the owning team):

   ```bash
   aws sso login --profile prod-us-secrets
   INBOX_RANKING_READER_SECRET_ID=<secret id> products/signals/dags/inbox_ranking/bin/sync_snapshots_local.sh
   ```

   This copies `inbox_report_state/v1/dt=*` and `inbox_report_labels/v1/dt=*` to `~/.cache/posthog/inbox_ranking/` and from there into `s3://posthog/inbox_ranking/` on SeaweedFS (`localhost:19000`). `INBOX_RANKING_SYNC_EMBEDDINGS=1` adds `inbox_report_embeddings`, which the `report_embeddings` family needs; it is off by default because that table carries a vector per live report per partition. Without it the job still runs, and that family builds no examples. `INBOX_RANKING_SYNC_TITLE_EMBEDDINGS=1` adds `inbox_report_title_embeddings`, which the `title_embeddings` family needs, on its own switch and for the same reason. It prints the partition days present in both tables; pick the **newest** of those as the partition to run. The examples asset reads the `INBOX_RANKING_TRAINING_LOOKBACK_DAYS` snapshots behind the partition it runs for, so an early day has little history behind it and trains on almost nothing. Re-runs only move new days.

   Note that the dev stack's object storage accepts unsigned requests and publishes port 19000 on every host interface, so anything synced here (and the disk cache) is readable by whoever can reach your machine. The snapshots are internal dogfood telemetry, not customer data, but run the sync on a network you trust.

2. Make sure `INBOX_RANKING_DATASET_S3_BUCKET` is unset for the Dagster process: `common.s3_client()` then talks to SeaweedFS and `dataset_bucket()` is `posthog`. Checking your shell (`env | grep INBOX_RANKING`) is not enough, because `bin/start` sources `.env.local` into the processes it starts; check that file too. If the variable reaches Dagster, the dag uses your ambient AWS credentials against that bucket, and the read-only credential the sync used protects nothing.

3. `bin/start` runs `dagster dev` on http://localhost:3030 with the signals location loaded; materialize `inbox_ranking_training_job` for that partition from the UI, or from the CLI:

   ```bash
   dagster job launch -w .dagster_home/workspace.yaml --location posthog.dags.locations.signals \
       -j inbox_ranking_training_job --tags '{"dagster/partition": "2026-08-25"}'
   ```

   The schedule is stopped outside prod US, so nothing runs unasked. If the run sits in `QUEUED`, check the daemon log for `Maximum is 10, won't launch more`: runs from a killed `dagster dev` stay `STARTED` forever and count against the local queue. Terminate them from the Runs page (force termination).

4. Read the result from `s3://posthog/inbox_ranking/inbox_ranking_models/v1/report_embeddings/dt=<day>/metadata.json` (per-head AUCs, readability); the examples are at `s3://posthog/inbox_ranking/inbox_ranking_training_examples/v1/report_embeddings/dt=<day>/part-00000.parquet`:

   ```bash
   AWS_ACCESS_KEY_ID=object_storage_root_user AWS_SECRET_ACCESS_KEY=object_storage_root_password \
       aws --endpoint-url http://localhost:19000 s3 cp s3://posthog/inbox_ranking/inbox_ranking_models/v1/report_embeddings/dt=2026-08-25/metadata.json -
   ```

Nothing here touches the prod bucket: the reader credential is read-only and the dag writes only to the local bucket.

## Configuration

| Setting                                | Default             | Meaning                                                                                                                                                                                                             |
| -------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `INBOX_RANKING_DATASET_S3_BUCKET`      | unset               | Destination bucket. Unset on Cloud makes every asset log and skip, so the dag can deploy before the bucket exists. Unset elsewhere falls back to the deployment's object-storage service (SeaweedFS in dev and CI). |
| `INBOX_RANKING_DATASET_S3_PREFIX`      | `inbox_ranking`     | Key prefix under the bucket.                                                                                                                                                                                        |
| `INBOX_RANKING_TRAINING_LOOKBACK_DAYS` | `60`                | How many daily snapshots back the training examples reach.                                                                                                                                                          |
| `INBOX_RANKING_TRAINING_HOLDOUT_DAYS`  | `7`                 | Trailing days of reports that grade a candidate.                                                                                                                                                                    |
| `INBOX_RANKING_AUTO_PROMOTE`           | `false`             | Whether a winning candidate rewrites `champion.json`; off, the decision is only logged.                                                                                                                             |
| `INBOX_RANKING_PROMOTION_MIN_DAYS`     | `0`                 | Minimum age of the champion before another promotion. The scoring sweep stamps each score with its model key, so no wait is needed for a clean read.                                                                |
| `INBOX_RANKING_SERVED_FAMILY`          | `report_embeddings` | Family whose champion the serving manifest serves.                                                                                                                                                                  |
| `INBOX_RANKING_SERVING_MIRROR_BUCKET`  | unset               | A second deployment's object-storage bucket that receives a copy of every serving publish, through ambient AWS config. Unset means no mirror.                                                                       |
| `INBOX_RANKING_SERVING_MIRROR_REGION`  | unset               | AWS region of the mirror bucket.                                                                                                                                                                                    |
| `INBOX_RANKING_SCORING_BATCH_SIZE`     | `500`               | Report ids per ClickHouse vector read in the scorer. A larger call is paged at this size.                                                                                                                           |

Writes use boto3: ambient AWS config (the node role) when the dedicated bucket is set, the `OBJECT_STORAGE_*` endpoint and credentials otherwise. Readers (project-level warehouse tables, model training) use a separate read-only credential provisioned with the bucket.

## ClickHouse posture

All reads route to the offline cluster replicas on Cloud (`etl_workload()`), carry the dagster run in `log_comment`, and the cross-team embeddings scan runs under explicit time/memory/spill guards (see `queries.py` for why that scan still reads nearly the whole table, even with the training consent `team_id` list, and why that is acceptable).

## Operating it

- Backfill any day range from the Dagster UI; partitions start 2026-04-01 (the label epoch). Every asset sits in the `inbox_ranking_etl` pool so concurrent partitions don't each start their own fleet-wide embeddings scan — the pool's limit is a Dagster deployment setting, provisioned with the bucket.
- A label column change needs a `FEATURE_SCHEMA_VERSION` bump, and no manual backfill. The labels asset stamps the version in each object's `feature-schema-version` metadata. Every hour, `inbox_ranking_labels_refresh_sensor` finds labels partitions in the training lookback whose stamp is missing or older, and runs `inbox_ranking_labels_refresh_job` on at most `INBOX_RANKING_LABELS_REFRESH_MAX_RUNS` (default 6) of them, newest first. A 60-day lookback is current again in about 10 hours. The sensor skips the newest day, which the daily schedule writes, and partitions with no labels object. It requests a partition at most once per schema version, so a failed refresh alerts and needs a person. The refresh covers labels only: report state reads current Postgres and embeddings have a TTL, so a rewrite of those is not point-in-time. `pairs_skipped_missing_label_columns` on `inbox_ranking_examples_built` counts the snapshot pairs each head lost to a missing label column while partitions are stale.
- Do not materialize these assets in-process in the code-location pod. Its memory limit (2Gi) is too small; launch a run instead.
- Failures alert `#alerts-self-driving` (owner `team-self-driving`); assets retry twice with a 60s delay before failing a run. A UI-launched materialization runs under Dagster's implicit `__ASSET_JOB`, which carries no owner tag, so alert routing falls back to matching the `inbox_report_`, `inbox_signal_`, and `inbox_ranking_` asset-name prefixes.
- Runtime budgets are per job (`dagster/max_runtime`): 2h for the dataset job, 3h for the training job. The dataset needs the 2h: its seven label streams run sequentially, each allowed up to 600s, and the join and S3 writes come after them. The dataset cap ends before training starts at 05:00 UTC, so a stuck dataset run fails before training reads its snapshots.

## Training consent

The dags train only on reports from organizations whose `Organization.is_ai_training_opted_in` is `True`.
`False` and `None` both mean no consent.
`consent.training_consent_team_ids()` returns the consenting teams that hold an inbox report, and every asset reads it once per run.

- `inbox_report_state` keeps only the spine reports of those teams. A label event that names another team's report does not pull it back in. That report's labels still land in `inbox_report_model_data` as a label-only row, which training skips.
- `inbox_report_embeddings`, `inbox_report_title_embeddings` and `inbox_signal_embeddings` read only those teams, through `team_id IN (...)` in the ClickHouse query.
- The examples asset drops every state row whose `report_team_id` is not in the current set, before it builds examples. The lookback window reaches partitions written before an organization opted out, so this filter is what makes an opt-out take effect on the next training run.

The filter follows the current setting, so an organization that opts back in is trained on again.
The state asset and the examples asset record `excluded_no_training_consent_reports` and `excluded_no_training_consent_teams` as metadata, and `inbox_ranking_examples_built` carries the examples counts. They are counts, never ids.
The online grade reads the dt=D state snapshot for its newborn pool, so that pool shrinks to consenting teams too. Scoring in the sweep does not change.
The filter does not delete existing partitions or models. A re-run of `inbox_signal_embeddings` stays additive, so rows that an older run wrote remain in that partition. Nothing trains on signal embeddings today, and a future reader must apply the same filter.

## Deletion and retention

Partitions are immutable history, so a report deleted later keeps its rows (and vector) in partitions written before the deletion.
The embedding tombstone nulls the vector in every partition built after it, and `status='deleted'` flows through state from then on.
**A re-run does not scrub a deleted report.** Label telemetry lives in the dogfood project and outlives the Postgres row, so a re-run regenerates the report as a label-only row: the id, its action/status/dismissal labels, and its team id come back, only the state columns go null.
Scrubbing therefore means deleting the affected `dt=` objects (and rebuilding `latest/`), not re-running the partitions.
The same holds for signal rows, with one addition: a retraction can expire out of the source before any run scans it, so a scrub cannot be driven off `is_deleted` in this archive and has to work from the deleted report's id.
Nothing in the team-deletion path knows about this prefix today, so the purge is manual until that is wired up - tracked with the bucket provisioning, and nothing is at risk before then because the assets write nothing until the bucket exists.
The bucket is internal-only and access-restricted; a lifecycle policy for old partitions is a provisioning-time decision.
