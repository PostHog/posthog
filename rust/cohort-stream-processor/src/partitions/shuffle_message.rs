//! The typed unit of work the partition router dispatches to a partition worker.
//!
//! The router never inspects the payload: affinity is supplied alongside the message, since the
//! shuffler's re-key already placed each event on the correct `cohort_stream_events` partition.

use crate::consumers::events::CohortStreamEvent;

/// A unit of work routed to the partition worker that owns its `(team_id, person_id)` key.
#[derive(Debug)]
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

        // No wildcard, so a new variant forces this test to be revisited.
        match message {
            ShuffleMessage::Event { event, cse_offset } => {
                assert_eq!(event.source_offset, 42);
                assert_eq!(event.source_partition, 3);
                assert_eq!(cse_offset, 7);
            }
        }
    }
}
