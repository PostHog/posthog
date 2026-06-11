//! The typed unit of work the partition router dispatches to a partition worker.
//!
//! The router never inspects the payload: affinity is supplied alongside the message, since the
//! shuffler's re-key already placed each event on the correct `cohort_stream_events` partition, and
//! the merge-protocol topics are co-partitioned with it (TDD §4.5.1).

use crate::consumers::events::CohortStreamEvent;
use crate::merge::transfer::{MergeStateTransfer, PersonMergeEvent};

/// A unit of work routed to the partition worker that owns its `(team_id, person_id)` key.
///
/// The hot `Event` variant is deliberately unboxed (see its doc), so it dwarfs the rare `Sweep`
/// tick — boxing the common variant to shrink the enum would add a per-event allocation on the
/// hot path, the opposite of what we want. A `Sweep` is at most one per partition per cycle; merges
/// are ~12/s globally.
#[derive(Debug)]
#[allow(clippy::large_enum_variant)]
pub enum ShuffleMessage {
    /// A re-keyed event from `cohort_stream_events`, paired with its offset on that topic
    /// (`cse_offset`); the partition is implicit (the worker's own). The worker marks this offset
    /// processed only *after* the event's membership changes are produced and acked
    /// (produce-before-commit), so it can't be committed ahead of its durable shadow output. Distinct
    /// from [`CohortStreamEvent::source_partition`]/[`source_offset`](CohortStreamEvent::source_offset),
    /// which anchor per-key replay idempotence in Stage 1.
    ///
    /// Unboxed on purpose: events are the hot, common variant, so inlining avoids a per-event heap
    /// allocation and keeps each `Vec<ShuffleMessage>` slot contiguous.
    Event {
        event: CohortStreamEvent,
        cse_offset: i64,
    },
    /// A time-driven eviction tick, carrying the cutoff `due_before_ms = now − safety_margin`
    /// computed once per cycle by the sweeper and shipped to every owned worker. Riding the same
    /// per-partition channel as [`Event`](Self::Event) serializes the sweep behind in-flight events
    /// on the owning worker, so the worker drains its own `EvictionQueue` with no locks (the
    /// worker-affinity invariant). The cutoff is the queue's only clock input.
    Sweep { due_before_ms: i64 },
    /// A merge trigger from `KAFKA_PERSON_MERGE_EVENTS` (keyed by P_old, so it lands on the worker
    /// that owns P_old's state), paired with its offset on that topic. The worker drains P_old and
    /// marks `offset` on the **merge** tracker — never the events `max_offset` — gating it per the
    /// drain outcome (D7).
    Merge {
        event: PersonMergeEvent,
        offset: i64,
    },
    /// A packaged state transfer from `cohort_merge_state_transfer` (keyed by P_new), paired with
    /// its offset on that topic, marked on the **transfer** tracker once the apply `WriteBatch`
    /// commits (D7). Boxed: rare (~12/s globally) and large (it carries whole per-leaf records), so
    /// boxing keeps the enum near the hot `Event` variant's size at a negligible per-merge cost.
    Transfer {
        transfer: Box<MergeStateTransfer>,
        offset: i64,
    },
    /// A periodic tick telling the worker to re-produce any `cf_pending_transfers` entries left by
    /// a transfer-produce failure (D3's within-tenure recovery). Carries no payload — the worker
    /// scans its own partition's outbox slice.
    RedrivePendingTransfers,
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

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
        }
    }

    #[test]
    fn event_variant_carries_event_and_cse_offset() {
        let message = ShuffleMessage::Event {
            event: sample_event(42),
            cse_offset: 7,
        };

        // No wildcard, so a new variant forces this test to be revisited.
        match message {
            ShuffleMessage::Event { event, cse_offset } => {
                assert_eq!(event.source_offset, 42);
                assert_eq!(event.source_partition, 3);
                assert_eq!(cse_offset, 7);
            }
            ShuffleMessage::Sweep { .. }
            | ShuffleMessage::Merge { .. }
            | ShuffleMessage::Transfer { .. }
            | ShuffleMessage::RedrivePendingTransfers => unreachable!("constructed an Event"),
        }
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
            | ShuffleMessage::RedrivePendingTransfers => unreachable!("constructed a Sweep"),
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
            | ShuffleMessage::RedrivePendingTransfers => unreachable!("constructed a Merge"),
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
            | ShuffleMessage::RedrivePendingTransfers => unreachable!("constructed a Transfer"),
        }
    }
}
