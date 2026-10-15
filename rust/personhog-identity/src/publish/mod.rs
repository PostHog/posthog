//! The publish phase. The outbox carries two row shapes: a mapping row
//! (kinds `create` and `attach`) that publishes as it is, and an op pointer
//! (kinds `merge_op` and `delete_op`) that resolves against the saga's
//! `moved` records. Identity enqueues pointers in
//! [`crate::lifecycle::engine::complete_op_in_tx`] and mapping rows from the
//! stub-create and attach paths; this module drains the outbox to Kafka from
//! the separate `personhog-publisher` binary.
//!
//! One pass is one transaction: claim the oldest pending rows with `FOR
//! UPDATE SKIP LOCKED`, resolve pointers against `moved` within a per-pass
//! row budget, produce, await every ack, then delete finished rows, advance
//! unfinished pointers, defer rows that cannot be read, and commit. A merge
//! pointer's final chunk also carries that merge's `person_merge_events`,
//! one per merged source person, so they go out in the pass that deletes
//! the pointer and never once per chunk. A produce error rolls the whole
//! pass back, so the only failure mode is a repeat publish, which every
//! consumer of these topics absorbs.
//! A row the publisher cannot read (an op row that is gone, a `moved` entry
//! the saga could not have written, an outcome that disagrees with the rows)
//! stays pending with `last_error` and a raised `attempts`: the rest of its
//! batch publishes, the row is retried on every pass and publishes on its
//! own once the state is repaired, and the lag gauge reports it meanwhile.
//! The publisher never parks a row; `given_up_at` is an operator's switch
//! to take a row out of the claim. Kafka failures retry forever with backoff.

pub mod claim;
pub mod config;
pub mod messages;
pub mod pointer;
pub mod sink;

use std::collections::BTreeSet;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use common_sqlx_macros::mirrored_query;
use lifecycle::Handle;
use sqlx::PgPool;
use uuid::Uuid;

use crate::config::IdentityTables;
use crate::lifecycle::engine::Tx;
use crate::lifecycle::merge::{MergeSourceRecord, OUTCOME_MERGED};
use crate::publish::claim::{claim, ClaimedRow, KIND_MERGE_OP};
use crate::publish::config::MergeEventsAllowlist;
use crate::publish::messages::{DistinctIdRow, PersonMergeEvent, MERGE_EVENT_SCHEMA_VERSION};
use crate::publish::pointer::{
    load_op, load_outcome_results, merged_sources, outbox_depth, resolve_chunk, Cursor, PointerOp,
};
use crate::publish::sink::{PublishBatch, PublishError, PublishSink};

const PUBLISH_ROWS_TOTAL: &str = "personhog_lifecycle_publish_rows_total";
const PUBLISH_FAILURES_TOTAL: &str = "personhog_lifecycle_publish_failures_total";
const PUBLISH_BATCH_DURATION_MS: &str = "personhog_lifecycle_publish_batch_duration_ms";
const PUBLISH_BACKLOG: &str = "personhog_lifecycle_publish_backlog";
const PUBLISH_LAG_SECONDS: &str = "personhog_lifecycle_publish_lag_seconds";
/// Rows an operator parked with `given_up_at`; the publisher never sets it.
const PUBLISH_GIVEN_UP: &str = "personhog_lifecycle_publish_given_up";

/// The gauges read the whole outbox, so they refresh on their own clock
/// rather than once per pass.
const GAUGE_REFRESH_INTERVAL: Duration = Duration::from_secs(5);
const MAX_BACKOFF: Duration = Duration::from_secs(30);

#[derive(Clone, Debug)]
pub struct DrainConfig {
    pub batch_size: i64,
    /// Messages one pass produces at most, distinct id rows and merge
    /// events together. A pointer's chunk is bounded by what is left of it,
    /// so a pass of large ops stays inside the produce timeout instead of
    /// failing the same way forever. A merge's events ride its final chunk
    /// whole, so one pointer can overshoot by its source count, which the
    /// merge request cap bounds.
    pub max_rows_per_pass: i64,
    pub interval: Duration,
    pub lag_alert: Duration,
    pub merge_events: Option<MergeEventsAllowlist>,
}

