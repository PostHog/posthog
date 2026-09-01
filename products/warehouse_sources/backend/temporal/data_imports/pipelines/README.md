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
7. The post-import workflow (`../post_import_job.py`, `data-import-post-import`) runs the load-dependent step list (table size, DuckLake copy, signals, enrichment, statistics).

## The pipelines

| Pipeline                             | Lives in                                                                                               | Attaches at                                                                                                                                                                                                                                                                               |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| v2 extract+load (`PipelineNonDLT`)   | `pipeline_v2/`                                                                                         | Step 4 when `pipeline_version == V2`; writes Delta inline per chunk, so extract and load are one activity. The workflow finalizes.                                                                                                                                                        |
| v3 extract (`PipelineV3`)            | `pipeline_v3/pipeline.py`, `pipeline_v3/s3/`, `pipeline_v3/postgres_queue/producer.py`                 | Step 4 when `pipeline_version == V3`, under the sync lock; writes parquet batches to S3 and enqueues them (`ExportSignalMessage`, `pipeline_v3/messages.py`) on the Postgres load queue.                                                                                                  |
| v3 load                              | `pipeline_v3/postgres_queue/`, `pipeline_v3/batch_consumer.py`, `pipeline_v3/load/`                    | Its own deployment (`run_warehouse_sources_load`), not the workflow: claims queued batches, writes Delta via `core/delta/`, finalizes the job, releases the lock, starts post-import.                                                                                                     |
| CDC                                  | `../cdc/`                                                                                              | Outside the scheduled flow: the `cdc-extraction` Temporal workflow tails the source WAL and enqueues to the same Postgres queue (jobs are created as V3). The load consumer writes the snapshot table and the `_cdc` SCD2 companion (`core/delta/scd2.py`).                               |
| Webhooks                             | `run_webhook_s3_sink` command; sink behind the `data_warehouse` facade                                 | Buffered ingress: deliveries are buffered to S3 continuously, and the next scheduled sync drains them as ordinary source items (webhook-only schemas skip table resets, `common/extract.py`).                                                                                             |
| Chunk sinks (CDP, person properties) | `core/sinks.py`, `core/cdp_producer.py`, `core/person_property_row_sink.py`                            | Gated taps on both write loops, one `stage_chunk` call per chunk (see `ChunkSink`). Downstream: `dwh-cdp-producer-job` produces staged chunks to Kafka for HogFunctions/HogFlows; `sync-warehouse-person-properties` plus `run_person_property_update_consumer` upsert person properties. |
| Post-import steps                    | `../post_import_job.py`, children under `../workflow_activities/`                                      | Step 7. Started by whoever finalizes the run (step 6); gates are resolved once in its resolve activity, then the workflow is a loop over recorded step keys.                                                                                                                              |
| Repartition                          | `core/repartition.py`, `core/repartition_controller.py`, `../workflow_activities/repartition_table.py` | Detection is a `POST_LOAD_STEPS` entry (flags oversized partitions); execution is `maybe_repartition_table_activity`, pre-extraction on the next run while the lock is held.                                                                                                              |

## The shared kernel

- `core/` - version-neutral pieces both pipelines use: `batcher.py`, `arrow_utils.py`, `partitioning.py`, `hogql_schema.py`, `sinks.py`, the repartitioner, and `typings.py` (`PipelineResult`).
- `core/delta/` - everything Delta Lake, one concern per module: `table.py` (`DeltaTableRef`, the single stateful handle threaded through a run), `writer.py`, `scd2.py`, `maintenance.py`, `evolution.py`, `ops.py`, `errors.py`.
  The write/maintenance classes are stateless wrappers constructed at their call sites over a `DeltaTableRef`.
- `common/` - the sync-flow helpers shared by v2 and v3: `extract.py` (reset/corruption handling, incremental bookkeeping) and `load.py` (`run_post_load_operations`).
- `pipeline_sync.py`, `helpers.py` - table registration and naming.

Dependency rule: `pipeline_v2/` and `pipeline_v3/` import from `core/` and `common/`; `core/` imports from no pipeline.
One remaining exception: several `core/` modules still import the shared write metrics from `pipeline_v3/load/metrics.py`.
Cross-product coupling goes through `../external_product_hooks.py` (registration) rather than direct imports.
