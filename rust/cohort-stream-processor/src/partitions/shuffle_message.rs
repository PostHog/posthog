//! The typed unit of work the partition router dispatches to a partition worker (TDD §3, §4).
//!
//! Each variant is a mutation that targets the state owned by exactly one partition worker. The
//! router never inspects the payload: partition affinity is supplied *alongside* the message by
//! the consumer, because the shuffler's re-key already placed each event on the correct
//! `cohort_stream_events` partition (§2.3, "**No content hashing**").
//!
//! For M1 (Stage 1 single-condition shadow-run) only [`ShuffleMessage::Event`] is built. The
//! remaining variants are introduced by their owning PRs as the matching subsystems land — each
//! is an additive, non-breaking addition to this crate-internal enum, so there is no payload to
//! invent now:
//!
//! | Future variant       | Carries                                  | PR  | TDD    |
//! |----------------------|------------------------------------------|-----|--------|
//! | `PersonMergeDrain`   | a merge event → Phase 1 drain on `P_old` | 3.1 | §4.5.1 |
//! | `MergeTransferApply` | packaged state → Phase 2 apply on `P_new`| 3.1 | §4.5.1 |
//! | `Cascade`            | a parent-cohort membership flip          | 3.4 | §4.8   |
//! | `Seed`               | a cold-start backfill event              | 6.2 | §4.4   |
//! | `Sweep`              | a due eviction key off the sweep heap    | 2.3 | §2.6   |

use crate::consumers::events::CohortStreamEvent;

/// A unit of work routed to the partition worker that owns its `(team_id, person_id)` key.
///
/// See the module comment for the variants each later PR adds.
#[derive(Debug)]
pub enum ShuffleMessage {
    /// A re-keyed event from `cohort_stream_events` (the hot path), paired with its offset **on
    /// that topic** (`cse_offset`).
    ///
    /// The owning topic partition is implicit — it is the worker's own `partition_id` — so only the
    /// offset travels on the message. The worker marks this offset processed **after** the event's
    /// membership changes have been produced and acked (PR 1.8's produce-before-commit), so the
    /// offset cannot be committed ahead of its durable shadow output. (PR 1.7 marked at route time;
    /// that was an explicit placeholder.) This is distinct from
    /// [`CohortStreamEvent::source_partition`]/[`source_offset`](CohortStreamEvent::source_offset),
    /// the upstream coordinates that anchor per-key replay idempotence inside Stage 1.
    ///
    /// Kept inline (unboxed) on purpose: events are the hot, overwhelmingly common variant, so the
    /// payload lives directly in the enum to avoid a heap allocation per event on the routing path
    /// and to keep each `Vec<ShuffleMessage>` slot contiguous (one buffer, no pointer-chase). The
    /// idiom is to box the *large, rare* variants — not the common one — so when the future
    /// merge/transfer variants land, each boxes its own payload to keep `size_of::<ShuffleMessage>`
    /// from inflating for every queued event. `clippy::large_enum_variant` will flag exactly which
    /// variant to box once there is more than one.
    Event {
        event: CohortStreamEvent,
        cse_offset: i64,
    },
}

#[cfg(test)]
mod tests {
    use super::*;

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
        }
    }

    #[test]
    fn event_variant_carries_event_and_cse_offset() {
        let message = ShuffleMessage::Event {
            event: sample_event(42),
            cse_offset: 7,
        };

        // Exhaustive match (no wildcard) so adding a variant later forces this test to be revisited.
        match message {
            ShuffleMessage::Event { event, cse_offset } => {
                // The upstream source coordinates and the topic offset are independent values.
                assert_eq!(event.source_offset, 42);
                assert_eq!(event.source_partition, 3);
                assert_eq!(cse_offset, 7);
            }
        }
    }
}