#[derive(Debug, thiserror::Error)]
pub enum DrainError {
    #[error("database error: {0}")]
    Db(#[from] sqlx::Error),
    #[error(transparent)]
    Publish(#[from] PublishError),
}

impl DrainError {
    fn reason(&self) -> &'static str {
        match self {
            DrainError::Db(_) => "db",
            DrainError::Publish(PublishError::Kafka(_)) => "kafka",
            DrainError::Publish(PublishError::Timeout(_)) => "kafka_timeout",
        }
    }
}

/// What one pass did. More work is waiting when the claim was full or the
/// row budget stopped the pass before every claimed row was handled.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct PassReport {
    pub claimed: usize,
    pub finished: usize,
    pub advanced: usize,
    pub deferred: usize,
    /// Claimed rows left untouched because the row budget ran out; they
    /// stay pending with their cursors for the next pass.
    pub unprocessed: usize,
    pub messages: usize,
}

enum Disposition {
    /// Published in full: the row is deleted.
    Finished,
    /// A pointer with rows left after this chunk: the cursor moves.
    Advanced(Cursor),
    /// State the saga could not have written: the row stays pending with
    /// the reason and is retried on every pass, so it publishes on its own
    /// once repaired and an operator can see why until then.
    Deferred(String),
}

pub struct Publisher<S> {
    pool: PgPool,
    tables: IdentityTables,
    sink: S,
    config: DrainConfig,
}

impl<S: PublishSink> Publisher<S> {
    pub fn new(pool: PgPool, tables: IdentityTables, sink: S, config: DrainConfig) -> Self {
        tables.validate().expect("invalid identity table set");
        assert!(config.batch_size > 0, "batch_size must be > 0");
        assert!(
            config.max_rows_per_pass > 0,
            "max_rows_per_pass must be > 0"
        );
        Self {
            pool,
            tables,
            sink,
            config,
        }
    }

    /// The drain loop, until `handle` shuts down. An in-flight pass runs
    /// to its end first: it is bounded by the produce timeout, the
    /// statement timeout and the row budget, and tearing it down
    /// mid-transaction would only trade a clean rollback for an abandoned
    /// connection.
    pub async fn run(&self, handle: &Handle) {
        let mut delay = Duration::ZERO;
        let mut backoff = self.config.interval;
        let mut gauges_refreshed_at: Option<Instant> = None;
        loop {
            // Biased, so a shutdown that arrives during a backlog (delay
            // zero, both branches ready) wins over starting another pass.
            tokio::select! {
                biased;
                _ = handle.shutdown_recv() => break,
                _ = tokio::time::sleep(delay) => {}
            }
            if gauges_refreshed_at.is_none_or(|at| at.elapsed() >= GAUGE_REFRESH_INTERVAL) {
                self.refresh_gauges().await;
                gauges_refreshed_at = Some(Instant::now());
            }
            match self.drain_once().await {
                Ok(report) => {
                    if report.claimed > 0 {
                        tracing::debug!(
                            claimed = report.claimed,
                            finished = report.finished,
                            advanced = report.advanced,
                            deferred = report.deferred,
                            unprocessed = report.unprocessed,
                            messages = report.messages,
                            "publish pass"
                        );
                    }
                    backoff = self.config.interval;
                    let more_waiting =
                        report.claimed as i64 >= self.config.batch_size || report.unprocessed > 0;
                    delay = if more_waiting {
                        Duration::ZERO
                    } else {
                        self.config.interval
                    };
                }
                Err(err) => {
                    common_metrics::inc(
                        PUBLISH_FAILURES_TOTAL,
                        &[("reason".to_string(), err.reason().to_string())],
                        1,
                    );
                    tracing::warn!(
                        error = %err,
                        backoff_ms = backoff.as_millis() as u64,
                        "publish pass failed; its rows stay claimed by nobody until the retry"
                    );
                    delay = backoff;
                    backoff = (backoff * 2).min(MAX_BACKOFF);
                }
            }
        }
    }

