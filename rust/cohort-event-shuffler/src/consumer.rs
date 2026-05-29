//! Consume → filter → re-key → produce loop for `clickhouse_events_json` (TDD §2.2).
//!
//! Mirrors the gating in `cdp-precalculated-filters.consumer.ts` (drop events with no
//! `person_id`, `:187-194`) and `realtime-supported-filter-manager-cdp.ts` (skip teams with no
//! realtime cohorts, `:219-222`), then re-keys the survivors by `(team_id, person_id)`.

use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use common_kafka::kafka_consumer::{RecvErr, SingleTopicConsumer};
use common_types::ClickHouseEvent;
use lifecycle::Handle;
use metrics::counter;
use tracing::{debug, error, info, warn};

use crate::event::CohortStreamEvent;
use crate::filter_team_index::TeamIndex;
use crate::observability::metrics::{
    EVENTS_CONSUMED, EVENTS_DROPPED_NO_PERSON_ID, EVENTS_FORWARDED, EVENTS_SKIPPED_TEAM_GATE,
    PRODUCE_ERRORS,
};
use crate::producer::CohortStreamProducer;

/// Outcome of the per-event gate (TDD §2.2, steps 2–3). An explicit enum — rather than a bool —
/// so the consumer can emit a distinct metric per drop reason. `Forward` carries the extracted
/// `person_id` so the forward path needs neither a clone nor a second `Option` check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ForwardDecision {
    /// Forward: the event has a `person_id` (carried here) and its team has ≥1 realtime cohort.
    Forward { person_id: String },
    /// Drop: no `person_id` — the re-key has no routing key (`consumer.ts:187-194`).
    DropNoPersonId,
    /// Skip: the team has no realtime cohorts (`realtime-supported-filter-manager-cdp.ts:219-222`).
    SkipTeamGate,
}

/// Classify an event against the gate, extracting the routing key on the forward path. Takes
/// `&mut` so the `person_id` can be *moved* out of the event into [`ForwardDecision::Forward`]
/// (no clone) when both gates pass. The `take()` runs before the team check, but a non-forwarded
/// event is discarded by the caller, so the mutation is unobservable. Depends only on the event
/// and the team snapshot, so it stays exhaustively unit-testable without Kafka or Postgres.
/// `person_id` is checked first because a missing routing key disqualifies the event regardless
/// of the team gate.
pub fn classify(event: &mut ClickHouseEvent, team_index: &TeamIndex) -> ForwardDecision {
    let Some(person_id) = event.person_id.take() else {
        return ForwardDecision::DropNoPersonId;
    };
    if !team_index.contains(event.team_id) {
        return ForwardDecision::SkipTeamGate;
    }
    ForwardDecision::Forward { person_id }
}

/// The stateless consume → filter → re-key → produce worker.
pub struct EventShuffler {
    consumer: SingleTopicConsumer,
    producer: CohortStreamProducer,
    team_index: Arc<TeamIndex>,
    handle: Handle,
    batch_size: usize,
    batch_timeout: Duration,
}

impl EventShuffler {
    pub fn new(
        consumer: SingleTopicConsumer,
        producer: CohortStreamProducer,
        team_index: Arc<TeamIndex>,
        handle: Handle,
        batch_size: usize,
        batch_timeout: Duration,
    ) -> Self {
        Self {
            consumer,
            producer,
            team_index,
            handle,
            batch_size,
            batch_timeout,
        }
    }

    /// Run until the lifecycle handle signals shutdown. A successful batch (even an empty poll)
    /// heartbeats liveness, so an idle topic stays healthy and only a wedged loop or a
    /// persistent produce failure trips the stall detector.
    pub async fn process(self) {
        let _guard = self.handle.process_scope();
        info!("shuffler consume loop starting");

        loop {
            tokio::select! {
                _ = self.handle.shutdown_recv() => {
                    info!("shutdown signal received, stopping consume loop");
                    break;
                }
                result = self.process_batch() => match result {
                    Ok(_) => self.handle.report_healthy(),
                    Err(err) => {
                        error!(error = %err, "batch processing failed; backing off");
                        tokio::time::sleep(Duration::from_secs(1)).await;
                    }
                },
            }
        }

        info!("shuffler consume loop stopped");
    }

