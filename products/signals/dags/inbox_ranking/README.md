# Inbox ranking Dagster dags

Dagster jobs for the Self-driving Inbox report-ranking model: the **dataset** dag (daily snapshots), the **training** dag (serving manifest and online grades), and the **nn** dag (the daily candidates), sibling subpackages sharing `common.py`.

```text
inbox_ranking/
├── common.py       # shared: S3 destination config, daily partition def, gating, Parquet IO
├── dataset/
│   ├── dag.py      # the dataset assets + job + schedule
│   ├── queries.py  # HogQL label SQL, embeddings SQL, stream merging
│   └── project_vectors.py  # per-team and per-user context vectors (pure functions)
├── training/
│   ├── dag.py        # serving manifest → served scores → unseen grade assets + job + schedule, and the plumbing nn shares
│   ├── promote.py    # the manual promote job that writes served.json
│   ├── examples.py   # birth-grain training examples over the snapshots
│   ├── heads.py      # the v0 outcome heads
│   ├── train.py      # per-head holdout/null metrics that every learner fills
│   └── promotion.py  # the candidate grading rule
├── multihead/        # the multi-head network, its ONNX export, and the offline prototype
├── nn/               # the `nn` family: examples → candidate → champion assets, and the pair examples, on the `signals_ml` location
└── tests/
```

Per-person activity summaries are not a dag. They live in `products/signals/backend/activity_summary/`.