    /// One claim transaction. Nothing is awaited inside it except the
    /// outbox statements and the sink.
    pub async fn drain_once(&self) -> Result<PassReport, DrainError> {
        let start = Instant::now();
        let mut tx = self.pool.begin().await?;
        let rows = claim(&mut tx, &self.tables, self.config.batch_size).await?;
        if rows.is_empty() {
            tx.rollback().await?;
            return Ok(PassReport::default());
        }

        let mut batch = PublishBatch::default();
        let mut dispositions: Vec<(&ClaimedRow, Disposition)> = Vec::with_capacity(rows.len());
        let mut remaining = self.config.max_rows_per_pass;
        for row in &rows {
            if remaining <= 0 {
                break;
            }
            let before = batch.distinct_id_rows.len() + batch.merge_events.len();
            let disposition = if row.is_pointer() {
                self.resolve_pointer(&mut tx, row, &mut batch, remaining)
                    .await
                    .inspect_err(|e| {
                        // The failing row is the head of the queue until it
                        // is repaired, so name it.
                        tracing::warn!(
                            outbox_id = row.id,
                            op_id = ?row.op_id,
                            error = %e,
                            "resolving a publish pointer failed; the pass rolls back"
                        );
                    })?
            } else {
                batch.distinct_id_rows.push(mapping_row(row)?);
                Disposition::Finished
            };
            remaining -= (batch.distinct_id_rows.len() + batch.merge_events.len() - before) as i64;
            dispositions.push((row, disposition));
        }
        let unprocessed = rows.len() - dispositions.len();

        // A failure here drops `tx`, which rolls the claim back: every row
        // stays pending with its cursor untouched.
        self.sink.send(&batch).await?;

        let mut finished: Vec<i64> = Vec::new();
        let mut advanced: (Vec<i64>, Vec<i64>, Vec<i64>) = Default::default();
        let mut deferred: (Vec<i64>, Vec<String>) = Default::default();
        for (row, disposition) in &dispositions {
            match disposition {
                Disposition::Finished => finished.push(row.id),
                Disposition::Advanced(cursor) => {
                    advanced.0.push(row.id);
                    advanced.1.push(cursor.person_id);
                    advanced.2.push(cursor.mapping_ordinal);
                }
                Disposition::Deferred(reason) => {
                    // The row is claimed on every pass, so log the first
                    // deferral and then every 300th.
                    if row.attempts % 300 == 0 {
                        tracing::error!(
                            outbox_id = row.id,
                            kind = %row.kind,
                            op_id = ?row.op_id,
                            attempts = row.attempts + 1,
                            reason = %reason,
                            "publish outbox row cannot be read; it stays pending until the state is repaired"
                        );
                    }
                    deferred.0.push(row.id);
                    deferred.1.push(reason.clone());
                }
            }
        }
        self.write_back(&mut tx, &finished, &advanced, &deferred)
            .await?;
        tx.commit().await?;

        // Counted after the commit, so a pass that rolls back counts nothing.
        for (row, disposition) in &dispositions {
            let result = match disposition {
                Disposition::Finished => "published",
                Disposition::Deferred(_) => "deferred",
                Disposition::Advanced(_) => continue,
            };
            record_row(&row.kind, result);
        }
        common_metrics::histogram(
            PUBLISH_BATCH_DURATION_MS,
            &[],
            start.elapsed().as_secs_f64() * 1000.0,
        );
        Ok(PassReport {
            claimed: rows.len(),
            finished: finished.len(),
            advanced: advanced.0.len(),
            deferred: deferred.0.len(),
            unprocessed,
            messages: batch.distinct_id_rows.len() + batch.merge_events.len(),
        })
    }

