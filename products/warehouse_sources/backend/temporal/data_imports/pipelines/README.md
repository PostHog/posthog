# Warehouse sources pipelines

A "pipeline" here is any of the data flows that move customer data from an external source into the warehouse, plus the auxiliaries that tap or follow them.
They share one kernel (`core/`, `common/`) but attach to the sync flow at different points.
This page is the map; each package's own docstrings and READMEs carry the detail.

## The sync flow

1. A per-schema Temporal schedule fires `ExternalDataJobWorkflow` (`../external_data_job.py`).
2. The workflow evaluates the v3 rollout flag once (`check_pipeline_version_activity`) and, for v3, takes the per-schema Redis sync lock (`pipeline_v3/sync_lock.py`).
3. `create_external_data_job_model_activity` creates the job row and persists `pipeline_version` on it - the single source of truth every later step consults.
4. `import_data_activity_sync` (`../workflow_activities/import_data_sync.py`) builds the source's `SourceResponse` and runs the pipeline the persisted version selects.
5. Post-load (`common/load.py::run_post_load_operations`): delta maintenance, publish queryable files, register the table, CDC companion handling, `POST_LOAD_STEPS`.
6. Finalization (terminal job status, v3 lock release, post-import start) is owned per run: the workflow, or the v3 load consumer once it loads the final batch.
   The contract lives on the `PipelineResult` docstring (`core/typings.py`).
   A run that fans out to several destinations finalizes differently - see [Destinations](#destinations).
7. The post-import workflow (`../post_import_job.py`, `data-import-post-import`) runs the load-dependent step list (table size, DuckLake copy, signals, enrichment, statistics).

## Destinations

A schema syncs to a set of destinations, of which the PostHog warehouse is one rather than a special case.
Absence of configuration resolves to the warehouse alone, so a source set up before destinations existed behaves exactly as it did.
Gated by the `warehouse-multi-destination` flag, evaluated once in `create_external_data_job_model_activity` and carried into the workflow as recorded history.

- **Configuration.** `ExternalDataDestination` is team-scoped and reusable; credentials live on a linked `Integration`, not in its config.
  Source-level links are the default set, schema-level links override them, and clearing the override restores inheritance (`models/external_data_destination.py::resolve_destinations`).
- **Jobs.** Each run creates one `ExternalDataDestinationJob` per resolved destination. The parent `ExternalDataJob` still owns extraction; its status becomes the aggregate.
- **Queue.** The producer writes one `sourcebatchdestination` work item per batch per destination, in the batch's transaction, plus a `sourcerundestination` snapshot on batch 0 because the queue database cannot read the app database.
- **Consumers.** One engine, two deployments split by claim scope: `run_warehouse_sources_load` claims `PostHogWarehouse`, `run_warehouse_sources_destinations_load` claims the rest, with a much softer retry budget (8 attempts, 300s backoff) because a destination is someone else's database.
- **Finalization.** Each consumer finalizes only its own child; the last child to land closes the run (`destination_finalization.py`).
  The parent stays `Running` until every child is terminal, because a terminal failed parent sweeps the queue and would cut off a sibling mid-run.
  Paths that own the whole run - extraction failed, cancelled, lock takeover - fail the parent directly and cascade to the children.
- **The cursor** promotes only when every destination succeeded, so a destination cannot develop a permanent gap: a run repeated because a sibling failed re-extracts the same window and the healthy destinations merge it again.
  Because of that repeat, a destination that already delivered a window is created non-billable on the retry (`destination_jobs.py`).
- **Billing** sums the children when a run has them and the parent when it does not. Only completed destinations bill.
- **Falling behind** is bounded by queue retention (7 days), not by patience: past that the staged parquet is gone and the run must be re-extracted. Alert on `oldest_eligible_age_seconds`.

CDC is excluded for now: it ticks a final batch continuously, which has no run-scoped commit for a destination to swap into.

## The pipelines

| Pipeline                             | Lives in                                                                                               | Attaches at                                                                                                                                                                                                                                                                                           |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| v2 extract+load (`PipelineNonDLT`)   | `pipeline_v2/`                                                                                         | Step 4 when `pipeline_version == V2`; writes Delta inline per chunk, so extract and load are one activity. The workflow finalizes.                                                                                                                                                                    |
| v3 extract (`PipelineV3`)            | `pipeline_v3/pipeline.py`, `pipeline_v3/s3/`, `pipeline_v3/postgres_queue/producer.py`                 | Step 4 when `pipeline_version == V3`, under the sync lock; writes parquet batches to S3 and enqueues them (`ExportSignalMessage`, `pipeline_v3/messages.py`) on the Postgres load queue.                                                                                                              |
| v3 load                              | `pipeline_v3/postgres_queue/`, `pipeline_v3/batch_consumer.py`, `pipeline_v3/load/`                    | Its own deployment (`run_warehouse_sources_load`), not the workflow: claims queued batches, writes Delta via `core/delta/`, finalizes the job, releases the lock, starts post-import. When the run fans out it finalizes the warehouse's child instead (`pipeline_v3/load/warehouse_destination.py`). |
| Destination load                     | `pipeline_v3/destinations_queue/`, `pipeline_v3/destinations_load/`                                    | Its own deployment (`run_warehouse_sources_destinations_load`): claims the same runs' work items for external destinations, streams the staged parquet, and writes through a `DestinationWriter`. See [Destinations](#destinations).                                                                  |
| CDC                                  | `../cdc/`                                                                                              | Outside the scheduled flow: the `cdc-extraction` Temporal workflow tails the source WAL and enqueues to the same Postgres queue (jobs are created as V3). The load consumer writes the snapshot table and the `_cdc` SCD2 companion (`core/delta/scd2.py`).                                           |
| Webhooks                             | `run_webhook_s3_sink` command; sink behind the `data_warehouse` facade                                 | Buffered ingress: deliveries are buffered to S3 continuously, and the next scheduled sync drains them as ordinary source items (webhook-only schemas skip table resets, `common/extract.py`).                                                                                                         |
| Chunk sinks (CDP, person properties) | `core/sinks.py`, `core/cdp_producer.py`, `core/person_property_row_sink.py`                            | Gated taps on both write loops, one `stage_chunk` call per chunk (see `ChunkSink`). Downstream: `dwh-cdp-producer-job` produces staged chunks to Kafka for HogFunctions/HogFlows; `sync-warehouse-person-properties` plus `run_person_property_update_consumer` upsert person properties.             |
| Post-import steps                    | `../post_import_job.py`, children under `../workflow_activities/`                                      | Step 7. Started by whoever finalizes the run (step 6); gates are resolved once in its resolve activity, then the workflow is a loop over recorded step keys.                                                                                                                                          |
| Repartition                          | `core/repartition.py`, `core/repartition_controller.py`, `../workflow_activities/repartition_table.py` | Detection is a `POST_LOAD_STEPS` entry (flags oversized partitions); execution is `maybe_repartition_table_activity`, pre-extraction on the next run while the lock is held.                                                                                                                          |

## The shared kernel

- `core/` - version-neutral pieces both pipelines use: `batcher.py`, `arrow_utils.py`, `partitioning.py`, `hogql_schema.py`, `sinks.py`, the repartitioner, and `typings.py` (`PipelineResult`).
- `core/delta/` - everything Delta Lake, one concern per module: `table.py` (`DeltaTableRef`, the single stateful handle threaded through a run), `writer.py`, `scd2.py`, `maintenance.py`, `evolution.py`, `ops.py`, `errors.py`.
  The write/maintenance classes are stateless wrappers constructed at their call sites over a `DeltaTableRef`.
- `common/` - the sync-flow helpers shared by v2 and v3: `extract.py` (reset/corruption handling, incremental bookkeeping) and `load.py` (`run_post_load_operations`).
- `pipeline_sync.py`, `helpers.py` - table registration and naming.

Dependency rule: `pipeline_v2/` and `pipeline_v3/` import from `core/` and `common/`; `core/` imports from no pipeline.
One remaining exception: several `core/` modules still import the shared write metrics from `pipeline_v3/load/metrics.py`.
Cross-product coupling goes through `../external_product_hooks.py` (registration) rather than direct imports.
