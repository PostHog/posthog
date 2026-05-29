//! Output producer (TDD §2.3, §2.8, §4.7) — PR 1.8.
//!
//! Maps the Stage 1 worker's per-leaf [`LeafTransition`]s to per-cohort
//! [`CohortMembershipChange`]s and produces them to the shadow topic
//! `cohort_membership_changed_shadow`, so the new pipeline emits observable, parity-comparable
//! output for the first time.
//!
//! ## M1 scope: leaf-level shadow output, not Stage 2 composition
//!
//! There is no boolean composition yet, so a single leaf flip can only determine membership for a
//! **single-leaf (single-condition) cohort**. [`map_transition`] therefore fans a transition out
//! through [`TeamFilters::by_lsk_to_single_leaf_cohorts`](crate::filters::reverse_index::TeamFilters),
//! which is keyed by [`LeafStateKey`](crate::stage1::key::LeafStateKey) (window/threshold-precise,
//! C1-correct) and populated only for single-leaf cohorts. A transition whose leaf belongs only to
//! multi-leaf cohorts maps to nothing and bumps `output_transitions_unmapped_total`.
//!
//! ## The I/O seam
//!
//! [`MembershipSink`] decouples the worker from Kafka: production uses [`KafkaMembershipSink`]
//! ([`kafka`]); tests use [`CaptureSink`], so the whole worker flush + offset-gating path is
//! exercisable without a broker. M3 (cascade) adds a second sink behind the same seam.
//!
//! Produces are flushed and acked **before** the worker marks its Kafka offset
//! ("produce before commit", TDD §2.3, §6.1 PR 1.8); the flush is at-least-once, which is
//! idempotent for the per-cohort parity diff.

pub mod batcher;
pub mod kafka;

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use chrono::Utc;
use common_kafka::kafka_producer::KafkaProduceError;
use metrics::counter;
use serde::{Deserialize, Serialize};

use crate::filters::reverse_index::TeamFilters;
use crate::filters::CohortId;
use crate::observability::metrics::OUTPUT_TRANSITIONS_UNMAPPED;
use crate::stage1::transition::{LeafTransition, TransitionKind};

pub use batcher::OutputBuffer;
pub use kafka::KafkaMembershipSink;

/// One per-cohort membership change on `cohort_membership_changed_shadow` (TDD §4.7). The wire
/// shape matches the legacy Python producer and the Node Zod consumer exactly:
///
/// ```jsonc
/// { "team_id": 42, "cohort_id": 91204, "person_id": "01928aaa-…",
///   "last_updated": "2026-05-26 12:34:56.789123", "status": "entered" }
/// ```
///
/// `team_id`/`cohort_id` are `i32` (from [`TeamId`](crate::filters::TeamId) / [`CohortId`]); they
/// serialize as JSON numbers, which Postgres and the Zod `z.number()` schema accept.
///
/// [`Deserialize`] is derived for round-trip tests (decoding the produced bytes back off the
/// shadow topic); the production path only serializes.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CohortMembershipChange {
    pub team_id: i32,
    pub cohort_id: i32,
    /// Stringified person UUID — the Zod schema is `z.guid()` and the topic is keyed by it.
    pub person_id: String,
    /// ClickHouse `DateTime64(6)` wire format, `"YYYY-MM-DD HH:MM:SS.ffffff"`.
    pub last_updated: String,
    pub status: MembershipStatus,
}

/// Membership direction. Serializes snake_case to `"entered"` / `"left"`, matching the consumer's
/// `z.enum(['entered', 'left'])`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MembershipStatus {
    Entered,
    Left,
}

impl MembershipStatus {
    /// The metric-label form, identical to the serialized wire value so `status` reads the same on
    /// the topic and in `output_membership_changes_emitted_total`.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Entered => "entered",
            Self::Left => "left",
        }
    }
}

impl From<TransitionKind> for MembershipStatus {
    fn from(kind: TransitionKind) -> Self {
        match kind {
            TransitionKind::Entered => Self::Entered,
            TransitionKind::Left => Self::Left,
        }
    }
}