    /// Resolve one pointer's next chunk, at most `limit` rows, into
    /// `batch`, plus the merge events on a merge pointer's final chunk.
    /// Rows and events are added only once the chunk decodes and the events
    /// resolve, so a deferred pointer contributes nothing to the batch.
    async fn resolve_pointer(
        &self,
        tx: &mut Tx<'_>,
        row: &ClaimedRow,
        batch: &mut PublishBatch,
        limit: i64,
    ) -> Result<Disposition, sqlx::Error> {
        let op_id = row.op_id.expect("pointer rows carry an op_id");
        let Some(op) = load_op(tx, &self.tables, op_id).await? else {
            return Ok(Disposition::Deferred(format!(
                "op {op_id} no longer exists; its moved rows cannot be published"
            )));
        };
        // Pointers are written only by a completed op's own commit, so any
        // of these is corrupt state rather than a case to handle.
        let Some(completed_at) = op.completed_at else {
            return Ok(Disposition::Deferred(format!(
                "op {op_id} is not completed"
            )));
        };
        if format!("{}_op", op.op_type) != row.kind {
            return Ok(Disposition::Deferred(format!(
                "op {op_id} is a {} op but the pointer kind is {}",
                op.op_type, row.kind
            )));
        }
        if op.op_type == "merge" && op.target_rows != 1 {
            return Ok(Disposition::Deferred(format!(
                "merge op {op_id} has {} target rows",
                op.target_rows
            )));
        }
        if op.malformed_moved_rows > 0 {
            return Ok(Disposition::Deferred(format!(
                "op {op_id} has {} source or victim rows whose moved is not an array",
                op.malformed_moved_rows
            )));
        }
        let cursor = Cursor {
            person_id: row.cursor_person_id,
            mapping_ordinal: row.cursor_mapping_ordinal,
        };
        let chunk = resolve_chunk(tx, &self.tables, op_id, cursor, limit).await?;

        let mut rows = Vec::with_capacity(chunk.len());
        for resolved in &chunk {
            let (Some(owner), Some(distinct_id), Some(version)) = (
                resolved.owner_uuid,
                resolved.distinct_id.as_ref(),
                resolved.version,
            ) else {
                return Ok(Disposition::Deferred(format!(
                    "op {op_id} person {} moved entry {} is malformed (owner {:?}, distinct_id {:?}, version {:?})",
                    resolved.person_id,
                    resolved.mapping_ordinal,
                    resolved.owner_uuid,
                    resolved.distinct_id,
                    resolved.version
                )));
            };
            rows.push(DistinctIdRow {
                person_id: owner,
                team_id: row.team_id as i64,
                distinct_id: distinct_id.clone(),
                version,
                is_deleted: u8::from(resolved.is_deleted),
            });
        }

        // A chunk shorter than the limit it was asked for is the last one.
        // A chunk exactly at the limit may also be the last, which costs
        // one more pass that finds nothing; cheaper than probing past the
        // limit on every chunk.
        let disposition = match chunk.last() {
            Some(last) if chunk.len() as i64 >= limit => Disposition::Advanced(last.cursor()),
            _ => Disposition::Finished,
        };

        let mut merge_events = Vec::new();
        if matches!(disposition, Disposition::Finished) && row.kind == KIND_MERGE_OP {
            if let Some(allowlist) = &self.config.merge_events {
                if allowlist.allows(i64::from(row.team_id)) {
                    match self
                        .merge_events_for(tx, op_id, &op, row.team_id, completed_at)
                        .await?
                    {
                        Ok(events) => merge_events = events,
                        Err(reason) => return Ok(Disposition::Deferred(reason)),
                    }
                }
            }
        }

        batch.distinct_id_rows.extend(rows);
        batch.merge_events.extend(merge_events);
        Ok(disposition)
    }

    /// One `person_merge_events` message per source person the merge
    /// deleted, with `merged_at_ms` the op's completion time. The source
    /// rows and the recorded outcome have to name the same persons;
    /// anything else is corrupt state, reported as the deferral reason.
    async fn merge_events_for(
        &self,
        tx: &mut Tx<'_>,
        op_id: Uuid,
        op: &PointerOp,
        team_id: i32,
        completed_at: DateTime<Utc>,
    ) -> Result<Result<Vec<PersonMergeEvent>, String>, sqlx::Error> {
        let Some(new_person_uuid) = op.target_uuid else {
            return Ok(Err(format!("merge op {op_id} has no target row")));
        };
        let Some(results) = load_outcome_results(tx, &self.tables, op_id).await? else {
            return Ok(Err(format!(
                "merge op {op_id} has no recorded outcome results"
            )));
        };
        let results: Vec<MergeSourceRecord> = match serde_json::from_value(results) {
            Ok(results) => results,
            Err(e) => {
                return Ok(Err(format!(
                    "merge op {op_id} has malformed outcome results: {e}"
                )))
            }
        };
        let mut recorded: BTreeSet<i64> = BTreeSet::new();
        for result in results.iter().filter(|r| r.outcome == OUTCOME_MERGED) {
            let Some(person_id) = result.person_id else {
                return Ok(Err(format!(
                    "merge op {op_id} recorded a merged source without a person id"
                )));
            };
            recorded.insert(person_id);
        }
        let sources = merged_sources(tx, &self.tables, op_id).await?;
        let deleted: BTreeSet<i64> = sources.iter().map(|s| s.person_id).collect();
        if recorded != deleted {
            return Ok(Err(format!(
                "merge op {op_id} recorded merged sources {recorded:?} but its deleted source rows are {deleted:?}"
            )));
        }
        let merged_at_ms = completed_at.timestamp_millis();
        Ok(Ok(sources
            .into_iter()
            .map(|source| PersonMergeEvent {
                team_id,
                old_person_uuid: source.person_uuid,
                new_person_uuid,
                merged_at_ms,
                schema_version: MERGE_EVENT_SCHEMA_VERSION,
            })
            .collect()))
    }

