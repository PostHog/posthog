//! Consume → filter → re-key → produce loop for `clickhouse_events_json`.
//!
//! Drops events with no `person_id`, skips teams with no realtime cohorts, then re-keys the
//! survivors by `(team_id, person_id)` to match the Node CDP precalculated-filters gating.

use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use common_types::ClickHouseEvent;
use lifecycle::Handle;
use metrics::counter;
use serde::{de::IgnoredAny, Deserialize};
use tracing::{debug, error, info, warn};

use crate::event::CohortStreamEvent;
use crate::filter_team_index::TeamIndex;
use crate::observability::metrics::{
    EVENTS_CONSUMED, EVENTS_DROPPED_NO_PERSON_ID, EVENTS_FORWARDED, EVENTS_SKIPPED_TEAM_GATE,
    PRODUCE_ERRORS,
};
use crate::producer::CohortStreamProducer;

/// Phase-1 gate target: the minimum the team gate needs. Every other field — including the big
/// `properties` / `person_properties` / `groupN_properties` JSON-string blobs — is undeclared, so
/// `serde_json` routes its value through the ignore path (scan to the end of the value, no unescape,
/// no per-field `String` allocation). Choosing this leaner target type is the whole optimization:
/// ~99% of the firehose is dropped at the gate and never pays the blob `parse_str` cost.
#[derive(Deserialize)]
struct GateFields {
    team_id: i32,
    /// Presence only. `Option<IgnoredAny>` reports `Some`/`None` without allocating the string,
    /// which is all the gate needs to keep `DropNoPersonId`-before-`SkipTeamGate` precedence; the
    /// value itself is re-read on the survivor path. Mirrors `ClickHouseEvent::person_id` presence
    /// semantics: absent and `null` → `None`, any present non-null value → `Some`.
    #[serde(default)]
    person_id: Option<IgnoredAny>,
}

/// Gate decision over the cheap phase-1 parse. `person_id` is checked before the team gate so a
/// missing routing key disqualifies the event regardless of team membership, preserving the current
/// `shuffler_events_*` counter attribution.
#[derive(Debug, PartialEq, Eq)]
enum GateOutcome {
    Forward,
    DropNoPersonId,
    SkipTeamGate,
}

fn classify_gate(gate: &GateFields, team_index: &TeamIndex) -> GateOutcome {
    if gate.person_id.is_none() {
        return GateOutcome::DropNoPersonId;
    }
    if !team_index.contains(gate.team_id) {
        return GateOutcome::SkipTeamGate;
    }
    GateOutcome::Forward
}

/// Output of the per-message decode closure. `Forward` carries the fully-parsed survivor and its
/// moved-out `person_id`; the source coordinates are stitched in afterward from the `Offset`, which
/// is not visible inside the closure.
///
/// `event` is boxed because it is by far the largest variant payload (~544 bytes) yet is built for
/// only the ~1% of events that pass the gate. Boxing keeps every entry of the batch `Vec` small, so
/// the ~99% drop/skip majority is cheap to move and scan; the cost is one transient allocation per
/// survivor, negligible against the full parse and produce that survivor already pays for.
#[derive(Debug)]
enum Decoded {
    Forward {
        event: Box<ClickHouseEvent>,
        person_id: String,
    },
    DropNoPersonId,
    SkipTeamGate,
}