/// Project one Stage 1 leaf transition to the membership changes it implies, one per single-leaf
/// cohort owning the transition's [`LeafStateKey`](crate::stage1::key::LeafStateKey).
///
/// **This is leaf-level shadow output, not Stage 2 composition.** A transition whose leaf maps to no
/// single-leaf cohort (it belongs only to multi-leaf cohorts) yields an empty iterator and bumps
/// `output_transitions_unmapped_total{reason="multi_leaf_cohort"}`. The returned iterator borrows
/// `filters`, so the caller consumes it (e.g. into an [`OutputBuffer`]) while the snapshot is held.
pub fn map_transition<'a>(
    filters: &'a TeamFilters,
    transition: &'a LeafTransition,
    last_updated: &'a str,
) -> impl Iterator<Item = CohortMembershipChange> + 'a {
    let cohorts: &[CohortId] = filters
        .by_lsk_to_single_leaf_cohorts
        .get(&transition.leaf_state_key)
        .map_or(&[], Vec::as_slice);
    if cohorts.is_empty() {
        counter!(OUTPUT_TRANSITIONS_UNMAPPED, "reason" => "multi_leaf_cohort").increment(1);
    }
    let team_id = transition.team_id.0;
    let status = MembershipStatus::from(transition.kind);
    let person_id = transition.person_id.to_string();
    cohorts
        .iter()
        .map(move |&cohort_id| CohortMembershipChange {
            team_id,
            cohort_id: cohort_id.0,
            person_id: person_id.clone(),
            last_updated: last_updated.to_string(),
            status,
        })
}

/// The current UTC time as a ClickHouse `DateTime64(6)` string, matching the legacy Python
/// producer's `datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")`.
///
/// The chrono spec uses `%.6f` (microseconds — 6 digits, leading dot included), **not** `%f`
/// (nanoseconds, 9 digits), which would break the `DateTime64(6)` JSONEachRow parse and the
/// per-row parity diff.
pub fn now_last_updated() -> String {
    Utc::now().format("%Y-%m-%d %H:%M:%S%.6f").to_string()
}

/// The output I/O seam: produce a batch of membership changes and await all acks, returning one
/// result per change **in input order** so the worker can gate its offset commit on full success.
///
/// At-least-once: a re-produced change is idempotent for the per-cohort parity diff, so the worker
/// safely replays a sub-batch whose produce failed.
#[async_trait]
pub trait MembershipSink: Send + Sync {
    async fn produce(
        &self,
        changes: Vec<CohortMembershipChange>,
    ) -> Vec<Result<(), KafkaProduceError>>;
}

/// An in-memory [`MembershipSink`] for tests: records every produced change and reports all-`Ok`.
///
/// Optionally fails its first `n` flushes ([`failing_first`](Self::failing_first)) — recording
/// nothing and returning an `Err` per change — to exercise the worker's produce-error offset gate.
/// `pub` for the `tests/` crates, consistent with the crate's pub-for-tests seam (`TeamFiltersBuilder`,
/// `CatalogHandle::from_catalog`).
#[derive(Debug, Default, Clone)]
pub struct CaptureSink {
    changes: Arc<Mutex<Vec<CohortMembershipChange>>>,
    /// Number of upcoming `produce` calls still set to fail; counts down to zero, then succeeds.
    fail_remaining: Arc<AtomicUsize>,
}

impl CaptureSink {
    /// A sink that records and acks everything.
    pub fn new() -> Self {
        Self::default()
    }

    /// A sink that fails its first `n` flushes (recording nothing, returning an `Err` per change),
    /// then behaves like [`new`](Self::new).
    pub fn failing_first(n: usize) -> Self {
        Self {
            changes: Arc::default(),
            fail_remaining: Arc::new(AtomicUsize::new(n)),
        }
    }

    /// A snapshot of everything successfully produced so far, in production order.
    pub fn changes(&self) -> Vec<CohortMembershipChange> {
        self.changes
            .lock()
            .expect("CaptureSink mutex poisoned")
            .clone()
    }
}

