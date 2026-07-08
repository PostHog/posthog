//! Output producer: maps Stage 1 [`LeafTransition`]s to per-cohort [`CohortMembershipChange`]s.
//!
//! [`map_transition`] fans out to single-leaf cohorts only; composable (multi-leaf) cohorts are
//! emitted by Stage 2.

pub mod batcher;
pub mod cascade;
pub mod kafka;
pub mod merge;

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
pub use cascade::{CaptureCascadeSink, CascadeSink, KafkaCascadeSink, NoopCascadeSink};
pub use kafka::KafkaMembershipSink;
pub use merge::{
    CaptureStreamEventSink, CaptureTransferSink, KafkaStreamEventSink, KafkaTransferSink,
    StreamEventSink, TransferSink,
};

/// One per-cohort membership change on `cohort_membership_changed_shadow`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CohortMembershipChange {
    pub team_id: i32,
    pub cohort_id: i32,
    pub person_id: String,
    /// ClickHouse `DateTime64(6)` wire format.
    pub last_updated: String,
    pub status: MembershipStatus,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MembershipStatus {
    Entered,
    Left,
}

impl MembershipStatus {
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

/// Fan out one leaf transition to one membership change per single-leaf cohort that owns its LSK.
pub fn map_transition<'a>(
    filters: &'a TeamFilters,
    transition: &'a LeafTransition,
    last_updated: &'a str,
) -> impl Iterator<Item = CohortMembershipChange> + 'a {
    let cohorts: &[CohortId] = filters
        .by_lsk_to_single_leaf_cohorts
        .get(&transition.leaf_state_key)
        .map_or(&[], Vec::as_slice);
    if cohorts.is_empty()
        && !filters
            .by_lsk_to_composable_cohorts
            .contains_key(&transition.leaf_state_key)
    {
        counter!(OUTPUT_TRANSITIONS_UNMAPPED, "reason" => "no_emitting_cohort").increment(1);
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

/// Current UTC time as a ClickHouse `DateTime64(6)` string (microseconds).
pub fn now_last_updated() -> String {
    Utc::now().format("%Y-%m-%d %H:%M:%S%.6f").to_string()
}

#[async_trait]
pub trait MembershipSink: Send + Sync {
    async fn produce(
        &self,
        changes: Vec<CohortMembershipChange>,
    ) -> Vec<Result<(), KafkaProduceError>>;
}

#[derive(Debug, Default, Clone)]
pub struct CaptureSink {
    changes: Arc<Mutex<Vec<CohortMembershipChange>>>,
    fail_remaining: Arc<AtomicUsize>,
}

impl CaptureSink {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn failing_first(n: usize) -> Self {
        Self {
            changes: Arc::default(),
            fail_remaining: Arc::new(AtomicUsize::new(n)),
        }
    }

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
    use chrono_tz::UTC;
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

    #[test]
    fn map_transition_entered_maps_to_one_change() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(91204), TeamId(42), &wrap(vec![behavioral_leaf(7)]))
            .unwrap();
        let filters = builder.freeze(UTC);
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
        let filters = builder.freeze(UTC);
        let lsk = LeafStateKey::for_person_property(b"fedcba9876543210");

        let changes: Vec<_> =
            map_transition(&filters, &transition(lsk, TransitionKind::Left), TS).collect();

        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].status, MembershipStatus::Left);
    }

    #[test]
    fn map_transition_fans_out_to_every_owning_cohort() {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(CohortId(1), TeamId(42), &wrap(vec![behavioral_leaf(7)]))
            .unwrap();
        builder
            .add_cohort(CohortId(2), TeamId(42), &wrap(vec![behavioral_leaf(7)]))
            .unwrap();
        let filters = builder.freeze(UTC);
        let lsk = filters.by_condition_to_lsk[&HASH][0];

        let mut cohorts: Vec<i32> =
            map_transition(&filters, &transition(lsk, TransitionKind::Entered), TS)
                .map(|change| change.cohort_id)
                .collect();
        cohorts.sort_unstable();
        assert_eq!(cohorts, vec![1, 2]);
    }

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
        let filters = builder.freeze(UTC);
        let lsk = filters.by_condition_to_lsk[&HASH][0];

        let changes: Vec<_> =
            map_transition(&filters, &transition(lsk, TransitionKind::Entered), TS).collect();
        assert!(
            changes.is_empty(),
            "a leaf owned only by a multi-leaf cohort produces no shadow output",
        );
    }

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

    #[test]
    fn now_last_updated_is_microsecond_clickhouse_format() {
        let now = now_last_updated();
        let (date_time, fraction) = now.split_once('.').expect("has a fractional part");
        assert_eq!(fraction.len(), 6, "microseconds, not nanoseconds: {now}");
        assert!(fraction.chars().all(|c| c.is_ascii_digit()));

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
