//! Consume → filter → re-key → produce loop for `clickhouse_events_json`.
//!
//! Drops events with no `person_id`, skips teams with no realtime cohorts, then re-keys the
//! survivors by `(team_id, person_id)` to match the Node CDP precalculated-filters gating.

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

/// A distinct variant per outcome so the consumer can emit a per-reason metric; `Forward` carries
/// the moved-out `person_id` so the forward path needs no clone.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ForwardDecision {
    Forward { person_id: String },
    DropNoPersonId,
    SkipTeamGate,
}

/// `&mut` so `person_id` can be moved out (no clone) when both gates pass; the caller discards any
/// non-forwarded event, so the `take()` before the team check is unobservable. `person_id` is
/// checked first because a missing routing key disqualifies the event regardless of the team gate.
pub fn classify(event: &mut ClickHouseEvent, team_index: &TeamIndex) -> ForwardDecision {
    let Some(person_id) = event.person_id.take() else {
        return ForwardDecision::DropNoPersonId;
    };
    if !team_index.contains(event.team_id) {
        return ForwardDecision::SkipTeamGate;
    }
    ForwardDecision::Forward { person_id }
}

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

    /// A successful batch (even an empty poll) heartbeats liveness, so an idle topic stays healthy
    /// and only a wedged loop or a persistent produce failure trips the stall detector.
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

    async fn process_batch(&self) -> Result<usize> {
        // Fail-closed until the team index loads once: don't consume — and advance offsets past —
        // events while the gate would forward nothing.
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
                    // Poison pills are already offset-stored by the consumer; just log.
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

        // At-least-once: produce and await acks BEFORE storing source offsets, and bail without
        // committing on any produce failure. `recv()` has already advanced the fetch position past
        // the failed offsets, so the bailed batch is only replayed on a restart (triggered by a
        // failure persistent enough to trip the liveness stall) — a transient failure that recovers
        // gets committed over by a later batch, dropping those events. Accepted codebase-wide
        // tradeoff; the downstream processor dedups replays via source_offset/source_partition.
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
            (
                "no person precedence",
                None,
                99,
                vec![2],
                ForwardDecision::DropNoPersonId,
            ),
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
        let index = TeamIndex::new();
        let mut event = sample_clickhouse_event(2, Some("p"));
        assert_eq!(classify(&mut event, &index), ForwardDecision::SkipTeamGate);
    }
}