/// Two-phase decode: a cheap gate parse for every event, then a full `ClickHouseEvent` parse only
/// for the ~1% that pass the gate, reusing the same payload bytes so the forwarded envelope stays
/// byte-identical to a single full-parse path. The error type matches
/// [`SingleTopicConsumer::recv_with`]'s decode contract, so a survivor that fails the full parse is
/// auto-stored and skipped exactly as a poison pill is today.
fn decode_gated(payload: &[u8], team_index: &TeamIndex) -> Result<Decoded, serde_json::Error> {
    let gate: GateFields = serde_json::from_slice(payload)?;
    match classify_gate(&gate, team_index) {
        GateOutcome::DropNoPersonId => Ok(Decoded::DropNoPersonId),
        GateOutcome::SkipTeamGate => Ok(Decoded::SkipTeamGate),
        GateOutcome::Forward => {
            let mut event: ClickHouseEvent = serde_json::from_slice(payload)?;
            let Some(person_id) = event.person_id.take() else {
                // Unreachable: the gate confirmed a present, non-null person_id, and a non-string
                // person_id would have failed the full parse above. Fail safe rather than panic on
                // the firehose hot path.
                warn!("gate-forwarded event had no person_id after full parse; dropping");
                return Ok(Decoded::DropNoPersonId);
            };
            Ok(Decoded::Forward {
                event: Box::new(event),
                person_id,
            })
        }
    }
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

        let results = self.recv_gated_batch().await;
        if results.is_empty() {
            return Ok(0);
        }

        let mut consumed = 0u64;
        let mut dropped = 0u64;
        let mut skipped = 0u64;
        let mut forwardable = Vec::new();
        let mut offsets = Vec::with_capacity(results.len());

        for result in results {
            let (decoded, offset) = match result {
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

            match decoded {
                Decoded::Forward { event, person_id } => {
                    forwardable.push(CohortStreamEvent::from_clickhouse(
                        *event,
                        person_id,
                        source_partition,
                        source_offset,
                    ))
                }
                Decoded::DropNoPersonId => dropped += 1,
                Decoded::SkipTeamGate => skipped += 1,
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
        // committing on any produce failure. A transient produce failure that recovers gets
        // committed over by a later batch, dropping those events — accepted tradeoff; the downstream
        // processor dedups replays via source_offset/source_partition.
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

    /// Faithful local mirror of [`SingleTopicConsumer::json_recv_batch`]: the same
    /// timeout-vs-collect race and break-on-error semantics, differing only in the decode target —
    /// each message goes through [`decode_gated`] instead of a blanket
    /// `serde_json::from_slice::<ClickHouseEvent>`. The closure captures `&TeamIndex` (a `Copy`
    /// reference; `TeamIndex: Sync`, so the polled future stays `Send`).
    async fn recv_gated_batch(&self) -> Vec<Result<(Decoded, Offset), RecvErr>> {
        let team_index: &TeamIndex = &self.team_index;
        let mut results = Vec::with_capacity(self.batch_size);

        tokio::select! {
            _ = tokio::time::sleep(self.batch_timeout) => {}
            _ = async {
                while results.len() < self.batch_size {
                    let result = self
                        .consumer
                        .recv_with(|payload| decode_gated(payload, team_index))
                        .await;
                    let was_err = result.is_err();
                    results.push(result);
                    if was_err {
                        break; // mirror json_recv_batch: an error may signal a kafka problem
                    }
                }
            } => {}
        }

        results
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
    use serde_json::{json, Value};

    fn index_with(teams: &[i32]) -> TeamIndex {
        TeamIndex::from_teams(teams.iter().copied())
    }

    fn gate_fields(team_id: i32, person_id: Option<IgnoredAny>) -> GateFields {
        GateFields { team_id, person_id }
    }

    #[test]
    fn classify_gate_covers_every_gate_outcome() {
        let cases = [
            (
                "forward",
                Some(IgnoredAny),
                2,
                vec![2],
                GateOutcome::Forward,
            ),
            ("no person", None, 2, vec![2], GateOutcome::DropNoPersonId),
            (
                "team gate",
                Some(IgnoredAny),
                99,
                vec![2],
                GateOutcome::SkipTeamGate,
            ),
            (
                "no person precedence",
                None,
                99,
                vec![2],
                GateOutcome::DropNoPersonId,
            ),
            (
                "empty index",
                Some(IgnoredAny),
                2,
                vec![],
                GateOutcome::SkipTeamGate,
            ),
        ];

        for (name, person_id, team_id, teams, expected) in cases {
            let index = index_with(&teams);
            assert_eq!(
                classify_gate(&gate_fields(team_id, person_id), &index),
                expected,
                "case: {name}"
            );
        }
    }

    #[test]
    fn unloaded_index_forwards_nothing() {
        let index = TeamIndex::new();
        assert_eq!(
            classify_gate(&gate_fields(2, Some(IgnoredAny)), &index),
            GateOutcome::SkipTeamGate
        );
    }

    #[test]
    fn dropped_event_never_materializes_blobs() {
        // `properties` as a JSON object would fail a full `ClickHouseEvent` parse (the field is a
        // stringified blob). A team outside the index has its blob ignored by the gate and skips —
        // proof the dropped majority never pays the `parse_str` unescape — while a team inside the
        // index runs the survivor full parse and rejects the very same payload.
        let mut value: Value =
            serde_json::to_value(sample_clickhouse_event(99, Some("p"))).unwrap();
        value["properties"] = json!({ "a": [1, 2, 3] });
        let payload = serde_json::to_vec(&value).unwrap();

        assert!(matches!(
            decode_gated(&payload, &index_with(&[2])).unwrap(),
            Decoded::SkipTeamGate
        ));
        assert!(decode_gated(&payload, &index_with(&[99])).is_err());
    }

    #[test]
    fn missing_person_mode_skips_mismatched_team_instead_of_erroring() {
        // `person_mode` is required by the full parse but ignored by the gate. A team-mismatch event
        // missing it now counts as consumed + skipped rather than an invisible serde error.
        let mut value: Value =
            serde_json::to_value(sample_clickhouse_event(99, Some("p"))).unwrap();
        value.as_object_mut().unwrap().remove("person_mode");
        let payload = serde_json::to_vec(&value).unwrap();

        assert!(matches!(
            decode_gated(&payload, &index_with(&[2])).unwrap(),
            Decoded::SkipTeamGate
        ));
    }

    #[test]
    fn person_id_presence_matches_full_parse_semantics() {
        let index = index_with(&[2]);
        let base: Value =
            serde_json::to_value(sample_clickhouse_event(2, Some("ignored"))).unwrap();
        let decode =
            |value: Value| decode_gated(&serde_json::to_vec(&value).unwrap(), &index).unwrap();

        // Absent → DropNoPersonId (the person check precedes the team gate).
        let mut absent = base.clone();
        absent.as_object_mut().unwrap().remove("person_id");
        assert!(matches!(decode(absent), Decoded::DropNoPersonId));

        // null → DropNoPersonId.
        let mut null = base.clone();
        null["person_id"] = Value::Null;
        assert!(matches!(decode(null), Decoded::DropNoPersonId));

        // "" is present → Forward, and the empty person_id is moved out verbatim.
        let mut empty = base.clone();
        empty["person_id"] = json!("");
        match decode(empty) {
            Decoded::Forward { event, person_id } => {
                assert_eq!(person_id, "");
                assert!(
                    event.person_id.is_none(),
                    "person_id must be taken from the event"
                );
            }
            other => panic!("expected Forward, got {other:?}"),
        }

        // Valid string → Forward, person_id taken.
        let mut valid = base.clone();
        valid["person_id"] = json!("p");
        match decode(valid) {
            Decoded::Forward { event, person_id } => {
                assert_eq!(person_id, "p");
                assert!(event.person_id.is_none());
            }
            other => panic!("expected Forward, got {other:?}"),
        }
    }

    #[test]
    fn survivor_fully_materializes_the_forward_envelope() {
        let payload = serde_json::to_vec(&sample_clickhouse_event(2, Some("p"))).unwrap();
        match decode_gated(&payload, &index_with(&[2])).unwrap() {
            Decoded::Forward { event, person_id } => {
                assert_eq!(person_id, "p");
                assert_eq!(event.team_id, 2);
                assert!(event.person_id.is_none(), "person_id should be taken");
                // Blobs ignored on the drop path are fully parsed for survivors.
                assert_eq!(
                    event.properties.as_deref(),
                    Some(r#"{"$current_url":"/pricing"}"#)
                );
                assert_eq!(
                    event.person_properties.as_deref(),
                    Some(r#"{"email":"u@p.com"}"#)
                );
            }
            other => panic!("expected Forward, got {other:?}"),
        }
    }
}
