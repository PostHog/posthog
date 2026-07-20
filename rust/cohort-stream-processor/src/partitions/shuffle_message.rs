//! The typed unit of work the partition router dispatches to a partition worker.

use crate::cascade::CascadeMessage;
use crate::consumers::events::CohortStreamEvent;
use crate::consumers::seeds::SeedWork;
use crate::merge::transfer::{MergeStateTransfer, PersonMergeEvent};

/// A unit of work routed to the partition worker that owns its `(team_id, person_id)` key.
#[derive(Debug)]
pub enum ShuffleMessage {
    /// A re-keyed event from `cohort_stream_events`, paired with its offset (`cse_offset`).
    /// The worker marks this offset processed only after membership changes are produced and acked.
    /// Boxed so the fat event doesn't inflate every `ShuffleMessage`'s inline size.
    Event {
        event: Box<CohortStreamEvent>,
        cse_offset: i64,
        /// Broker timestamp of the consumed message — the seed fence's watermark input. `None`
        /// never advances the watermark.
        broker_ts_ms: Option<i64>,
    },
    /// A time-driven eviction tick with the cutoff `due_before_ms`. Serialized on the same channel
    /// as events so the worker processes it in order with no locks.
    Sweep { due_before_ms: i64 },
    /// A merge trigger from `KAFKA_PERSON_MERGE_EVENTS` (keyed by P_old), paired with its topic
    /// offset. Marked on the merge tracker, not the events tracker.
    Merge {
        event: PersonMergeEvent,
        offset: i64,
    },
    /// A state transfer from `cohort_merge_state_transfer` (keyed by P_new), paired with its topic
    /// offset. Boxed because it's rare and large.
    Transfer {
        transfer: Box<MergeStateTransfer>,
        offset: i64,
    },
    /// A cohort flip from `cohort_cascade_events` (keyed by `hash(team_id, person_id)`), paired with
    /// its topic offset. Marked on the cascade tracker, not the events tracker. Boxed because it's
    /// rare.
    Cascade {
        message: Box<CascadeMessage>,
        offset: i64,
    },
    /// Periodic tick to re-produce any `cf_pending_transfers` entries left by a failed produce.
    RedrivePendingTransfers,
    /// Periodic tick to garbage-collect expired merge idempotence markers and tombstones. Both
    /// cutoffs are computed at tick time by the sweeper (`now − retention`), so the worker stays
    /// clock-free — same posture as [`Sweep`](ShuffleMessage::Sweep)'s `due_before_ms`. Marker CFs
    /// (`cf_merge_drains_applied`, `cf_merge_applied`) evict below `marker_cutoff_ms`; tombstones
    /// (`cf_merge_tombstones`) evict below `tombstone_cutoff_ms`.
    MergeCfGc {
        marker_cutoff_ms: i64,
        tombstone_cutoff_ms: i64,
    },
    /// A backfill day-tile (or its consume-side skip), paired with its topic offset. Marked on
    /// the seed tracker, never the events tracker. Boxed so the tile doesn't inflate every
    /// `ShuffleMessage`.
    Seed { work: Box<SeedWork>, offset: i64 },
}

impl ShuffleMessage {
    /// The offset an [`Event`](Self::Event) carries; `None` for every other variant, including
    /// [`Seed`](Self::Seed) (its offset belongs to the seed tracker).
    pub fn event_offset(&self) -> Option<i64> {
        match self {
            ShuffleMessage::Event { cse_offset, .. } => Some(*cse_offset),
            ShuffleMessage::Sweep { .. }
            | ShuffleMessage::Merge { .. }
            | ShuffleMessage::Transfer { .. }
            | ShuffleMessage::Cascade { .. }
            | ShuffleMessage::RedrivePendingTransfers
            | ShuffleMessage::MergeCfGc { .. }
            | ShuffleMessage::Seed { .. } => None,
        }
    }

    /// The seed-topic offset a [`Seed`](Self::Seed) carries; `None` for every other variant.
    pub fn seed_offset(&self) -> Option<i64> {
        match self {
            ShuffleMessage::Seed { offset, .. } => Some(*offset),
            ShuffleMessage::Event { .. }
            | ShuffleMessage::Sweep { .. }
            | ShuffleMessage::Merge { .. }
            | ShuffleMessage::Transfer { .. }
            | ShuffleMessage::Cascade { .. }
            | ShuffleMessage::RedrivePendingTransfers
            | ShuffleMessage::MergeCfGc { .. } => None,
        }
    }