Registered via `posthog/dags/locations/signals.py` (US only) and loaded locally through `.dagster_home/workspace.yaml`. The `nn` family is registered via `posthog/dags/locations/signals_ml.py` instead, because it needs torch (see [The nn family](#the-nn-family)).

## The dataset dag

`inbox_ranking_dataset_job` runs daily at 02:30 UTC (schedule default: running on prod US, stopped everywhere else — including hosted DEV and E2E, which have no dogfood project to read labels from) and builds ten assets on one daily partition, each a Parquet object in S3:

```text
s3://<bucket>/<prefix>/
├── inbox_report_state/v1/dt=YYYY-MM-DD/       # Postgres spine + report-state columns
├── inbox_report_embeddings/v1/dt=YYYY-MM-DD/  # report_id -> small-1536 vector as of snapshot end
├── inbox_report_labels/v1/dt=YYYY-MM-DD/      # cumulative label columns from dogfood telemetry
├── inbox_report_model_data/v1/
│   ├── dt=YYYY-MM-DD/                         # materialized join of the three (the training table)
│   └── latest/                                # rewritten by the newest partition; warehouse tables point here
├── inbox_signal_embeddings/v1/dt=YYYY-MM-DD/  # one row per signal emitted during the day (signal grain)
├── inbox_report_title_embeddings/v1/dt=YYYY-MM-DD/  # the same shape, for the title-only rendering
├── inbox_report_reviewers/v1/dt=YYYY-MM-DD/   # one row per suggested reviewer of each spine report
├── inbox_user_report_interactions/v1/dt=YYYY-MM-DD/ # cumulative interactions per (report, person)
├── inbox_project_vectors/v1/dt=YYYY-MM-DD/    # per-team mean report vectors of past engagement, by kind
├── inbox_user_vectors/v1/dt=YYYY-MM-DD/       # per-user mean report vectors of past engagement, by kind
└── inbox_activity_summary_vectors/v1/dt=YYYY-MM-DD/ # one row per activity summary vector generated during the day
```

The first four are report grain and land in one table. `inbox_signal_embeddings` is signal grain, feeds the group-level model, and is read on its own — training joins it to `inbox_report_model_data` by `report_id`.

`inbox_report_title_embeddings` is a report-grain leaf. It snapshots the `title_v1` rendering the same way `inbox_report_embeddings` snapshots `title_summary_v1`, and nothing joins it. No model family trains on it since `title_embeddings` was retired; the snapshot stays for offline reads. It carries its own `embedding_inserted_at`, because a summary-only edit re-emits only `title_summary_v1`. Its dependency on `inbox_report_model_data` is for ordering, not data — it holds a vector per live report, so it runs last and alone in the run pod. That edge has a cost: a failed join, or a run that hits the job's runtime cap, skips the title snapshot for the day, and the schedule never revisits a day. Repair such a gap with a single-asset backfill while the source rows are inside their 3-month TTL.

`inbox_report_reviewers` is a (report, reviewer) leaf for user–report affinity modeling. It holds one row per entry of each spine report's current `SignalReportSuggestedReviewer` index, for teams that allow AI training. Nothing joins it, and its object carries its own schema version (`REVIEWERS_SCHEMA_VERSION`), so a failure here does not fail the training table.

- `user_distinct_id` comes from `user_uuid` when that uuid names a member of the report team's organization. Otherwise it comes from `github_login`, through the same GitHub identity mapping the `pr_merged` and `pr_closed` attribution uses. `identity_resolution` says which one matched (`user_uuid`, `github_login` or `unresolved`).
- An entry that maps to no member stays as a row with a null `user_distinct_id`, so a reviewer with no history is counted and not dropped.
- **The asset is current-state-only.** The index is rebuilt in full on every reviewer change, and reviewer artefacts can be edited in place or deleted, so no earlier set can be rebuilt. A forward-run partition holds the set at run time (at most a few hours after the cutoff). A backfilled partition holds today's set, flagged by `features_observed_at`. History starts on the day the asset first ran.

### Project vectors

`inbox_project_vectors` is a (team, kind) leaf with context vectors for a ranking model that reads a team's engagement history next to the report's own vector.
`dataset/project_vectors.py` holds the pure function `project_vectors(labels, embeddings, as_of)`, and the asset calls it with `as_of` = the end of dt=D.

| `kind`    | Mean of                                                                                          |
| --------- | ------------------------------------------------------------------------------------------------ |
| `typical` | every report vector of the team                                                                  |
| `open`    | the last 50 reports anyone on the team opened before `as_of`                                     |
| `action`  | the last 50 reports anyone on the team acted on through a UI intent action (`UI_ACTION_COLUMNS`) |
| `dismiss` | the last 50 reports anyone on the team dismissed from the UI                                     |
| `fixed`   | the last 50 reports the team got fixed (`first_fixed_at`, from the status stream)                |

- The columns are `team_id`, `kind`, `vector` (small-1536), `n_reports` and `as_of`.
- The inputs are the dt=D `inbox_report_embeddings` and `inbox_report_labels` snapshots only. The `open`, `action` and `dismiss` moments are the labels' first-event timestamps of the inbox app events, so MCP reads and agent actions never count there. The `fixed` moment comes from the status stream, so a fix through an agent counts. A project is a team, not an organization.
- A kind with fewer than `MIN_HISTORY_REPORTS` reports keeps its row, with its real `n_reports` and an all-zero vector. A team with no report vector before `as_of` has no rows.
- The asset filters the embeddings snapshot through `training_consent_team_ids()` again, so an opt-out after the snapshot was written takes effect.
- **It is a leaf.** Nothing joins it, it is not in `inbox_report_model_data`'s deps, and its object carries its own `PROJECT_VECTORS_SCHEMA_VERSION`, so a failure here does not fail the training table. Its deps on the embeddings and labels assets keep it after the embeddings snapshot, so the two vector-heavy steps do not share the run pod's memory.

Point-in-time contract:

- A report born on day D uses the project vectors of dt=D−1. Their `as_of` is D 00:00 UTC, strictly before the birth, and that matches serving, where the sweep reads the newest snapshot.
- A report enters a vector only when its vector landed and its engagement happened strictly before `as_of`. The snapshot holds only the latest vector per report, so a report re-embedded after `as_of` is left out rather than read with text it did not have yet.
- The training side can rebuild any past day by calling the function on newer snapshots with an earlier `as_of`. No backfill is needed while the vectors are inside the embedding TTL.
- Serving: when any manifest entry reads project vectors, `inbox_ranking_serving_manifest` copies the dt=D day into the deployment's object store before it writes the manifest. The sweep reads that day once per pass, only for the teams it scores. Its `as_of` is the end of dt=D, so it is never newer than a report scored after the publish. Until the next publish, a report scored on day D+2 still reads dt=D, which is one day older than training reads.
- Serving loads every kind of the day and gives each model the kinds its `metadata.json` lists, in that order. A day written before `PROJECT_VECTORS_SCHEMA_VERSION` 2, or a mirror day built from a v1 engagement export, has no `fixed` rows. A model that reads a kind the day has no rows for is skipped with `project_vector_kinds_missing`. When the served model hits it, the pass fails.

### User vectors

`inbox_user_vectors` is an (organization, user, kind) leaf with the user vectors of `user_vectors(interactions, embeddings, as_of)` in `dataset/project_vectors.py`.
The asset calls it with `as_of` = the end of dt=D, on the dt=D interactions and embeddings snapshots, so its rows equal what `pair_user_vectors` rebuilds for a report born on D+1.

- It filters the interactions again by `training_consent_team_ids()`, and maps each team to its organization through `team_organizations`, like the pair lane.
- Each row carries the `user_hash` of its (organization, user): a hash over each kind's name, `n_reports` and vector. A day that adds no report to a user's history keeps the hash.
- The manifest asset copies the day to `serving_user_vectors_key(prefix, dt)` and names it in `user_vectors`. The mirror never gets a copy.

### Engagement export

`inbox_engagement_export` sends the engagement moments of the other region's reports to the mirror store, so that region can build its own project vectors from its own report embeddings.
The inbox telemetry of every region lands in the US dogfood project, so the `open`, `action`, `dismiss` and `fixed` moments of an EU report exist only in the US labels snapshot.

- It runs only when `INBOX_RANKING_SERVING_MIRROR_BUCKET` is set. Otherwise it logs and writes nothing.
- The rows are the dt=D labels rows whose `report_id` has no `SignalReport` in this region's Postgres before the cutoff. A row whose id is not a UUID is dropped.
- The columns are exactly `ENGAGEMENT_EXPORT_COLUMNS` from `dataset/project_vectors.py`: `report_id` and the first opened, first UI dismissed, first UI action and first fixed timestamps. There are no team ids, no counts, no text and no vectors, so the other region passes the file to `project_vectors()` unchanged.
- The labels snapshot is cumulative, so each day is a full snapshot as of the end of dt=D.
- The key is `serving_engagement_key(prefix, dt)`: `<prefix>/serving/engagement/<dt>/engagement.parquet`. The mirror's write grant covers only `<prefix>/serving/`. The write sets `ACL: bucket-owner-full-control` and stamps the row count, the snapshot date and `ENGAGEMENT_EXPORT_SCHEMA_VERSION` in the object metadata.
- **It is a leaf.** Nothing joins it. A mirror write failure does not fail the asset: it logs, and the output metadata carries `written=false`. The metadata also carries `rows`, `excluded_rows` (the rows whose report is in this region), `local_share` (`excluded_rows` over all labels rows), `bytes` and `s3_key`.
- **A collapsed local share refuses the write.** When the local report lookup returns too few rows, every report it misses looks remote, and this region's report ids would go to the other region. So when the labels table has rows and the lookup finds no local report, the skip reason is `no_local_reports`. When `local_share` is below `ENGAGEMENT_EXPORT_MIN_LOCAL_SHARE`, the skip reason is `local_share_collapsed`. A refusal writes nothing, logs at error level, and sets `written=false` and `skip_reason` in the metadata. The asset does not fail: the mirror region uses an older export for up to `ENGAGEMENT_EXPORT_MAX_AGE_DAYS`, then fails on its side. An empty labels table is not refused.
- Each run with the mirror bucket set captures one `inbox_ranking_engagement_export_published` event in the dogfood project through `training/telemetry.py`, also when the write fails or is refused. It carries `partition`, `written`, `skip_reason`, `rows`, `excluded_rows`, `local_share`, `bytes` and `schema_version`, and no report id or team id.
- A report deleted in this region keeps its Postgres row with the `deleted` status, so it is not exported. Only a report whose row is gone, for example after its team was deleted, looks remote. Such a row exposes a report id and timestamps, and it never matches a report vector in the other region.
- The grant has no delete, and no lifecycle rule covers the prefix, so the daily objects accumulate. Each one holds a report id and a few timestamps per row.

### Mirror region project vectors

`inbox_mirror_project_vectors` (`mirror/dag.py`) builds the project vectors of the mirror region (EU) in that region.
The report vectors of a region exist only in its own ClickHouse, so the training region cannot build them.

- It registers on EU only (`is_inbox_ranking_mirror_registered()`), in its own daily job `inbox_ranking_mirror_job` at 05:30 UTC, after the training region's dataset run.
- The schedule skips its ticks until `INBOX_RANKING_MIRROR_PROJECT_VECTORS_ENABLED` is set. A run by hand works without it.
- The report vectors come from `report_embeddings_table`, the same function the `inbox_report_embeddings` snapshot uses, for the teams in this region's `training_consent_team_ids()`.
- The engagement moments come from the dt=D engagement export at `serving_engagement_key`, in this region's object store. When dt=D is missing, it uses the newest export up to `ENGAGEMENT_EXPORT_MAX_AGE_DAYS` older and logs a warning. When none is in that window, or the export has a schema version the reader does not know, the asset fails. The reader takes `ENGAGEMENT_EXPORT_SCHEMA_VERSION` and the version before it, because the two regions deploy apart. A v1 export has no `first_fixed_at`, so the day gets four kinds and no `fixed` rows.
- It calls `project_vectors()` in memory with `as_of` at the end of dt=D, and writes no dataset object.
- The output is `serving_project_vectors_key(prefix, dt)` in this region's object store, stamped with the row count, the snapshot date, `PROJECT_VECTORS_SCHEMA_VERSION` and the export date it read.
- The output metadata carries the rows, the teams, the teams with enough history for each kind, the export date and its age.

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

### User grain

`inbox_user_report_interactions` has one row per `(report_id, user_distinct_id)`, for user–report affinity models. It has the labels asset's contract: `dt=D` is cumulative from `LABELS_EPOCH` to `D+1 00:00 UTC`, every source has an explicit time bound, and a re-run writes the same object (rows are sorted by key).

- **It is a leaf.** Nothing joins it, it is not in `inbox_report_model_data`'s deps, and it has no deps of its own, so it runs beside the labels asset. A failure here never fails the training table.
- **It has its own schema version**, `USER_INTERACTIONS_SCHEMA_VERSION`, stamped on the object. A change here does not set off `inbox_ranking_labels_refresh_sensor`. There is no refresh sensor for this table: after a schema change, backfill the training lookback by hand.
- **The person key is `User.distinct_id`.** The app's events and the status stream's `actor_distinct_id` already carry it. `user_uuid` is null when the distinct id is not a user in this region.
- **Only consented, local reports get rows.** A row is written only when its report exists in this region's Postgres before the cutoff and its team is in `training_consent_team_ids()`. This is stricter than the labels asset, which keeps label-only rows, because these rows describe a person.
- **Only members of the report's organization get rows.** The person lookups read every `User` in the region, so after the merge the asset drops each pair whose `user_distinct_id` is not a member of the report team's organization. The `non_member_pairs` metadata value counts these pairs.

| Columns                                                        | Source                                       | Person key                                                 |
| -------------------------------------------------------------- | -------------------------------------------- | ---------------------------------------------------------- |
| impressions, suggested-reviewer impressions                    | `Inbox reports impressed` (per entry)        | event `distinct_id`                                        |
| opens, `first_open_method`                                     | `Inbox report opened`                        | event `distinct_id`                                        |
| closes, `total_time_spent_ms`                                  | `Inbox report closed`                        | event `distinct_id`                                        |
| UI actions (`ACTION_TYPES`)                                    | `Inbox report action`                        | event `distinct_id`                                        |
| feedback                                                       | `Inbox report feedback`                      | event `distinct_id`                                        |
| refunds                                                        | `signals_pr_refund_created`                  | event `distinct_id`                                        |
| `status_*`, `first_dismissal_actor_kind`                       | `signal_report_status_changed`               | `actor_distinct_id` when `actor_kind` is `user` or `agent` |
| `pr_closed_by_*`, `pr_merged_by_*`                             | `pr_closed` / `pr_merged`                    | `pr_closed_by_distinct_id` / `pr_merged_by_distinct_id`    |
| claims, linked PRs, notes                                      | `SignalReportArtefact` (`HUMAN_ACTOR_KINDS`) | `created_by`                                               |
| `first_viewed_at`, `first_read_at`, `first_slack_discussed_at` | `SignalReportAction.first_at`                | `user`                                                     |

Point-in-time caveats, per source:

- **The status and PR columns start when the actor keys shipped (2026-10-09).** Earlier events carry no actor, so they reach no row. A backfill before that date fills only the app-event and Postgres columns. Most transitions are `system` and name no person, so most rows come from impressions and opens.
- **The PR closer and merger are set only when their GitHub login maps to an org member.**
- **The status columns follow the `STATUS_SQL` tenant rule.** Each aggregate reads only the tenant of the report's latest transition, taken over every transition of the report, not only this person's. When that tenant is missing or is not the report's team, the pair keeps its other streams and gets default status columns, as `label_provenance_ok` does for the report grain. The `status_tenant_mismatch_pairs` metadata value counts these pairs.
- **The Postgres columns read current rows**, with the report-grain caveats: a merge moves notes and linked PRs to the survivor, and a note can be deleted. Action rows give only `first_at`; their `count` and `last_at` keep moving after the cutoff. Bulk actions carry no `report_id` and stay out, and the desktop app sends no impressions.
- **The client streams are claimed, not proven.** A `report_id` and a `distinct_id` on an app event are client-supplied. The report must exist in this region, and the person must be a member of the report's organization, but nothing proves that the person saw the report.
- **Staff impersonation.** posthog-js opts out of capture in an impersonated session, so the client streams hold no impersonated events. The refund event carries `was_impersonated`, and those refunds are excluded. The status event and the Postgres rows carry no impersonation flag, so a transition, artefact or action row a staff member made while impersonating counts for the impersonated person.

### Signal-grain partitions

`inbox_signal_embeddings` is the one asset here whose partitions are **not** full snapshots. `dt=D` holds only the signal documents inserted during D — an emission log — because a cumulative copy at signal grain means a 1536-float vector per signal, fleet-wide, rewritten every day.

- Read the **union** of partitions and take the latest row per `(team_id, signal_id)` at or before the cutoff. `signal_id` (the ClickHouse `document_id`) is caller-supplied and only unique within a team, so the tenant key is part of the identity. That is the same `(team_id, document_id)` latest-wins the report assets do in SQL, moved to read time.
- **The log is best-effort, not complete.** The source is a ReplacingMergeTree versioned by `inserted_at`, and a retraction re-emits the signal under the same sort key, so a merge between the two writes keeps only the retraction. A signal whose report is deleted in the same window it was inserted reaches no partition in its live form, and no query shape recovers it: the merge has already dropped the row.
- The reverse gap is the TTL. A retraction inherits the original event timestamp, so retracting a signal more than three months old writes a row that is already expired and may never be scanned. **Absence of an `is_deleted` row is not proof that a signal is live**, and this archive is not authoritative for deletion — see the retention section below.
- The vectors' source TTL runs from **signal event time**, so this asset is also where signal vectors become durable. Whatever a partition does not capture before its signals age out is gone.
- Consequently **a re-run is additive**: it unions the fresh scan into the rows the partition already holds, keyed by `(team_id, signal_id, embedding_inserted_at)`, so a row the source can no longer supply survives. Overwriting with the scan alone would delete it permanently, and a row count cannot police that — a scan can lose one emission and gain another and land on the same total.
- The count check remains as a backstop: a union can only grow, so a smaller result means the merge itself is broken and the write is refused. Row counts are stamped in S3 object metadata at write time to make that check a `head_object`. A deliberate shrink still means deleting the object by hand.
- Signal text never leaves ClickHouse: the query selects the vector and the structured metadata (weight, source, match graph), not `content` or the free-text metadata fields.

### Activity summary vectors

`inbox_activity_summary_vectors` is a (team, user, day) leaf with its own `ACTIVITY_SUMMARY_VECTORS_SCHEMA_VERSION`.
It is the durable history of the per-user activity summary vectors, for a ranking model that reads a user vector next to the report vector.
Each successful activity summary build writes one vector per (user, day) to the document embeddings table (`document_id` = `"{user_id}:{date}"`, `timestamp` = the summary's `generated_at`).
That table drops a row 3 months after its `timestamp`, and `UserActivitySummaryVersion` keeps only the newest versions of a pair, so a vector that this asset does not copy in time cannot be rebuilt.

- `dt=D` holds only the vectors whose `timestamp` falls in D, one row per `(team_id, document_id)`, the newest `inserted_at` winning. It is not a cumulative snapshot.
- The columns are `team_id`, `user_id`, `document_id`, `generated_date`, `generated_at`, `embedding_small` (small-1536, the report vectors' space), `embedding_inserted_at`, `prompt_version`, `render_version`, `model` and `source` (`live`, or `backfill` for a summary built as of a past date). No summary text leaves ClickHouse.
- Training reads the union of partitions and calls `activity_vector_as_of` (`training/examples.py`) for the vector a user had at a moment: the newest one generated strictly before it, or nothing when that one is older than a staleness cap.
- A re-run replaces the rows the source still returns and keeps the rows it no longer returns, so a re-run after the TTL does not erase history. It drops the rows of teams without training consent.
- **It is a leaf.** Nothing joins it, so a failure here does not fail the training table. A day of vectors is small, so it has no ordering dependency.
- Backfill: materialize every partition from the first activity summary build that is still inside the source TTL. Repeat for the matching partitions after a backfill of past-dated summaries, before those vectors expire.

## The training dag

`inbox_ranking_training_job` runs daily at 05:00 UTC on the same partition definition (gated like the dataset job).
It fits no model: the `nn` families train on the `signals_ml` location (see [The nn family](#the-nn-family)).
The job runs three assets: `inbox_ranking_serving_manifest`, `inbox_ranking_served_scores` and `inbox_ranking_unseen_graded`.
The manifest depends on the dt=D `inbox_project_vectors` and `inbox_user_vectors` partitions, which it copies.
The user vectors copy is optional: a missing day leaves `user_vectors` out of the manifest and never blocks the publish.
The models live under the dataset prefix:

```text
s3://<bucket>/<prefix>/
├── inbox_ranking_models/v1/
│   ├── served.json                                       # the model key the scoring sweep serves; only the promote job writes it
│   └── <model_name>/
│       ├── dt=YYYY-MM-DD/<model files> + metadata.json   # the day's candidate (a re-run replaces this prefix in full)
│       └── champion.json                                   # retired automatic pointer; read only for the cross-family role
└── inbox_ranking_served_scores/v1/dt=YYYY-MM-DD/       # the scoring sweep's scores of the reports born that day, per model key
```

The per-head XGBoost families are retired (`RETIRED_MODEL_NAMES`): `tabular_xgb`, `title_embeddings` and `report_embeddings_v2`.
Their saved versions (`<head>.ubj` + `<head>.holdout.ubj`) stay in the bucket, and the sweep can still serve one by key, so a rollback to one of them is possible.
The grader drops the online rows of a retired family.

- **A model is a `(model_name, model_version, model_role)`.** `model_name` is the recipe: which features, which learner and which training settings: `nn_v3`, one ONNX network, and `nn_with_prio_v2`, the same network with the report's priority as an input, are trained by the `signals_ml` location, and each `MODEL_FAMILIES` entry names its `learner` and the `location` that trains it. `model_version` is the partition day it was fit on, and `model_role` is the role it was scored or trained under (`candidate` on the training events; `served`, `recent`, `challenger`, `pinned` or `cross_family` on the online grade, and `daily_candidate` on grades written before the `recent` role). Each family owns a prefix under the models path, so two families trained on the same day cannot collide. A candidate is graded only against the served model of its own name. The served pointer can name any family, so a rollback can cross families.
- **A recipe change gets a new `model_name`.** `report_embeddings` and `nn` became `report_embeddings_v2` and `nn_v2` when `action` started to count a thumbs up, and `nn_v2` and `nn_with_prio` became `nn_v3` and `nn_with_prio_v2` when the lookback went from 60 to 90 days and the row budget from 100,000 to 250,000. A candidate's `metadata.json` carries `recipe` and `recipe_hash`, a stable hash of the recipe (`training/recipe.py`): the learner, the feature set and its schema version, the project-vector kinds and their history settings, the booster params or network config, each head's cohort, label, horizon, label columns and status-label flag, `lookback_days`, `holdout_days`, the example grain and row budget, and `dataset_version`. Dates, `run_id`, row counts and metrics stay out, so a daily retrain keeps the hash. The candidate asset compares its hash with the newest version of the same name, at or before its partition, that has one, and on a mismatch it fails before it writes the partition and names the changed inputs. A re-run of a partition therefore compares with that partition's own saved recipe. The search covers every dataset version, so a `DATASET_VERSION` bump also needs a new name. A version without a hash is not compared. This includes an env change such as `INBOX_RANKING_TRAINING_LOOKBACK_DAYS`. To start a new recipe, add a `MODEL_FAMILIES` entry with a new name (`nn_v2` after `nn`) and remove the old entry: the old versions stay servable by key, and the promotion gate never compares two recipes. Two recipes can train side by side for a comparison, but each costs a manifest slot, so do not do it by default. `recipe_hash` is on `inbox_ranking_candidate_trained` and `inbox_ranking_promotion_decided` (with `incumbent_recipe_hash`), and `inbox_ranking_serving_manifest_published` carries `model_recipe_hashes` per model key.
- **A feature set is one feature universe.** `products/signals/backend/ranking/features.py` holds a `FeatureSet` per universe: its name, its schema version, its ordered feature names, the report-state columns it reads, `build_matrix`, and how many rows it wants per report and per head. `report_embeddings` is the report vector, and `report_embeddings_priority` is that vector plus one column per priority level (`priority_P0` to `priority_P4`, all zero when the report has no judgment), read from the `priority` state column. A candidate records the set it was fit on in its `metadata.json`, so the grader checks a model against its own set rather than one global contract, and the scoring sweep builds one matrix per set and shares it across the families that read it. Adding a set means an entry in `FEATURE_SETS`; a model naming a set this build cannot produce is logged and left unscored.
- **Examples are one row per report at its birth, by default.** For partition `dt=D` the `nn` examples asset reads the report-state and labels snapshots `dt=D-lookback..D` and emits one row per report, on the snapshot of the day it was created, labeled from the snapshot `horizon_days` later (7 for open, 14 for action, 30 for fixed). Features are built by the feature set from that snapshot's state columns plus `age_hours`, the report's age at the snapshot. Labels are aligned to the state spine, so a report with no label event is a negative (all-zero labels), not absent. Label-only rows (no Postgres state) are skipped, as are state rows read long after their snapshot day (backfills carry current Postgres state; see `features_observed_at`) and, for the heads that read the status stream (`action` and `fixed`), rows whose status telemetry fails the dataset's `label_provenance_ok` check. Birth is the moment serving scores a report, and the label that comes out is a per-report probability, which is what the inbox ordering needs. A report born before the window, or one whose birth-day snapshot is missing from it, is no example; `reports_missing_birth_snapshot` counts the second case, which is a gap in the partitions.
- **An outcome already visible on the birth day is a future positive.** A report born on day D has no scoring moment before D, so an outcome visible at D belongs to the moment being built rather than to an earlier one; the labels of D therefore read as their defaults for a report born on D. Most outcomes land on the birth day, so this is where the positives are: censoring on them costs the `pr_created` head most of its training signal. `birth_day_positives` on the unseen grade events says how many positives landed on the birth day. These rows carry a hindsight the other rows do not: the state snapshot reads `signal_count`, `total_weight`, `run_count` and the text sizes live from Postgres a few hours after day D ends, so a birth-day outcome happened before its own feature read. Both the holdout AUC and the newborn unseen grade therefore read optimistically on these rows, until the scoring sweep's timestamped score log replaces the daily snapshot as this table's source.
- **Every head asks whether the outcome happened within N days of the scoring moment.**
- **A set may ask for another grain**, and cap the rows one head keeps (`max_examples_per_head`, whole report-creation days, newest first). The scoring-moment grain is one row per (report, snapshot) whose head label is still 0 on that snapshot: the serving situation replayed over history, but its label is a hazard conditional on the report still being live, and one long-lived report contributes dozens of near-duplicate rows. The report grain is the first snapshot of the window where the report is a usable moment, which is later than birth only when a side input landed late. Both stay selectable for re-scoring families; nothing ships on them today. The row budget shortens the history a head is fit on and keeps each kept day whole, so the scores stay calibrated to the population of that window. The lookback is the training job's whatever the grain, so positives accrue over the whole window until the budget binds.
- **The embedding sets are the serving contract.** Each reads one rendering's vector and nothing else, so the scoring sweep needs only the report's latest vector for that rendering. The sweep must build features through the same module; the booster's `feature_names` are checked against it at load. A model whose metadata names no set is left unscored.
- **`report_embeddings` is the report's own vector and nothing else**, read from the dt=D `inbox_report_embeddings` snapshot as a side input. Age is deliberately left out: it is the whole signal of the `recency_auc` line the unseen read already reports, so a gap to that line is content rather than recency. The scoring sweep does not serve this set: it is an offline candidate, and serving it needs the report vector at scoring time.
- **A moment only takes a vector that already existed for it.** The snapshot holds the latest vector per report, and a report is re-embedded whenever its text changes (the summary workflow and every re-research run rewrite it), so the latest vector often postdates an earlier moment. Each row carries `embedding_inserted_at`, and a moment keeps the vector only when it landed at or before that snapshot's end; at the birth grain a report whose birth-day snapshot holds only a later vector is no example, and at the report grain it moves to the first snapshot where the vector was already its own. Without that check the family would train on text that did not exist when the report was supposedly scored. A report the snapshot has no vector for at all is not an example either, because the source table's TTL runs from report creation and a long-lived report loses its vector while still live. The scores asset records each set's coverage of the newborn pool, so a thin side input is visible rather than silent.
- **A missing side input is a skip, not a rebuild from nothing.** A rebuild would write an empty candidate, and the candidate's prefix cleanup would delete model files that a pointer can name. See [The nn family](#the-nn-family).
- **Candidate**: one per family, holdout = the last `holdout_days` of reports (cut by report, never by row), AUC + a label-permutation null. A head is _readable_ when it has enough holdout positives and clears its null by 0.05. The shipped model is refit on everything, and the train-only fit is kept so a later candidate can grade this model on its own holdout.
- **Metrics telemetry**: each asset also captures its metrics as events into the dogfood project (the same project the label events land in), through `training/telemetry.py`: `inbox_ranking_candidate_trained` once per head (`head`, `model_role` always `candidate`, holdout / train AUC, average precision, logloss, positive rate, mean predicted score, the row-weighted decile calibration error, the permutation-null mean and spread, counts, `readable`), `inbox_ranking_holdout_calibration` once per head and holdout score decile `inbox_ranking_promotion_decided` once per run and `inbox_ranking_serving_manifest_published` once per run, all carrying `model_name` and `model_version` and stamped midday UTC on the partition day so re-runs and backfills chart on the day they describe. Per-head stability is a trends insight with a `head` breakdown; a readability drop is an insight alert. `metadata.json` stays the durable record. Capture is best-effort. Local dev runs (`DEBUG`) emit too, under `distinct_id` `inbox_ranking_training_local` with `environment=local`, so filter or break down on `environment` when reading the prod series; any other non-Cloud deployment emits nothing.
- **Champion**: one decision per family, recorded and never written to a pointer. The incumbent is the model `served.json` names when it has the candidate's `model_name`; otherwise there is no paired comparison, and the reason says so. `promotion.decide_promotion` says the candidate would promote when it has a readable head and is within 0.02 AUC and 0.02 holdout ECE of the incumbent on every head the incumbent could read. `would_promote` and `gates_passed` on the `inbox_ranking_promotion_decided` event and the asset metadata carry the decision, and `promoted` is always false. The incumbent's AUCs and ECEs come from its train-only fit scored on the candidate's holdout, so both models are compared on one set of reports; an incumbent without that fit falls back to its stored AUC and skips the calibration check. A head whose shared holdout has fewer than its `min_holdout_positives` is skipped rather than blocking, and is listed in `skipped_heads`; a head the candidate did not train still blocks.
- **Promotion is manual.** `inbox_ranking_promote_job` (`training/promote.py`, `signals` location) takes a `model_key` and a `reason`. It refuses a malformed key, a model this build cannot serve, a missing model file, and a model without every head in `HEADS`, and then writes nothing. Otherwise it writes `served.json` (`model_key`, `promoted_at`, `reason`, `previous_key`, `run_id`), captures `inbox_ranking_model_promoted`, and publishes the serving manifest for the newest partition with project vectors, so the sweep serves the model without waiting for the 05:00 UTC run. Rollback is the same job with an older key, of any family. Launch it from the Dagster UI, or:

```bash
dagster job launch -w .dagster_home/workspace.yaml --location posthog.dags.locations.signals -j inbox_ranking_promote_job \
    --config-json '{"ops": {"inbox_ranking_promote": {"config": {"model_key": "nn_v3@2026-10-21", "reason": "seed the pointer"}}}}'
```

- **Serving manifest**: the dag's decision about what the scoring sweep runs, published where the sweep can read it. The Temporal workers have no credential for the dataset bucket, so `inbox_ranking_serving_manifest` copies the models the sweep needs into the deployment's own object store and writes a manifest naming them:

```text
s3://<object-storage bucket>/<prefix>/serving/
├── models/<model_name>@<model_version>/metadata.json + <head>.ubj   # xgboost: the refit boosters only
├── models/<model_name>@<model_version>/metadata.json + model.onnx   # onnx: one graph for every head
└── manifest.json                                                    # the models one scoring pass runs
```

Each entry names its `model_kind`, and the sweep loads it through that kind's handler in `products/signals/backend/ranking/model_store.py`:

- `xgboost`, the default for a model without the field: one booster per head, `<head>.ubj`. The entry's `heads` list names the files.
- `onnx`: one `model.onnx` for every head. The entry names it in `model_file`, and `heads` still lists the heads it scores. The graph takes one float32 input, `report`, of shape (batch, feature-set width), and gives one output, `probabilities`, of shape (batch, heads). The column order of that output is `output_heads` in the model's `metadata.json`, and each head entry in `heads` there names `model.onnx` as its `file`. At load, the handler checks the input names and widths against what the model's feature set builds, and a mismatch skips the model like an unloadable booster. The session runs on CPU with a bounded thread count, and `onnxruntime` is imported only when a model loads. The project-vector inputs are not served yet, so the sweep skips an `nn` model, whose graph also takes `project` and `has_history`, until it feeds them.

The manifest holds one entry per model with its `roles`: `served` for the model `served.json` names, `recent` for each of the newest `INBOX_RANKING_SERVING_RECENT_VERSIONS` (default 2) versions of the served `model_name`, `challenger` for the newest readable version of each other serving family, read from its last 2 days because an `nn` candidate can land after the manifest runs, `pinned` for each model the `pin` override keeps (see [Overrides](#overrides)), and `cross_family` for every other family's `champion.json` that has a readable head. Nothing writes those files anymore, so they name the last version the retired automatic promotion chose. The dag reads the `recent` versions newest first from `<model_name>/dt=D/metadata.json` in the 2N days up to the partition, where N is the setting. It skips a version with no readable head, the served version, and a version that fails the pin check, and it removes duplicate keys. So each version gets online scores for about N days, not for one. A pass scores all of them, so an online paired read and a later interleaving need no rescoring; the entry count is capped at the `ranking_score` artefact's own limit (5). The order is `served`, `recent`, `challenger`, `pinned`, `cross_family`, so the cap drops `cross_family` entries first and `pinned` entries next. Challengers come in family registration order, so when there are more challengers than free entries, the last registered families lose their place. A challenger is how a new recipe gets online scores on the same reports as the served model before anyone promotes it. Each `recent` version adds one model to every sweep pass, so a higher N costs sweep time and pod memory. The schema, the role names and the object keys live in `products/signals/backend/ranking/serving_manifest.py`, and its validators run at write time, so the dag refuses a manifest the sweep could not act on. A model version is immutable, so a version already in the store is not copied again, and `manifest.json` is written last: a failed copy leaves the previous manifest and the previous models serving. When `served.json` is missing, or names a model that fails the pin check, the asset writes nothing and says why, and the previous manifest keeps serving.

A region that does not train serves the same models through a mirror. When `INBOX_RANKING_SERVING_MIRROR_BUCKET` is set, the asset repeats the publish into that bucket after the primary publish succeeds, in the same order and with the same skip of versions already there. A mirror failure does not fail the asset: it logs, and the `inbox_ranking_serving_manifest_published` event carries `mirror_published=false`. The property is absent when no mirror is set.

Project vectors are per-team data, so this region never copies its own day to the mirror. When a manifest entry reads them, the asset looks for the mirror region's own day in the mirror bucket instead:

- It calls `head_object` on `serving_project_vectors_key(prefix, D')` for each day D' from D back to D − `MIRROR_PROJECT_VECTORS_MAX_LAG_DAYS` (3), newest first. The mirror grant has no list permission, so a missing key answers 403, and both read as absent. It reads only the object metadata, never the body.
- A day passes when its `feature-schema-version` metadata is this build's `PROJECT_VECTORS_SCHEMA_VERSION` and its `engagement-export-date` metadata is no older than D − 3. The key names live in `serving_manifest.py`, and the mirror region's writer uses the same ones.
- When a day passes, the mirror manifest names it in `project_vectors`, and the publish copies no project vectors object. The mirror region builds day D after the 05:00 UTC publish, so a mirror that keeps up names D−1, one day older than the primary.
- When no day passes and the served model reads project vectors, the mirror keeps its previous manifest. When only other entries read them, the mirror manifest names none, and the mirror sweep skips those entries.
- The event carries `mirror_project_vectors_key`, `mirror_project_vectors_date` and `mirror_engagement_export_date`, and `mirror_skip_reason` when the mirror is not published: `no_fresh_project_vectors`, `unknown_schema_version`, `stale_engagement_export` or `publish_failed`. The `inbox_ranking_sweep_finished` log carries the `project_vectors_date` the pass read and its `project_vectors_age_days`.

The reader is `score_reports` in `products/signals/backend/ranking/scorer.py`. It loads every model the manifest names through `model_store.py`, reads each report's latest vector once per rendering, builds each model's matrix with its own `FeatureSet.build_matrix`, and writes one `ranking_score` artefact per report plus one `inbox_ranking_report_scored` event per report and model. The dag and the reader decide whether a model can be scored with the same functions, in `products/signals/backend/ranking/model_contract.py`. A served model that cannot load stops the pass. Any other model that cannot load, or has no vector for a report, is a `skipped` result. No scheduled caller runs the reader yet.

### Overrides

An owner can change serving without a training run or a Dagster launch, through the payload of the `inbox-ranking-overrides` feature flag in the internal PostHog project. The flag is inert by default. When the flag is off, the payload is empty, or the lookup fails, the sweep and the dag run as they do without the flag. The parser is `products/signals/backend/ranking/overrides.py`, and the sweep and the dag share it.

Every key is optional, but no key applies without `expires_at`:

```json
{
  "expires_at": "2026-10-11T00:00:00Z",
  "served": "report_embeddings@2026-10-03",
  "pin": ["report_embeddings@2026-09-26"]
}
```

| Key          | Read by                                | Effect                                                                                                                                                                                                       |
| ------------ | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `expires_at` | sweep and dag                          | Required. After this time the sweep and the dag ignore the payload and log `inbox_ranking_override_expired`. A payload with no `expires_at`, or one more than 14 days ahead, is invalid.                     |
| `served`     | sweep, once per pass                   | Gives this model key the `served` role for the pass. The key must name a model in the current manifest, a pinned one included. `served.json` does not change, and removing the key reverts on the next tick. |
| `pin`        | dag (`inbox_ranking_serving_manifest`) | Keeps these model keys in the manifest with the `pinned` role, so a `served` override survives the next manifest rewrite and can roll back to an older model.                                                |

Promotion is not an override: use `inbox_ranking_promote_job`. A payload that still carries the retired `promotion` key is invalid. An unknown key, or a model key that is not `<model_name>@<YYYY-MM-DD>`, makes the whole payload invalid: it is never partly applied, and `inbox_ranking_override_invalid` logs the reason.

The worst result of a bad payload is a warning, never a stopped pass or an unpublished manifest:

- A `served` key that is not in the manifest, that did not load (missing files, a feature contract mismatch, an untrained head), that has fewer heads than the manifest's served model is rejected. The sweep logs `inbox_ranking_override_rejected` and scores with the manifest's served model. The override only moves the `served` role among models the pods already load, so it never adds memory.
- A pinned key whose `metadata.json` or boosters are missing in the dataset bucket, or that fails `model_mismatch`, is dropped before composition. The manifest still publishes, and the asset metadata lists `pinned_keys` and `dropped_pins` with reasons.

During a `served` override, the override model carries the roles `served` and `served_override`, and the manifest's served model carries `manifest_served` in place of `served`. The sweep compares the served key on the latest `ranking_score` with the effective one, so setting or removing an override rescores every report in the window. The `inbox_ranking_sweep_finished` log and each `inbox_ranking_report_scored` event carry `override_served` and `override_expires_at`.

Examples, each with an `expires_at` at most 14 days ahead:

- Serve a recent version now: set `served` to a `recent` key of the current manifest.
- Roll back to an older model without a Dagster launch: add its key to `pin`, wait for the next manifest run (or rematerialize `inbox_ranking_serving_manifest`), then set `served` to the same key. For a lasting rollback, run `inbox_ranking_promote_job` with the key.

Both regions read the same flag, so one override applies everywhere, if the region's `posthoganalytics` client evaluates flags in the internal project. A region that cannot read the flag runs with no override. Nothing deletes old model prefixes in the dataset bucket or old `serving/models/<key>/` copies. If the bucket has a lifecycle rule, a rollback through `pin` works only while the model files are still there.

### Outcome heads

| Head     | Cohort at the horizon | Horizon (days) |
| -------- | --------------------- | -------------- |
| `open`   | Every report          | 7              |
| `action` | Every report          | 14             |
| `fixed`  | Every report          | 30             |

The families train only these three heads, because the inbox reads only these three.
The dataset still snapshots the label columns of other outcomes, so a head can come back without a labels backfill.
The promotion rule compares only the heads in `HEADS`, so an incumbent that carries a retired head does not block a candidate without it.

`action` counts intent from every surface, not only the cloud inbox list.
A report is a positive when someone clicked an intent action in the inbox UI (create PR, implement, copy the prompt, discuss, open or view a PR, edit the reviewers, restore), or when a person or an external agent claimed it, linked a PR, left a note, discussed it in Slack, or resolved it.
A thumbs up on the report counts too (`feedback_positive_count`). A thumbs down does not, because it is a negative judgment and not intent.
A resolve counts when it carries a reason or when its `actor_kind` is `user` or `agent`, so the one-click Today resolve counts.
Self-driving's own `task` and `system` writes do not count: they are internal operational work.
A resolve with no reason and no human actor is the automatic resolve after a tracked PR merges, so it does not count either.

`fixed` counts a resolve without a not-fixed reason, and a dismissal with a fixed reason.
A reason-less resolve by a `user` or an `agent` waits for a 24-hour grace window first.
It counts as fixed only when the window closed before the snapshot and no not-fixed reason arrived inside it as a `reason_added` row.
The label is dated from the resolve, and a reason after the window cannot take it back, so the label only grows.

The Today home sends the same client events as the Inbox, with `surface: 'today'` and a `list` property (`briefing` or `sidebar_more`) on impressions and opens.
The Today report page sends `Inbox report opened` once per visit, when the report loads.
A click on a list row sends `open_method: 'click'` with the row's `list`, `rank` and `list_size`, and `source` (`list` or `more`).
The previous / next control sends `source: 'step'`, with the position in the report queue as `rank` and the queue length as `list_size`, and no `list`.
Every other visit (a shared URL, a PostHog AI link, a refresh, back / forward) sends `open_method: 'deeplink'` with a null `list`, `rank` and `list_size`.
`link_source` comes from the URL, and PostHog AI writes `link_source=today` on the Today report links it shows.
A list row opened in place sends `Inbox report action` with `action_type: 'expand_preview'`, `list` and `rank`.
No head reads `expand_preview`, and it is not in `ACTION_TYPES`.
Sample reports send no `Inbox` events.
Filter on `surface` where a metric must stay Inbox-only.
Today sets a verdict first and sends its optional reason in a second state call, which does not change the status.
For that call the server emits `signal_report_status_changed` with `previous_status` equal to `status` and `reason_added: true`, so the reason reaches the status-stream heads.

Every training series resets on the first partition after deploy.
Before and after holdout numbers are not comparable because the example population changes.
See [training example semantics](../../../../docs/internal/inbox-ranking-training.md) for gap handling and snapshot boundaries.

### The online read

The model is read in three layers: **training** (train metrics), **test** (the random-by-report holdout, which drives promotion) and **online** (the scoring sweep's live scores, graded at each head's horizon).
The holdout grades the recipe, not the model that ships: the shipped model is refit on train plus holdout, and every holdout row comes from the same snapshots the trainer saw.
Two assets add the missing number, from the scores the sweep actually wrote for reports no model trained on.

- **`inbox_ranking_served_scores` (dt=D)** (`training/served.py`) takes the dt=D state rows of the reports **created on D**, the pool the rows tag `pool=newborn`. A newborn has no scoring moment before D, and the dt=D examples stop at D minus the head's horizon (7 days at the shortest), so no example can cover it. It reads this deployment's `inbox_ranking_report_scored` events for that pool inside D and keeps the earliest `scored` event per (report, model key), so every model the manifest named is graded: the served model, the served family's `recent` versions, the `pinned` models, and the other families' `cross_family` champions. `model_role` comes from the event's roles: `served` when they hold it, else the first role, else `candidate`. The sweep scores a candidate only after a manifest names it, so a candidate's online cohort starts the day after it was trained, and it stays a `recent` entry until N newer versions replace it. Every head a model fit is scored, readable or not, and each row carries `head_readable` and the model's own `classification_threshold`. One Parquet row per (report, model key, head) carries the score, `age_hours`, `label_at_scoring` (the head outcome that had already happened when the report was scored, which for a newborn is one that landed on its own birth day, so the grade keeps it; a status-label head's rows are still dropped on it, because no scores column carries the scoring-day `label_provenance_ok` that the example builder checks), `model_name`, `model_role`, and `pool`. `served_pool_coverage` and `pool_coverage_by_model` say how much of the pool each model covered. A re-run that reads no event is refused when the partition already holds rows, and so is one that reads fewer families than the object already holds. Rows of a retired family (`RETIRED_MODEL_NAMES`) are dropped on read, and the rewrite guard does not require them.
- **`inbox_ranking_unseen_graded` (dt=D)** reads saved scores from D back through each head's horizon and evaluates them against the dt=D labels. Daily head evaluations include both unbaked and baked metrics, marked by `is_mature`; existing head, report and calibration grade events remain baked-only at `D - horizon_days`. See [baked and unbaked unseen metrics](../../../../docs/internal/inbox-ranking-training.md#baked-and-unbaked-unseen-metrics) for the event contract and chart revision rules. It keeps the rows whose cohort holds at D, reads the outcome with `Head.label`, and reports the AUC per model and head next to two comparison lines on the same rows: `recency_auc`, the AUC of ranking newest first by `report_created_at`, and `null_auc` / `null_auc_std`, the mean and spread of the AUC over seeded permutations of the scores. The mean is 0.5 by construction; the spread is the noise band a per-day AUC has to clear before a gap between two families means anything. It also reads the calibration of those scores, which no AUC can see: the in-cohort rows are cut into score deciles by rank (`training/calibration.py`, shared with the trainer so both sides cut them the same way), and each decile's mean score is compared against the rate the outcome actually happened at. A run of equal scores stays in one decile, so a head reports fewer deciles rather than a gap that only reflects the row order. Read each grade with the model's `pool_coverage_by_model`: a key that joined the manifest part of the way through D grades only part of the pool.

At the full horizon, the cohort, label and provenance rules are the trainer's own, so the baked online AUC is directly comparable to the holdout AUC of the same head and model version. The gap between the two series is the overfitting read the promotion gate cannot see.

The event names keep the `unseen` prefix so existing dashboard tiles keep reading. Three events carry the baked results, next to the daily `inbox_ranking_unseen_head_evaluated`: `inbox_ranking_unseen_head_graded` per (model, head) with `readable` (whether the head's holdout could be read on the model that wrote the scores), `model_role`, `rows`, `positives`, `birth_day_positives` (of the positives, how many landed on the report's birth day), `base_rate`, `mean_score`, `expected_calibration_error`, `auc` and `recency_auc`, `inbox_ranking_unseen_calibration` per (model, head, decile) with `bucket`, `rows`, `positives`, `mean_score` and `realized_rate` (one event per decile, because a table on the head event would be an array no insight can break down), and `inbox_ranking_unseen_report_graded` per (report, model, horizon) with `p_<head>`, `in_cohort_<head>` and `outcome_<head>` for a calibration read on the raw rows. Both graded events are stamped on the day the outcome was read and carry `scoring_partition`, the day the report was scored, so a chart can be built on either axis. Both also carry `pool`, read back from the scores object, so an AUC series never mixes two pool definitions: the grader reads scores from up to the longest head horizon (21 days) earlier, so the days after a pool change grade both populations. A scores object written before the column existed reads as `sampled`, the pool the old seeded sample defined.

#### Pooled and within-team AUC

The inbox sorts the reports of one team, so the order that matters is the order inside one team. Every grade reports two AUCs on the same rows, and each answers a different question:

- **Pooled AUC** (`holdout_auc` on a candidate, `auc` and `recency_auc` on the online grade) compares every report with every other report, across teams. It asks: does the model separate the reports that get the outcome from the reports that do not, anywhere? A model that only learns which teams engage a lot gains pooled AUC. A score equal to each team's past label rate gets a pooled AUC well above 0.5.
- **Within-team AUC** (`holdout_within_team_auc` on a candidate, `within_team_auc` and `recency_within_team_auc` on the online grade) compares only two reports of the same team. It asks: inside one inbox, does a report that gets the outcome rank above one that does not? The team-rate score gets exactly 0.5 here.

`within_team_auc` weighs each team by its positive x negative pairs, so a large team counts more. `within_team_auc_macro` is the mean of the per-team AUCs, so each team counts the same. `within_team_teams` and `within_team_pairs` say how much the number rests on. A team with one outcome class has no pair and adds nothing, and a row without a team id is left out of these four fields only. Both AUCs are null when no team has both classes.

Compare model families on the within-team AUC when they differ in team-level inputs, such as project vectors: a gain in pooled AUC alone can be team identity rather than a better order. The promotion gate still reads the pooled holdout AUC.

### Running the training job locally

The `nn` training job is S3-only, so it can run on a laptop against copies of the prod snapshots. The dataset job cannot: it needs the dogfood project's ClickHouse and cross-region Postgres.

1. With the dev stack up (`bin/start`; the script waits for object storage to accept requests), sync the two prefixes the job reads into the local object-storage bucket. This needs an SSO session with the `secrets-editor` role on `prod-us-secrets`, and the Secrets Manager id of the dataset reader credential (provisioned with the bucket; ask the owning team):

   ```bash
   aws sso login --profile prod-us-secrets
   INBOX_RANKING_READER_SECRET_ID=<secret id> products/signals/dags/inbox_ranking/bin/sync_snapshots_local.sh
   ```

   This copies `inbox_report_state/v1/dt=*` and `inbox_report_labels/v1/dt=*` to `~/.cache/posthog/inbox_ranking/` and from there into `s3://posthog/inbox_ranking/` on SeaweedFS (`localhost:19000`). `INBOX_RANKING_SYNC_EMBEDDINGS=1` adds `inbox_report_embeddings`, which the `nn` families need; it is off by default because that table carries a vector per live report per partition. Without it the `nn` assets skip the partition. `INBOX_RANKING_SYNC_TITLE_EMBEDDINGS=1` adds `inbox_report_title_embeddings` on its own switch and for the same reason. No family trains on it. It prints the partition days present in both tables; pick the **newest** of those as the partition to run. The `nn` examples asset reads the `INBOX_RANKING_TRAINING_LOOKBACK_DAYS` snapshots behind the partition it runs for, so an early day has little history behind it and trains on almost nothing. Re-runs only move new days.

   Note that the dev stack's object storage accepts unsigned requests and publishes port 19000 on every host interface, so anything synced here (and the disk cache) is readable by whoever can reach your machine. The snapshots are internal dogfood telemetry, not customer data, but run the sync on a network you trust.

2. Make sure `INBOX_RANKING_DATASET_S3_BUCKET` is unset for the Dagster process: `common.s3_client()` then talks to SeaweedFS and `dataset_bucket()` is `posthog`. Checking your shell (`env | grep INBOX_RANKING`) is not enough, because `bin/start` sources `.env.local` into the processes it starts; check that file too. If the variable reaches Dagster, the dag uses your ambient AWS credentials against that bucket, and the read-only credential the sync used protects nothing.

3. Launch `inbox_ranking_nn_training_job` for that partition as [The nn family](#the-nn-family) describes.

   The schedule is stopped outside prod US, so nothing runs unasked. If the run sits in `QUEUED`, check the daemon log for `Maximum is 10, won't launch more`: runs from a killed `dagster dev` stay `STARTED` forever and count against the local queue. Terminate them from the Runs page (force termination).

4. Read the result from `s3://posthog/inbox_ranking/inbox_ranking_models/v1/nn_v3/dt=<day>/metadata.json` (per-head AUCs, readability):

   ```bash
   AWS_ACCESS_KEY_ID=object_storage_root_user AWS_SECRET_ACCESS_KEY=object_storage_root_password \
       aws --endpoint-url http://localhost:19000 s3 cp s3://posthog/inbox_ranking/inbox_ranking_models/v1/nn_v3/dt=2026-08-25/metadata.json -
   ```

Nothing here touches the prod bucket: the reader credential is read-only and the dag writes only to the local bucket.

### The multi-head prototype

`multihead/` is an offline experiment and not a dag. It tests whether one shared network over the report vector, with or without the team's project vectors, beats the per-head XGBoost champion recipe of the `report_embeddings` family. It reads the disk cache the sync script fills, so sync with `INBOX_RANKING_SYNC_EMBEDDINGS=1` first. The dev stack does not need to be up.

The network is PyTorch. torch is not a main dependency: it comes from the `inbox-ranking` dependency group, with the CPU-only wheels, together with `onnx` and `onnxruntime`. The group conflicts with the `sentiment` group, which takes the CUDA build of torch, so install one or the other. Only `Dockerfile.dagster-ml`, the image of the `signals_ml` code location, installs the group. Each master push publishes that image, and `container-images-cd.yml` sends its digest to PostHog/charts with the `restart_dagster_ml_code_location` dispatch. A failed build or dispatch does not block CD.

```bash
uv sync --group inbox-ranking
DEBUG=1 python -m products.signals.dags.inbox_ranking.multihead --output multihead.json
```

`multihead/network.py` is the only module that imports torch. `multihead/inputs.py` holds the inputs and the settings, so the prototype and its callers build them without torch. Never import `network.py` from a module on the Django, Temporal or Dagster import path: `test_multihead_network.py` fails if torch reaches one. Without the group, the torch tests skip. `ci-inbox-ranking.yml` installs the group and runs them.

`export_onnx(network, path)` writes the network as one ONNX graph and returns its head order. The inputs are `report` (N x 1536) and, for the network with project vectors, `project` (N x 4 x 1536) and `has_history` (N x 4), all float32. The one output is `probabilities` (N x heads), after the sigmoid. N is a dynamic axis.

The run takes the newest day that has the state, labels and report embeddings cached, unless you pass `--partition`. It builds the `open`, `action` and `fixed` examples with the training dag's own `example_moments`, `cap_examples` and `holdout_mask`. Then it prints pooled AUC, within-team AUC (`team_auc`), average precision and ECE per head for three models on each head's own holdout rows:

- `champion_recipe` is the `XGB_PARAMS` booster, refit on the head's train rows.
- `nn_report` is the network over the report vector only.
- `nn_report_project` is the network over the report vector plus the `typical`, `open`, `action` and `dismiss` vectors from `project_vectors()`. A report born on day D reads them as of D 00:00 UTC.

The network leaves out every report that is in any head's holdout, so the comparison is conservative for it. A run holds one embeddings snapshot: the title embeddings are never read, and the project vectors are computed from the same table as the report vectors. Results vary with `--seed`, so compare a few seeds before you read a small AUC gap as a result.

### The nn family

`nn` is one multi-head network (`multihead/network.py`) over the report vector and the team's `typical`, `open`, `action` and `dismiss` project vectors, with the heads `open`, `action` and `fixed`. It is a model family like the per-head ones: it has its own prefix, the main job's serving manifest names a served, challenger or cross-family `nn` model as an `onnx` entry, and the online grader grades it. The main location fits no model.

Two `nn` families train every day. `nn_v3` reads the `report_embeddings` set. `nn_with_prio_v2` reads `report_embeddings_priority`: its `report` input carries the 1536 vector components and then the five priority levels, and those five columns skip the shared projection and go straight into the trunk input. Neither is served by default; a person serves one with `inbox_ranking_promote_job` after comparing their online grades.

`inbox_ranking_nn_training_job` lives on its own code location, `posthog/dags/locations/signals_ml.py`, which runs on an image with the `inbox-ranking` group. torch is imported only inside the candidate asset's body, so the location module imports on the main image too, and `test_multihead_network.py` fails if torch reaches it. The job writes:

```text
s3://<bucket>/<prefix>/
├── inbox_ranking_nn_examples/v1/dt=YYYY-MM-DD/   # rows, a label and a holdout flag per head, priority; no vectors
├── inbox_ranking_models/v1/nn_v3/
│   ├── dt=YYYY-MM-DD/model.onnx + model.holdout.onnx + metadata.json
│   └── champion.json   # retired; nothing writes it
└── inbox_ranking_models/v1/nn_with_prio_v2/dt=YYYY-MM-DD/model.onnx + model.holdout.onnx + metadata.json
```

- **Examples** are the prototype's: each head's `example_moments` over the `report_embeddings` set, capped by `cap_examples` and split by `holdout_mask`, so every head's rows and holdout are the ones its `report_embeddings` champion is graded on. The object holds no vector, and one object serves both families. Each row carries its `priority` from its own snapshot. The candidate and champion assets rebuild the report vectors and the project vectors from the dt=D embeddings and labels snapshots. An object written before the `priority` column existed makes the `nn_with_prio_v2` candidate skip with a warning; re-run the examples asset for that day.
- **Candidate**: the network trains on the rows in no head's holdout and is graded on each head's own holdout through the shared `head_metrics`, so `metadata.json` carries the same per-head fields as the retired booster families (pooled and within-team AUC, average precision, ECE, readability, row counts, example window). Readability uses a permutation null: three networks fit on permuted labels. `model.onnx` is a refit on every labeled row, and `model.holdout.onnx` is the train-only fit. `metadata.json` has `model_kind: onnx`, the family's `feature_set`, and `output_heads`, the graph's column order. The `nn_with_prio_v2` candidate runs after the `nn_v3` champion, for memory and not for data: each candidate holds an embeddings snapshot and the project vectors.
- **Champion**: the same rule as the other families (`decide_family_champion`), recorded and never written to a pointer. The incumbent is the served model when it has the candidate's `model_name`, graded through its `model.holdout.onnx` on the candidate's holdout, with `onnxruntime`.
- **A missing partition is a skip.** If the dt=D state, labels or embeddings snapshot is missing, each asset logs and writes nothing, so the partition keeps the objects it holds.
- **Schedule**: 04:30 UTC, after the dataset job's 2h budget (02:30 UTC start) and before the 05:00 UTC training job when the run is short enough. A candidate that lands after that day's manifest is paired by the next day's manifest. The schedule runs by default on prod US and is stopped everywhere else.

To run it locally, install the group (`uv sync --group inbox-ranking`), sync the snapshots with `INBOX_RANKING_SYNC_EMBEDDINGS=1` as in [Running the training job locally](#running-the-training-job-locally), and uncomment `posthog.dags.locations.signals_ml` in `.dagster_home/workspace.yaml`. The entry is commented out because most developers do not have torch installed. Then launch the job:

```bash
dagster job launch -w .dagster_home/workspace.yaml --location posthog.dags.locations.signals_ml \
    -j inbox_ranking_nn_training_job --tags '{"dagster/partition": "2026-08-25"}'
```

### Experiment families

An experiment is a `MODEL_FAMILIES` entry with `experiment=True`, a `baseline` serving family and an `expires` day (`training/families.py`). It tests a modeling idea without a serving family's costs:

- **Its own job.** `inbox_ranking_nn_experiments_job` (`nn/experiments.py`, on `signals_ml`) trains every live experiment, one after the other. It has its own runtime and memory tags, so it never uses the `nn` job's budget. It holds three assets, run one step at a time in one process: `inbox_ranking_nn_experiment_candidates` (the report-grain experiments), `inbox_ranking_nn_pair_examples` and `inbox_ranking_nn_pair_experiment_candidates` (the pair-grain experiments, after the pair examples). The report experiments do not depend on the pair examples, so a failed pair step skips only the pair experiments. Its schedule (08:00 UTC, after the `nn` job's 3h budget) selects the report asset when a report experiment is live and the two pair assets when a pair experiment is live, and skips when nothing is live.
- **No new examples.** It reads the day's `inbox_ranking_nn_examples` object. A day without that object is skipped, and so is a family after its `expires` day.
- **Never served.** The serving manifest reads only `serving_families()`. The pin check refuses an experiment key, so the promote job, the served pointer and the pins cannot name one. To serve the recipe, register it as a serving family under a new `model_name`.
- **Paired read.** The experiment and its baseline each fit once per seed in `EXPERIMENT_SEEDS`, on the same train rows. `metadata.json` holds a `vs_baseline` block per head: each seed's within-team and pooled holdout AUC for both arms, and the mean, min and max of the gaps. One `inbox_ranking_experiment_compared` event per head carries the gaps.
- **Side inputs.** A side input beyond the report vectors needs a loader in `training/side_inputs.py`. The registry refuses a frame without a timezone-aware `as_of_column` and drops the rows known after the partition end. A feature set in the dags reads the frame through `rows_as_of`. A set in `features.py` cannot import the dags, so it applies the same `<= as_of` cut on the loader's column itself.

The live report-grain experiment is `nn_with_prio_sources_v1`, graded against `nn_with_prio_v2` until 2026-11-11. The pair-grain experiments are under [User-history families](#user-history-families). Its set, `report_embeddings_priority_sources`, adds the source products of the report's signals: one column per product in a fixed vocabulary, `source_other`, `source_count` and `has_sources`. The `report_sources` loader reads only the metadata columns of `inbox_signal_embeddings`, from 30 days before the training lookback to dt=D. A moment takes the latest emission per `(team_id, signal_id)` inserted at or before it and drops a retracted signal. It never reads the impression labels' `source_products` column, which holds the latest impression's value. The scoring sweep cannot build this set, so the recipe needs serving work before it can become a serving family.

The schedule is a fallback. To read an experiment on a chosen day, launch the job for that partition from the Dagster UI or the CLI:

```bash
dagster job launch -w .dagster_home/workspace.yaml --location posthog.dags.locations.signals_ml \
    -j inbox_ranking_nn_experiments_job --tags '{"dagster/partition": "2026-10-20"}'
```

The newest day you can launch is the newest day the `nn` job finished. Adjacent days share most of their train and holdout rows, so their reads are not independent. Judge a `vs_baseline` gap on spaced days, for example every 7th day.

### Pair examples

`inbox_ranking_nn_pair_examples` (`nn/pairs.py`) holds the report-user pairs for a personal ranking lane: a model that reads a vector of the reports one user viewed before, next to the report.
It writes `inbox_ranking_nn_pair_examples/v1/dt=D/` with its own `PAIR_EXAMPLES_SCHEMA_VERSION`, and runs in its own job, `inbox_ranking_nn_pair_examples_job`, which has no schedule. The experiments job also builds it for the partition it trains, before the pair experiments. Launch the pair examples job alone to inspect a partition before any model reads it.

- **Rows**: one per (report example, user), for each user impressed with the report within `PAIR_HORIZON_DAYS` (7) of birth. The report rows are the `open` head's rows of the dt=D `inbox_ranking_nn_examples` object, so the report inputs, the holdout split (`holdout` is the row's `open_holdout`) and the day windows are the report lane's. A report born on day B reads its impressions from the dt=B+7 `inbox_user_report_interactions` partition, the partition the report's `open` label reads.
- **Labels**, from the same partition and before its end: `open_label` is the user's `first_opened_at`, and `action_label` is any of the user's UI action `first_*` columns from `UI_ACTION_COLUMNS`, the set the `action` project vector reads. There is no `fixed` label, because a fix belongs to the report and not to a user.
- **User inputs**, as of the start of day B, from the dt=D interactions and embeddings snapshots: `user_open_reports` and `user_dismiss_reports` (the reports in each `user_vectors()` mean), `prior_views` (every view before B, without the limit or the embedding gate), `days_since_last_view` (capped at `DAYS_SINCE_VIEW_CAP`) and `has_history`. The report and the reports born with it are outside the history by construction.
- **`is_suggested_reviewer`** comes from the dt=B `inbox_report_reviewers` partition when it exists, and from `impressed_as_suggested_reviewer_count` otherwise. `suggested_reviewer_source` says which (`reviewers` or `impressions`).
- **No vectors.** The object holds the user inputs above and the keys `report_id`, `report_team_id` and `user_distinct_id`. A reader rebuilds the `open` and `dismiss` user vectors with `pair_user_vectors`, which calls `user_vectors()` once per birth day.
- **Consent**: only reports and history of teams in `training_consent_team_ids()`, read at run time.
- **Metadata**: `rows`, `users`, `reports`, positives per label, rows and users per prior-view bucket (`0`, `1_9`, `10_49`, `50_plus`), and `suggested_reviewer_share`.
- **A missing input is a skip.** Without the dt=D examples, interactions or embeddings object, the asset writes nothing. A birth day without its dt=B+7 interactions partition gives no pairs and is counted in `birth_days_without_impressions`.

`user_vectors(interactions, embeddings, as_of, organizations=...)` in `dataset/project_vectors.py` builds one row per (organization, user, kind) with `vector`, `n_reports`, `last_at` and `as_of`.
The `open` kind reads `first_viewed_at`, the durable VIEW row, and the `dismiss` kind reads `first_ui_dismissed_at`.
The vector is the plain mean of the user's last `USER_HISTORY_LIMIT` (20) reports of the kind, through the as-of rule and the embedding gate of `project_vectors()`.
A report counts only in the organization of its own team, and a user without usable history gets no row.

### Pair-grain experiments

A family with `grain="pair"` scores one row per (report, impressed user) from `inbox_ranking_nn_pair_examples`. Pair grain is experiment-only: `ModelFamily` refuses a pair-grain serving family, so the manifest, the promote job and the pins never see one.

- **Registration.** A pair family declares its `heads` from `PAIR_HEAD_NAMES` (`open`, `action`; there is no pair `fixed` label). Its `baseline` is another pair experiment in the registry, and its optional `reference` is a report-grain serving family. It names a baseline, a reference, or both. `family_problems` refuses a baseline of the other grain, an unregistered pair baseline, a baseline cycle and a reference that is not a report-grain serving family.
- **Lane.** The experiments job routes a pair family to `nn/pair_lane.py`. A day without the pair examples object skips the pair families only, with a log line. A pair takes its report's input and state columns from the report's row of the day's `inbox_ranking_nn_examples` object, and its team's project vectors as of its birth day. The experiment and its baseline fit with each of `EXPERIMENT_SEEDS` on the same train pairs and are graded on the same holdout pairs.
- **Reference.** For each seed, the reference fits at report grain on the report train rows born on a pair train day, and each holdout pair takes its report's score. The reference fits before the pair matrices are built, so its report matrix and the pair matrices are never in memory together.
- **Grade.** `vs_baseline` (`nn/pair_grade.py`) has `grain: "pair"` and, per head, within-user AUCs for each arm and seed. A user is one person in one team, and a user with one outcome class is left out. `macro` weighs each user the same, and `pooled` weighs each user by its pairs. The scopes are `all` and `non_dogfood` (without the dogfood project's users). The slices are `all`, the prior-view buckets, `history_10_plus`, `suggested_reviewer` and `not_suggested_reviewer`. `vs_baseline` and `vs_reference` give the mean, min and max delta over the paired seeds, and a team bootstrap interval for the macro delta. One `inbox_ranking_experiment_compared` event per head, scope and slice carries `grain`, `scope`, `slice` and the deltas against both arms. Report-grain experiments keep their block and their events as they were.

#### User-history families

`nn_pair_user_v1` and `nn_pair_base_v1` ask whether a user's own inbox history improves the ranking. Both train until 2026-11-25, with heads `open` and `action` and `nn_with_prio_v2` as the reference. `nn_pair_user_v1` names `nn_pair_base_v1` as its baseline, and the base has no pair baseline.

- **Same network.** Both read the `report_embeddings_priority` columns, the team's project vectors, `is_suggested_reviewer` and the same user-history inputs, in one input shape, on the same pairs and seeds.
- **User inputs** (`PairUserHistoryFeatureSet` in `products/signals/backend/ranking/features.py`): `log1p` of `user_open_reports` and `user_dismiss_reports`, `days_since_last_view` over its 90-day cap, `has_user_history`, and a `user` graph input. That input holds, per kind (`open`, `dismiss`), the user's vector minus the team's project vector of the kind (`user_offsets`). An offset is zero when the user has no report of the kind or the team's kind has too thin a history. A cold-start user reads zero offsets, zero counts and the capped recency, and gets a finite score from the same network.
- **The base reads no history.** `nn_pair_base_v1`'s set holds every user column and offset at zero, whatever the pair rows hold, and keeps the reviewer flag. So `nn_pair_user_v1` against `nn_pair_base_v1` is the uplift of the user's history alone, and the change of grain and the reviewer flag are in both arms.
- **Per pair.** The lane builds each arm's inputs from the pair rows. The report part is built once per report, and the user columns and offsets come from each pair's own user, so two users of one report never share them. The user vectors come from `pair_user_vectors` on the dt=D interactions snapshot of teams in `training_consent_team_ids()`, inside each team's organization, as of the start of the birth day. A family that reads user history skips a partition without that snapshot.
- **Metadata.** A pair candidate records `user_vector_kinds`, and its recipe records them with `user_vector_settings`. The asset metadata adds `pair_rows`, `pair_users` and `pair_rows_with_prior_views` per family.

To run both families for one partition, launch the experiments job on the `posthog.dags.locations.signals_ml` location with the tag `dagster/partition` set to the day (`YYYY-MM-DD`), as in the command above. The job needs no run config. A launch without an asset selection runs all three assets, so it also trains the report-grain experiments. To train only the pair families, select `inbox_ranking_nn_pair_examples` and `inbox_ranking_nn_pair_experiment_candidates`. Launch a day the `nn` job finished, and whose dt=D interactions and embeddings snapshots and dt=B+7 interactions partitions exist.

Before the first read, launch `inbox_ranking_nn_pair_examples_job` alone on a recent day and check its metadata: `rows`, `users`, positives per label, rows and users per prior-view bucket, and `suggested_reviewer_share`. The `history_10_plus` holdout needs users with both classes in enough teams for the within-user grade and its team bootstrap to read.

Lead the read with the macro within-user AUC delta of `nn_pair_user_v1` against `nn_pair_base_v1`, in `scope=non_dogfood`, `slice=all`, for `open` and `action`, next to its `vs_reference` delta. Then read the history buckets, `history_10_plus` and the reviewer slices. The predeclared bar for a go is a positive macro delta in `history_10_plus` outside dogfood on `open` or `action`, on at least 3 partitions about 7 days apart, with a team bootstrap interval above zero on at least one, and no bucket below 10 views worse than the base beyond seed noise.

## Configuration

| Setting                                 | Default         | Meaning                                                                                                                                                                                                             |
| --------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `INBOX_RANKING_DATASET_S3_BUCKET`       | unset           | Destination bucket. Unset on Cloud makes every asset log and skip, so the dag can deploy before the bucket exists. Unset elsewhere falls back to the deployment's object-storage service (SeaweedFS in dev and CI). |
| `INBOX_RANKING_DATASET_S3_PREFIX`       | `inbox_ranking` | Key prefix under the bucket.                                                                                                                                                                                        |
| `INBOX_RANKING_TRAINING_LOOKBACK_DAYS`  | `90`            | How many daily snapshots back the training examples reach.                                                                                                                                                          |
| `INBOX_RANKING_TRAINING_HOLDOUT_DAYS`   | `7`             | Trailing days of reports that grade a candidate.                                                                                                                                                                    |
| `INBOX_RANKING_SERVING_MIRROR_BUCKET`   | unset           | A second deployment's object-storage bucket that receives a copy of every serving publish, through ambient AWS config. Unset means no mirror.                                                                       |
| `INBOX_RANKING_SERVING_MIRROR_REGION`   | unset           | AWS region of the mirror bucket.                                                                                                                                                                                    |
| `INBOX_RANKING_SERVING_RECENT_VERSIONS` | `2`             | How many of the served family's newest versions the manifest carries under the `recent` role, read from the last 2N days. Each one adds one model to every sweep pass and takes an entry a challenger could use.    |
| `INBOX_RANKING_SCORING_BATCH_SIZE`      | `500`           | Report ids per ClickHouse vector read in the scorer. A larger call is paged at this size.                                                                                                                           |

Writes use boto3: ambient AWS config (the node role) when the dedicated bucket is set, the `OBJECT_STORAGE_*` endpoint and credentials otherwise. Readers (project-level warehouse tables, model training) use a separate read-only credential provisioned with the bucket.

## ClickHouse posture

All reads route to the offline cluster replicas on Cloud (`etl_workload()`), carry the dagster run in `log_comment`, and the cross-team embeddings scan runs under explicit time/memory/spill guards (see `queries.py` for why that scan still reads nearly the whole table, even with the training consent `team_id` list, and why that is acceptable).

## Operating it

- Backfill any day range from the Dagster UI; partitions start 2026-04-01 (the label epoch). Every asset sits in the `inbox_ranking_etl` pool so concurrent partitions don't each start their own fleet-wide embeddings scan — the pool's limit is a Dagster deployment setting, provisioned with the bucket.
- A label column change needs a `FEATURE_SCHEMA_VERSION` bump, and no manual backfill. The labels asset stamps the version in each object's `feature-schema-version` metadata. Every hour, `inbox_ranking_labels_refresh_sensor` finds labels partitions in the training lookback whose stamp is missing or older, and runs `inbox_ranking_labels_refresh_job` on at most `INBOX_RANKING_LABELS_REFRESH_MAX_RUNS` (default 6) of them, newest first. A 90-day lookback is current again in about 15 hours. The sensor skips the newest day, which the daily schedule writes, and partitions with no labels object. It requests a partition at most once per schema version, so a failed refresh alerts and needs a person. The refresh covers labels only: report state reads current Postgres and embeddings have a TTL, so a rewrite of those is not point-in-time. A head loses the snapshot pairs whose label column is missing while partitions are stale.
- Do not materialize these assets in-process in the code-location pod. Its memory limit (2Gi) is too small; launch a run instead.
- Failures alert `#alerts-self-driving` (owner `team-self-driving`); assets retry twice with a 60s delay before failing a run. A UI-launched materialization runs under Dagster's implicit `__ASSET_JOB`, which carries no owner tag, so alert routing falls back to matching the `inbox_report_`, `inbox_signal_`, and `inbox_ranking_` asset-name prefixes.
- Runtime budgets are per job (`dagster/max_runtime`): 2h for the dataset job, 1h for the training job, 3h for the `nn` training job. The dataset needs the 2h: its seven label streams run sequentially, each allowed up to 600s, and the join and S3 writes come after them. The dataset cap ends before training starts at 05:00 UTC, so a stuck dataset run fails before training reads its snapshots.

## Training consent

The dags train only on reports from organizations whose `Organization.is_ai_training_opted_in` is `True`.
`False` and `None` both mean no consent.
`consent.training_consent_team_ids()` returns the consenting teams that hold an inbox report, and every asset reads it once per run.

- `inbox_report_state` keeps only the spine reports of those teams. A label event that names another team's report does not pull it back in. That report's labels still land in `inbox_report_model_data` as a label-only row, which training skips.
- `inbox_report_embeddings`, `inbox_report_title_embeddings`, `inbox_signal_embeddings` and `inbox_activity_summary_vectors` read only those teams, through `team_id IN (...)` in the ClickHouse query.
- The `nn` examples asset drops every state row whose `report_team_id` is not in the current set, before it builds examples. The lookback window reaches partitions written before an organization opted out, so this filter is what makes an opt-out take effect on the next training run.

The filter follows the current setting, so an organization that opts back in is trained on again.
The state asset and the `nn` examples asset record `excluded_no_training_consent_reports` and `excluded_no_training_consent_teams` as metadata. They are counts, never ids.
The online grade reads the dt=D state snapshot for its newborn pool, so that pool shrinks to consenting teams too. Scoring in the sweep does not change.
The filter does not delete existing partitions or models. A re-run of `inbox_signal_embeddings` stays additive, so rows that an older run wrote remain in that partition. The `report_sources` side input reads only its metadata columns, and the example rows it joins to already drop the teams without training consent.

## Deletion and retention

Partitions are immutable history, so a report deleted later keeps its rows (and vector) in partitions written before the deletion.
The embedding tombstone nulls the vector in every partition built after it, and `status='deleted'` flows through state from then on.
**A re-run does not scrub a deleted report.** Label telemetry lives in the dogfood project and outlives the Postgres row, so a re-run regenerates the report as a label-only row: the id, its action/status/dismissal labels, and its team id come back, only the state columns go null.
Scrubbing therefore means deleting the affected `dt=` objects (and rebuilding `latest/`), not re-running the partitions.
The same holds for signal rows, with one addition: a retraction can expire out of the source before any run scans it, so a scrub cannot be driven off `is_deleted` in this archive and has to work from the deleted report's id.
Nothing in the team-deletion path knows about this prefix today, so the purge is manual until that is wired up - tracked with the bucket provisioning, and nothing is at risk before then because the assets write nothing until the bucket exists.
The bucket is internal-only and access-restricted; a lifecycle policy for old partitions is a provisioning-time decision.
