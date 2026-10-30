# Warehouse sources pipelines

A "pipeline" here is any of the data flows that move customer data from an external source into the warehouse, plus the auxiliaries that tap or follow them.
They share one kernel (`core/`, `common/`) but attach to the sync flow at different points.
This page is the map; each package's own docstrings and READMEs carry the detail.

## The sync flow

1. A per-schema Temporal schedule fires `ExternalDataJobWorkflow` (`../external_data_job.py`).
2. The workflow takes the per-schema Redis sync lock (`pipeline_v3/sync_lock.py`).
3. `create_external_data_job_model_activity` creates the job row with `pipeline_version` set to V3.
4. `import_data_activity_sync` (`../workflow_activities/import_data_sync.py`) builds the source's `SourceResponse` and runs the v3 extraction. It fails a job row with any other pipeline version.
5. Post-load (`common/load.py::run_post_load_operations`): delta maintenance, publish queryable files, register the table, CDC companion handling, `POST_LOAD_STEPS`.
6. Finalization (terminal job status, v3 lock release, post-import start) is owned per run: the workflow, or the v3 load consumer once it loads the final batch.
   The contract lives on the `PipelineResult` docstring (`core/typings.py`).
   A run that fans out to several destinations finalizes differently - see [Destinations](#destinations).
7. The post-import workflow (`../post_import_job.py`, `data-import-post-import`) runs the load-dependent step list (table size, DuckLake copy, signals, enrichment, statistics).

## Append runs that end early

An append run commits each batch to Delta, but its watermark moves only when the run completes.
A run that ends before its final batch (a cancel, a failure, a retried attempt) would leave rows that the next run reads again, and an append has no key to merge them on.
The loader records the table version at the first batch of each append run in `sync_type_config["append_run_in_progress"]`.
The first batch of the next fresh run restores the table to that version when the recorded run never completed (`pipeline_v3/load/append_rollback.py`).
A resumed attempt keeps the rows of the attempt before it.
The restore covers the PostHog warehouse table only, not an external destination.

## Incremental runs that load a table from empty

An incremental run merges each batch on the primary key.
A first sync and a reset are different: the table is empty, so the first batch overwrites the table and the later batches append.
A merge into such a table finds no row to update, but it must read the key columns of each file to prove that.
An attempt that loads this way and reads the source from the start records itself in `sync_type_config["table_rebuild_run_uuid"]` (`pipeline_v3/table_rebuild.py`).
A later attempt of the same workflow run that also reads from the start loads the same way, and the loader skips the batches of the attempt that it replaced.
An attempt that continues from a cursor merges, because it can read a row again that an earlier attempt already queued.
The append keeps one row for each key in a batch, not in the run: a key that the source holds in two batches stays twice until a later run merges that key.

## Incremental runs that replace rows by file

A source that has no primary key can name the origin of each row instead, for example the file it came from.
It sets `SourceResponse.replace_scope` (`ReplaceScope` in `sources/common/typings.py`): a column, the values this run reads again (`replaced`), and the values that are live now (`retained`).

- The pipeline writes the two value sets to `replace_scope.parquet` in the run's folder (`pipeline_v3/replace_scope.py`). Each queue row carries only the column and the manifest path, under `replace_scope` in its metadata.
- Before batch 0 of a fresh attempt writes, the loader deletes each row whose value is in `replaced` or not in `retained` (`pipeline_v3/load/replace_rows.py`). It reads the values in the table from one column, and deletes in commits of up to 1,000 values. Then every batch of the run appends.
- The delete commits do not carry the batch tag, so a batch that failed after its deletes still writes on redelivery. A second delete of the same values finds nothing more to delete.
- The attempt records itself in `sync_type_config["replace_scope_run_uuid"]`, and the loader drops each later batch of an earlier attempt of the same workflow run. The producer also supersedes the queue rows of earlier attempts. The new attempt deletes the rows of every file that an earlier attempt read again.
- A run that reads no rows queues one empty batch, so a scope that only removes rows still reaches the loader.
- A first sync and a reset load into an empty table, so they do not send a scope. A row with no value in the column stays.
- The watermark does not change: it moves only when the run completes, so a failed run reads and deletes the same files again.

## Incremental runs that fail part way

The final batch of a run promotes the run's staged watermark, so a run that fails after many loaded batches would make the next run read all of them again.
With `DATA_WAREHOUSE_IMPORT_PREFIX_WATERMARK_ENABLED`, the watermark also moves each time batches `0..k` of a run are all loaded.

- Only an incremental merge on a primary key qualifies, from a source that says `sort_mode="asc"`. A first sync, a reset, a CDC table, a laned source, a resumable source, an attempt that continues an earlier one and a table with an active chunk sink (a warehouse-triggered workflow, a HogFunction or a person-property mapping) do not qualify. A retry clears the sink's staged files, so it would never stage the rows that it skips.
- A run with an external destination does not qualify. A file destination publishes the batches of a run only when the run completes, so a loaded warehouse prefix does not prove that the destination has the rows.
- The promoted value is safe only when the source really reads in ascending order, because the next run reads only the rows above it. The check for a batch out of order cannot protect rows that the run did not read yet. Enable the setting only where every source that says `sort_mode="asc"` proves that order.
- Each batch records in its queue metadata (`loaded_prefix_cursor`) the largest value below the newest value read so far. Rows that hold the newest value can still be in the next batch, so the next run reads them again and merges them. A batch out of ascending order stops the recording for the rest of the run.
- After each write, the loader checks that every earlier batch of the run has `succeeded` (`get_loaded_prefix_sync` in `jobs_db.py`). Then it promotes the value under the schema row lock. It never moves the watermark down, and it does nothing when the run has no staged cursor, because a reset deleted it.
- A later attempt of the same job reads only the rows above the promoted value, so it keeps the job's `rows_synced` through that prefix (`incremental_prefix_promotion`) instead of counting from zero.

## Destinations

A schema syncs to a set of destinations, of which the PostHog warehouse is one rather than a special case.
Absence of configuration resolves to the warehouse alone, so a source set up before destinations existed behaves exactly as it did.
Gated by the `warehouse-multi-destination` flag, evaluated once in `create_external_data_job_model_activity` and carried into the workflow as recorded history.

- **Configuration.** `ExternalDataDestination` is team-scoped and reusable; credentials live on a linked `Integration`, not in its config.
  Source-level links are the default set, schema-level links override them, and clearing the override restores inheritance (`models/external_data_destination.py::resolve_destinations`).
- **One job, one run.** The resolved destination ids are snapshotted onto `ExternalDataJob.destination_ids` when the run starts and travel with every batch, so a config change mid-run cannot alter where an in-flight run lands or what it bills.
- **One consumer.** There is no second deployment. `run_warehouse_sources_load` writes the batch to Delta as it always has, then `destinations_load/delivery.py` writes the same batch to every other destination in turn.
- **All destinations share one lifecycle.** A batch is done only when every destination has taken it, and a destination that fails fails the batch, which is retried in full. Each destination has its own idempotency key, so a retry skips the ones that already took the batch. The failing destination's name is prefixed onto the job's `latest_error`.
- **A run that lists destinations but not the warehouse** never touches Delta: no table registration, no post-import.
- **The cursor** is unchanged from before destinations existed. A batch is either delivered everywhere or retried, so it advances exactly as it always has.
- **Billing** multiplies the run's rows by the number of destinations it snapshotted (`billable_destination_multiplier`). Runs that predate destinations carry an empty list and bill as one.
- **Falling behind** is bounded by queue retention, not by patience: past that the staged parquet is gone and the run must be re-extracted. Alert on `oldest_eligible_age_seconds`.

Writers live in `destinations_load/writers/` and are resolved by type from a registry, so the consumer never names a destination type. Only Postgres ships today; it runs on batch exports' `PostgreSQLClient`.

CDC is excluded for now: the source setup flow does not offer destinations for CDC tables.

## The pipelines

| Pipeline                             | Lives in                                                                                                       | Attaches at                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| v3 extract (`PipelineV3`)            | `pipeline_v3/pipeline.py`, `pipeline_v3/s3/`, `pipeline_v3/postgres_queue/producer.py`                         | Step 4, under the sync lock; writes parquet batches to S3 and enqueues them (`ExportSignalMessage`, `pipeline_v3/messages.py`) on the Postgres load queue.                                                                                                                                                                                                          |
| v3 load                              | `pipeline_v3/postgres_queue/`, `pipeline_v3/load/`, engine in `products/warehouse_sources_queue/backend/core/` | Its own deployment (`run_warehouse_sources_load`), not the workflow: claims queued batches, writes Delta via `core/delta/`, finalizes the job, releases the lock, starts post-import. When the run has destinations it also hands each batch to `destinations_load/delivery.py` before finalizing.                                                                  |
| CDC                                  | `../cdc/`                                                                                                      | Capture runs outside the scheduled flow: the `cdc-extraction` Temporal workflow tails the source WAL and writes change files to the S3 change buffer (`cdc/buffer.py`). Each table's scheduled v3 sync consumes that buffer as its source (`cdc/source_manager.py`); the loader writes the consolidated table and the `_cdc` SCD2 companion (`core/delta/scd2.py`). |
| Webhooks                             | `run_webhook_s3_sink` command; sink behind the `data_warehouse` facade                                         | Buffered ingress: deliveries are buffered to S3 continuously, and the next scheduled sync drains them as ordinary source items (webhook-only schemas skip table resets, `common/extract.py`).                                                                                                                                                                       |
| Chunk sinks (CDP, person properties) | `core/sinks.py`, `core/cdp_producer.py`, `core/person_property_row_sink.py`                                    | Gated taps on the write loop, one `stage_chunk` call per chunk (see `ChunkSink`). Downstream: `dwh-cdp-producer-job` produces staged chunks to Kafka for HogFunctions/HogFlows; `sync-warehouse-person-properties` plus `run_person_property_update_consumer` upsert person properties.                                                                             |
| Post-import steps                    | `../post_import_job.py`, children under `../workflow_activities/`                                              | Step 7. Started by whoever finalizes the run (step 6); gates are resolved once in its resolve activity, then the workflow is a loop over recorded step keys.                                                                                                                                                                                                        |
| Repartition                          | `core/repartition.py`, `core/repartition_controller.py`, `../workflow_activities/repartition_table.py`         | Detection is a `POST_LOAD_STEPS` entry (flags oversized partitions); execution is `maybe_repartition_table_activity`, pre-extraction on the next run while the lock is held.                                                                                                                                                                                        |

## The shared kernel

- `core/` - the pipeline kernel: `batcher.py`, `arrow_utils.py`, `partitioning.py`, `hogql_schema.py`, `sinks.py`, the repartitioner, and `typings.py` (`PipelineResult`).
- `core/delta/` - everything Delta Lake, one concern per module: `table.py` (`DeltaTableRef`, the single stateful handle threaded through a run), `writer.py`, `scd2.py`, `maintenance.py`, `evolution.py`, `ops.py`, `errors.py`.
  The write/maintenance classes are stateless wrappers constructed at their call sites over a `DeltaTableRef`.
- `common/` - the sync-flow helpers: `extract.py` (reset/corruption handling, incremental bookkeeping) and `load.py` (`run_post_load_operations`).
- `pipeline_sync.py`, `helpers.py` - table registration and naming.

Dependency rule: `pipeline_v3/` imports from `core/` and `common/`; `core/` imports from no pipeline.
One remaining exception: several `core/` modules still import the shared write metrics from `pipeline_v3/load/metrics.py`.
Cross-product coupling goes through `../external_product_hooks.py` (registration) rather than direct imports.