    /// Whether this message reserves an intake-budget slot; maintenance/control messages must
    /// always flow.
    pub fn counts_toward_intake(&self) -> bool {
        match self {
            ShuffleMessage::Event { .. } | ShuffleMessage::Seed { .. } => true,
            ShuffleMessage::Sweep { .. }
            | ShuffleMessage::Merge { .. }
            | ShuffleMessage::Transfer { .. }
            | ShuffleMessage::Cascade { .. }
            | ShuffleMessage::RedrivePendingTransfers
            | ShuffleMessage::MergeCfGc { .. } => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    use crate::producer::{CohortMembershipChange, MembershipStatus};

    fn sample_cascade() -> CascadeMessage {
        CascadeMessage {
            change: CohortMembershipChange {
                team_id: 1,
                cohort_id: 42,
                person_id: "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
                last_updated: "2026-05-26 12:34:56.789000".to_string(),
                status: MembershipStatus::Entered,
                origin: None,
                run_id: None,
            },
            source_offset: 9,
            depth: 1,
            originating_cohort_id: 42,
            cascade_chain: vec![42],
        }
    }

    fn sample_event(source_offset: i64) -> CohortStreamEvent {
        CohortStreamEvent {
            team_id: 1,
            person_id: "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
            distinct_id: "d".to_string(),
            uuid: "u".to_string(),
            event: "$pageview".to_string(),
            timestamp: "2026-05-26 12:34:56.789000".to_string(),
            properties: None,
            person_properties: None,
            elements_chain: None,
            source_offset,
            source_partition: 3,
            redirected_from: None,
            redirect_hops: 0,
        }
    }

    fn sample_merge() -> PersonMergeEvent {
        PersonMergeEvent {
            team_id: 1,
            old_person_uuid: Uuid::from_u128(1),
            new_person_uuid: Uuid::from_u128(2),
            merged_at_ms: 1_716_800_000_000,
            schema_version: 1,
        }
    }

    fn sample_transfer() -> MergeStateTransfer {
        MergeStateTransfer {
            team_id: 1,
            old_person_uuid: Uuid::from_u128(1),
            new_person_uuid: Uuid::from_u128(2),
            merged_at_ms: 1_716_800_000_000,
            source_partition: 3,
            source_offset: 9,
            leaves: vec![],
            forward_hops: 0,

            person_dedup: None,
        }
    }

    #[test]
    fn event_variant_carries_event_offset_and_broker_ts() {
        let message = ShuffleMessage::Event {
            event: Box::new(sample_event(42)),
            cse_offset: 7,
            broker_ts_ms: Some(1_700_000_000_000),
        };

        // No wildcard, so a new variant forces this test to be revisited.
        match message {
            ShuffleMessage::Event {
                event,
                cse_offset,
                broker_ts_ms,
            } => {
                assert_eq!(event.source_offset, 42);
                assert_eq!(event.source_partition, 3);
                assert_eq!(cse_offset, 7);
                assert_eq!(broker_ts_ms, Some(1_700_000_000_000));
            }
            ShuffleMessage::Sweep { .. }
            | ShuffleMessage::Merge { .. }
            | ShuffleMessage::Transfer { .. }
            | ShuffleMessage::RedrivePendingTransfers
            | ShuffleMessage::MergeCfGc { .. }
            | ShuffleMessage::Seed { .. }
            | ShuffleMessage::Cascade { .. } => unreachable!("constructed an Event"),
        }
    }

    fn sample_seed_work() -> SeedWork {
        use std::num::NonZeroU32;

        use cohort_core::seed::{ClaimEpoch, ConditionHash, RunId, SChunkMs, SeedTile};

        SeedWork::Tile(SeedTile::new(
            crate::filters::TeamId(1),
            Uuid::from_u128(9),
            ConditionHash::parse("0123456789abcdef").unwrap(),
            NonZeroU32::new(3).unwrap(),
            20_614,
            SChunkMs(1_700_000_000_000),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        ))
    }

    #[test]
    fn seed_variant_carries_its_own_offset_and_never_an_event_offset() {
        let message = ShuffleMessage::Seed {
            work: Box::new(sample_seed_work()),
            offset: 17,
        };

        assert_eq!(
            message.event_offset(),
            None,
            "a seed offset must never reach the events tracker",
        );
        assert_eq!(message.seed_offset(), Some(17));
        assert!(message.counts_toward_intake());

        let event = ShuffleMessage::Event {
            event: Box::new(sample_event(1)),
            cse_offset: 3,
            broker_ts_ms: None,
        };
        assert_eq!(event.seed_offset(), None);
        assert!(event.counts_toward_intake());
        assert!(!ShuffleMessage::RedrivePendingTransfers.counts_toward_intake());
    }

    #[test]
    fn sweep_variant_carries_the_due_before_cutoff() {
        let message = ShuffleMessage::Sweep {
            due_before_ms: 1_700_000_000_000,
        };
        match message {
            ShuffleMessage::Sweep { due_before_ms } => assert_eq!(due_before_ms, 1_700_000_000_000),
            ShuffleMessage::Event { .. }
            | ShuffleMessage::Merge { .. }
            | ShuffleMessage::Transfer { .. }
            | ShuffleMessage::RedrivePendingTransfers
            | ShuffleMessage::MergeCfGc { .. }
            | ShuffleMessage::Seed { .. }
            | ShuffleMessage::Cascade { .. } => unreachable!("constructed a Sweep"),
        }
    }

    #[test]
    fn merge_cf_gc_variant_carries_both_cutoffs() {
        let message = ShuffleMessage::MergeCfGc {
            marker_cutoff_ms: 100,
            tombstone_cutoff_ms: 200,
        };
        match message {
            ShuffleMessage::MergeCfGc {
                marker_cutoff_ms,
                tombstone_cutoff_ms,
            } => {
                assert_eq!(marker_cutoff_ms, 100);
                assert_eq!(tombstone_cutoff_ms, 200);
            }
            ShuffleMessage::Event { .. }
            | ShuffleMessage::Sweep { .. }
            | ShuffleMessage::Merge { .. }
            | ShuffleMessage::Transfer { .. }
            | ShuffleMessage::RedrivePendingTransfers
            | ShuffleMessage::Seed { .. }
            | ShuffleMessage::Cascade { .. } => unreachable!("constructed a MergeCfGc"),
        }
    }

    #[test]
    fn merge_and_transfer_variants_carry_their_own_topic_offsets() {
        let merge = ShuffleMessage::Merge {
            event: sample_merge(),
            offset: 11,
        };
        match merge {
            ShuffleMessage::Merge { event, offset } => {
                assert_eq!(event.old_person_uuid, Uuid::from_u128(1));
                assert_eq!(offset, 11);
            }
            ShuffleMessage::Event { .. }
            | ShuffleMessage::Sweep { .. }
            | ShuffleMessage::Transfer { .. }
            | ShuffleMessage::RedrivePendingTransfers
            | ShuffleMessage::MergeCfGc { .. }
            | ShuffleMessage::Seed { .. }
            | ShuffleMessage::Cascade { .. } => unreachable!("constructed a Merge"),
        }

        let transfer = ShuffleMessage::Transfer {
            transfer: Box::new(sample_transfer()),
            offset: 23,
        };
        match transfer {
            ShuffleMessage::Transfer { transfer, offset } => {
                assert_eq!(transfer.new_person_uuid, Uuid::from_u128(2));
                assert_eq!(offset, 23);
            }
            ShuffleMessage::Event { .. }
            | ShuffleMessage::Sweep { .. }
            | ShuffleMessage::Merge { .. }
            | ShuffleMessage::RedrivePendingTransfers
            | ShuffleMessage::MergeCfGc { .. }
            | ShuffleMessage::Seed { .. }
            | ShuffleMessage::Cascade { .. } => unreachable!("constructed a Transfer"),
        }
    }

    #[test]
    fn cascade_variant_carries_the_boxed_message_and_offset() {
        let message = ShuffleMessage::Cascade {
            message: Box::new(sample_cascade()),
            offset: 31,
        };
        match message {
            ShuffleMessage::Cascade { message, offset } => {
                assert_eq!(message.change.cohort_id, 42);
                assert_eq!(message.depth, 1);
                assert_eq!(message.cascade_chain, vec![42]);
                assert_eq!(offset, 31);
            }
            ShuffleMessage::Event { .. }
            | ShuffleMessage::Sweep { .. }
            | ShuffleMessage::Merge { .. }
            | ShuffleMessage::Transfer { .. }
            | ShuffleMessage::RedrivePendingTransfers
            | ShuffleMessage::MergeCfGc { .. }
            | ShuffleMessage::Seed { .. } => unreachable!("constructed a Cascade"),
        }
    }
}