#[async_trait]
impl MembershipSink for CaptureSink {
    async fn produce(
        &self,
        changes: Vec<CohortMembershipChange>,
    ) -> Vec<Result<(), KafkaProduceError>> {
        // Consume one "fail" credit iff any remain (saturating at zero). `then` (not `then_some`) so
        // `n - 1` is never evaluated when `n == 0` — that would underflow.
        let should_fail = self
            .fail_remaining
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |n| {
                (n > 0).then(|| n - 1)
            })
            .is_ok();
        if should_fail {
            return changes
                .into_iter()
                .map(|_| Err(KafkaProduceError::KafkaProduceCanceled))
                .collect();
        }
        let acks = (0..changes.len()).map(|_| Ok(())).collect();
        self.changes
            .lock()
            .expect("CaptureSink mutex poisoned")
            .extend(changes);
        acks
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};
    use uuid::Uuid;

    use crate::filters::{CohortId, TeamFiltersBuilder, TeamId};
    use crate::stage1::key::LeafStateKey;

    const HASH: [u8; 16] = *b"0123456789abcdef";
    const TS: &str = "2026-05-26 12:34:56.789123";

    fn behavioral_leaf(time_value: i64) -> Value {
        json!({
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "time_value": time_value,
            "time_interval": "day",
            "conditionHash": "0123456789abcdef",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
        })
    }

    fn person_leaf() -> Value {
        json!({
            "type": "person",
            "key": "email",
            "value": "a@b.com",
            "operator": "exact",
            "conditionHash": "fedcba9876543210",
            "bytecode": ["_H", 1, 32, "a@b.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        })
    }

    fn wrap(values: Vec<Value>) -> Value {
        json!({ "properties": { "type": "AND", "values": values } })
    }

    fn transition(lsk: LeafStateKey, kind: TransitionKind) -> LeafTransition {
        LeafTransition {
            team_id: TeamId(42),
            leaf_state_key: lsk,
            person_id: Uuid::from_u128(0x01928aaa),
            condition_hash: HASH,
            kind,
        }
    }

    /// One single-leaf cohort → its transition maps to exactly one `entered` change with the §4.7
    /// shape.
    #[test]
    fn map_transition_entered_maps_to_one_change() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(91204), TeamId(42), &wrap(vec![behavioral_leaf(7)]))
            .unwrap();
        let filters = builder.freeze();
        let lsk = filters.by_condition_to_lsk[&HASH][0];

        let changes: Vec<_> =
            map_transition(&filters, &transition(lsk, TransitionKind::Entered), TS).collect();

        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].team_id, 42);
        assert_eq!(changes[0].cohort_id, 91204);
        assert_eq!(changes[0].status, MembershipStatus::Entered);
        assert_eq!(changes[0].last_updated, TS);
        assert_eq!(
            changes[0].person_id,
            Uuid::from_u128(0x01928aaa).to_string()
        );
    }

    #[test]
    fn map_transition_left_carries_left_status() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(42), &wrap(vec![person_leaf()]))
            .unwrap();
        let filters = builder.freeze();
        let lsk = LeafStateKey::for_person_property(b"fedcba9876543210");

        let changes: Vec<_> =
            map_transition(&filters, &transition(lsk, TransitionKind::Left), TS).collect();

        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].status, MembershipStatus::Left);
    }

    /// A leaf shared by N single-leaf cohorts fans out to N changes, one per cohort.
    #[test]
    fn map_transition_fans_out_to_every_owning_cohort() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(42), &wrap(vec![behavioral_leaf(7)]))
            .unwrap();
        builder
            .add_cohort(CohortId(2), TeamId(42), &wrap(vec![behavioral_leaf(7)]))
            .unwrap();
        let filters = builder.freeze();
        let lsk = filters.by_condition_to_lsk[&HASH][0];

        let mut cohorts: Vec<i32> =
            map_transition(&filters, &transition(lsk, TransitionKind::Entered), TS)
                .map(|change| change.cohort_id)
                .collect();
        cohorts.sort_unstable();
        assert_eq!(cohorts, vec![1, 2]);
    }

    /// A leaf that belongs only to a multi-leaf cohort maps to nothing (Stage 2's job).
    #[test]
    fn map_transition_for_a_multi_leaf_only_leaf_is_empty() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(42),
                &wrap(vec![behavioral_leaf(7), person_leaf()]),
            )
            .unwrap();
        let filters = builder.freeze();
        let lsk = filters.by_condition_to_lsk[&HASH][0];

        let changes: Vec<_> =
            map_transition(&filters, &transition(lsk, TransitionKind::Entered), TS).collect();
        assert!(
            changes.is_empty(),
            "a leaf owned only by a multi-leaf cohort produces no shadow output",
        );
    }

    /// The serialized JSON has exactly the five §4.7 keys, snake_case status, and a string UUID.
    #[test]
    fn serialized_change_has_exactly_the_contract_keys() {
        let change = CohortMembershipChange {
            team_id: 42,
            cohort_id: 91204,
            person_id: "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
            last_updated: TS.to_string(),
            status: MembershipStatus::Entered,
        };
        let value = serde_json::to_value(&change).unwrap();
        let object = value.as_object().unwrap();

        let mut keys: Vec<&str> = object.keys().map(String::as_str).collect();
        keys.sort_unstable();
        assert_eq!(
            keys,
            vec![
                "cohort_id",
                "last_updated",
                "person_id",
                "status",
                "team_id"
            ],
        );
        assert_eq!(object["status"], json!("entered"));
        assert!(object["person_id"].is_string());
        assert_eq!(object["team_id"], json!(42));
    }

    #[test]
    fn left_status_serializes_snake_case() {
        let value = serde_json::to_value(MembershipStatus::Left).unwrap();
        assert_eq!(value, json!("left"));
    }

    /// `%.6f` (microseconds) — not `%f` (nanoseconds): exactly six fractional digits.
    #[test]
    fn now_last_updated_is_microsecond_clickhouse_format() {
        let now = now_last_updated();
        let (date_time, fraction) = now.split_once('.').expect("has a fractional part");
        assert_eq!(fraction.len(), 6, "microseconds, not nanoseconds: {now}");
        assert!(fraction.chars().all(|c| c.is_ascii_digit()));

        // "YYYY-MM-DD HH:MM:SS"
        let (date, time) = date_time.split_once(' ').expect("date and time");
        assert_eq!(date.len(), 10);
        assert_eq!(date.matches('-').count(), 2);
        assert_eq!(time.matches(':').count(), 2);
    }

    #[tokio::test]
    async fn capture_sink_records_and_acks_in_order() {
        let sink = CaptureSink::new();
        let change = CohortMembershipChange {
            team_id: 1,
            cohort_id: 2,
            person_id: "p".to_string(),
            last_updated: TS.to_string(),
            status: MembershipStatus::Entered,
        };
        let acks = sink.produce(vec![change.clone(), change.clone()]).await;
        assert_eq!(acks.len(), 2);
        assert!(acks.iter().all(Result::is_ok));
        assert_eq!(sink.changes(), vec![change.clone(), change]);
    }

    #[tokio::test]
    async fn capture_sink_failing_first_fails_then_succeeds_recording_nothing_on_failure() {
        let sink = CaptureSink::failing_first(1);
        let change = CohortMembershipChange {
            team_id: 1,
            cohort_id: 2,
            person_id: "p".to_string(),
            last_updated: TS.to_string(),
            status: MembershipStatus::Left,
        };

        let first = sink.produce(vec![change.clone()]).await;
        assert!(first.iter().all(Result::is_err), "first flush fails");
        assert!(sink.changes().is_empty(), "a failed flush records nothing");

        let second = sink.produce(vec![change.clone()]).await;
        assert!(second.iter().all(Result::is_ok), "second flush succeeds");
        assert_eq!(sink.changes(), vec![change]);
    }
}