    /// One consume → filter → produce → commit cycle. Returns the number of events consumed.
    async fn process_batch(&self) -> Result<usize> {
        // Fail-closed until the team index loads once (key design point 4): don't consume — and
        // advance offsets past — events while the gate would forward nothing.
        if !self.team_index.is_loaded() {
            tokio::time::sleep(Duration::from_millis(200)).await;
            return Ok(0);
        }

        let results = self
            .consumer
            .json_recv_batch::<ClickHouseEvent>(self.batch_size, self.batch_timeout)
            .await;
        if results.is_empty() {
            return Ok(0);
        }

        let mut consumed = 0u64;
        let mut dropped = 0u64;
        let mut skipped = 0u64;
        let mut forwardable = Vec::new();
        let mut offsets = Vec::with_capacity(results.len());

        for result in results {
            let (mut event, offset) = match result {
                Ok(pair) => pair,
                Err(err) => {
                    // Poison pills (empty/undeserializable) are auto-stored by the consumer.
                    log_recv_error(&err);
                    continue;
                }
            };

            consumed += 1;
            let source_partition = offset.partition();
            let source_offset = offset.get_value();

            match classify(&mut event, &self.team_index) {
                ForwardDecision::Forward { person_id } => {
                    forwardable.push(CohortStreamEvent::from_clickhouse(
                        event,
                        person_id,
                        source_partition,
                        source_offset,
                    ))
                }
                ForwardDecision::DropNoPersonId => dropped += 1,
                ForwardDecision::SkipTeamGate => skipped += 1,
            }

            offsets.push(offset);
        }

        counter!(EVENTS_CONSUMED).increment(consumed);
        if dropped > 0 {
            counter!(EVENTS_DROPPED_NO_PERSON_ID).increment(dropped);
        }
        if skipped > 0 {
            counter!(EVENTS_SKIPPED_TEAM_GATE).increment(skipped);
        }

        // At-least-once ordering (key design point 2): produce and await acks BEFORE storing the
        // source offsets. On a produce failure we record it and bail without committing this
        // batch; `process()` then logs, backs off, and continues. Because `recv()` has already
        // advanced the fetch position past the failed offsets, the bailed batch is NOT redelivered
        // in-process — only a failure persistent enough to trip the liveness stall (deadline 60s ×
        // stall_threshold 3 ≈ 180s of consecutive failing batches, main.rs:51-57) forces the
        // restart that replays from the last committed offset. A transient failure that recovers
        // sooner can be committed over by a later successful batch, so those events are not
        // re-forwarded. This is the accepted codebase-wide at-least-once tradeoff (mirrors
        // ingestion-consumer); downstream Stage 1 dedups any replayed duplicates via per-key
        // offset tracking (PR 1.5), keyed on source_offset/source_partition.
        let forward_count = forwardable.len();
        if forward_count > 0 {
            let produce_results = self.producer.forward(forwardable).await;
            let errors = produce_results.iter().filter(|r| r.is_err()).count();
            if errors > 0 {
                counter!(PRODUCE_ERRORS).increment(errors as u64);
                let first_error = produce_results
                    .iter()
                    .find_map(|r| r.as_ref().err())
                    .map(ToString::to_string)
                    .unwrap_or_default();
                anyhow::bail!(
                    "{errors}/{forward_count} produces to cohort_stream_events failed: {first_error}"
                );
            }
            counter!(EVENTS_FORWARDED).increment(forward_count as u64);
        }

        for offset in offsets {
            if let Err(err) = offset.store() {
                warn!(error = %err, "failed to store consumer offset");
            }
        }
        self.consumer
            .commit()
            .context("committing consumer offsets after forwarding batch")?;

        Ok(consumed as usize)
    }
}

fn log_recv_error(err: &RecvErr) {
    match err {
        RecvErr::Empty => debug!("skipped message with empty payload"),
        RecvErr::Serde(e) => debug!(error = %e, "skipped undeserializable event"),
        RecvErr::Kafka(e) => warn!(error = %e, "kafka recv error during batch"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::sample_clickhouse_event;

    fn index_with(teams: &[i32]) -> TeamIndex {
        TeamIndex::from_teams(teams.iter().copied())
    }

    #[test]
    fn classify_covers_every_gate_outcome() {
        let cases = [
            (
                "forward",
                Some("p"),
                2,
                vec![2],
                ForwardDecision::Forward {
                    person_id: "p".to_string(),
                },
            ),
            (
                "no person",
                None,
                2,
                vec![2],
                ForwardDecision::DropNoPersonId,
            ),
            (
                "team gate",
                Some("p"),
                99,
                vec![2],
                ForwardDecision::SkipTeamGate,
            ),
            // A missing person_id disqualifies the event even when the team is gated.
            (
                "no person precedence",
                None,
                99,
                vec![2],
                ForwardDecision::DropNoPersonId,
            ),
            // An empty (but loaded) index forwards nothing.
            (
                "empty index",
                Some("p"),
                2,
                vec![],
                ForwardDecision::SkipTeamGate,
            ),
        ];

        for (name, person_id, team_id, teams, expected) in cases {
            let mut event = sample_clickhouse_event(team_id, person_id);
            let index = index_with(&teams);
            assert_eq!(classify(&mut event, &index), expected, "case: {name}");
        }
    }

    #[test]
    fn unloaded_index_forwards_nothing() {
        // Before the first refresh the index is empty, so the gate skips everything.
        let index = TeamIndex::new();
        let mut event = sample_clickhouse_event(2, Some("p"));
        assert_eq!(classify(&mut event, &index), ForwardDecision::SkipTeamGate);
    }
}