    async fn write_back(
        &self,
        tx: &mut Tx<'_>,
        finished: &[i64],
        advanced: &(Vec<i64>, Vec<i64>, Vec<i64>),
        deferred: &(Vec<i64>, Vec<String>),
    ) -> Result<(), sqlx::Error> {
        if !finished.is_empty() {
            mirrored_query!(
                self.tables.is_validation(),
                op = "publish_delete_finished",
                "DELETE FROM {person_publish_outbox} WHERE id = ANY($1)",
                finished
                => execute(&mut **tx)
            )?;
        }
        if !advanced.0.is_empty() {
            mirrored_query!(
                self.tables.is_validation(),
                op = "publish_advance_cursors",
                r#"
                UPDATE {person_publish_outbox} o
                SET cursor_person_id = u.person_id,
                    cursor_mapping_ordinal = u.mapping_ordinal,
                    attempts = o.attempts + 1,
                    last_error = NULL
                FROM unnest($1::bigint[], $2::bigint[], $3::bigint[]) AS u(id, person_id, mapping_ordinal)
                WHERE o.id = u.id
                "#,
                &advanced.0,
                &advanced.1,
                &advanced.2
                => execute(&mut **tx)
            )?;
        }
        if !deferred.0.is_empty() {
            mirrored_query!(
                self.tables.is_validation(),
                op = "publish_defer",
                r#"
                UPDATE {person_publish_outbox} o
                SET last_error = u.last_error, attempts = o.attempts + 1
                FROM unnest($1::bigint[], $2::text[]) AS u(id, last_error)
                WHERE o.id = u.id
                "#,
                &deferred.0,
                &deferred.1
                => execute(&mut **tx)
            )?;
        }
        Ok(())
    }

    async fn refresh_gauges(&self) {
        match outbox_depth(&self.pool, &self.tables).await {
            Ok(depth) => {
                common_metrics::gauge(PUBLISH_BACKLOG, &[], depth.pending as f64);
                common_metrics::gauge(PUBLISH_GIVEN_UP, &[], depth.given_up as f64);
                common_metrics::gauge(PUBLISH_LAG_SECONDS, &[], depth.lag_seconds);
                if depth.lag_seconds > self.config.lag_alert.as_secs_f64() {
                    tracing::warn!(
                        lag_seconds = depth.lag_seconds,
                        backlog = depth.pending,
                        "publish lag is above the alert threshold"
                    );
                }
            }
            Err(e) => tracing::warn!(error = %e, "failed to refresh the publish outbox gauges"),
        }
    }
}

/// A create or attach row carries its message inline. The CHECK constraint
/// makes the three columns non-null for these kinds, so a null is a schema
/// change the code has not followed.
fn mapping_row(row: &ClaimedRow) -> Result<DistinctIdRow, sqlx::Error> {
    let (Some(person_uuid), Some(distinct_id), Some(version)) =
        (row.person_uuid, row.distinct_id.as_ref(), row.version)
    else {
        return Err(sqlx::Error::Decode(
            format!(
                "outbox row {} of kind {} lacks a mapping column",
                row.id, row.kind
            )
            .into(),
        ));
    };
    Ok(DistinctIdRow {
        person_id: person_uuid,
        team_id: row.team_id as i64,
        distinct_id: distinct_id.clone(),
        version,
        is_deleted: 0,
    })
}

fn record_row(kind: &str, result: &str) {
    common_metrics::inc(
        PUBLISH_ROWS_TOTAL,
        &[
            ("kind".to_string(), kind.to_string()),
            ("result".to_string(), result.to_string()),
        ],
        1,
    );
}
