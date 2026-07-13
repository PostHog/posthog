//! App-side intake backpressure: a per-partition ceiling on **events** resident in a worker's
//! channel. The mpsc slots bound sub-batches; this bounds the events inside them. Over the cap, new
//! events are refused (→ held → paused), never buffered.
//!
//! The counter cannot drift: [`PartitionIntake::try_admit`] reserves a batch's events (only the
//! consume loop admits), [`MeteredReceiver`] releases them on the next `recv` and on `Drop`, and the
//! router releases eagerly when an admitted batch fails to enter the channel. Both sides count events
//! only, so maintenance ticks reserve and release 0.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use metrics::gauge;
use tokio::sync::mpsc;

use super::shuffle_message::ShuffleMessage;
use crate::observability::metrics::PARTITION_INTAKE_EVENTS;

/// Event-carrying messages in a batch. Maintenance ticks carry no offset and count 0.
pub fn count_events(batch: &[ShuffleMessage]) -> usize {
    batch
        .iter()
        .filter(|message| message.event_offset().is_some())
        .count()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Admission {
    /// Reserved under the cap; the caller must send the batch or release the reservation.
    Admitted,
    /// At the event ceiling; the caller holds the batch and pauses the partition.
    Rejected,
}

/// Per-partition ceiling on un-drained events.
///
/// Releases (from the worker's [`MeteredReceiver`] and, on a failed send, the router) only ever lower
/// the count, so [`try_admit`](Self::try_admit)'s plain load-then-add never overshoots `cap`: a
/// concurrent release between its load and its add can only have freed room.
pub struct PartitionIntake {
    cap: usize,
    in_flight_events: AtomicUsize,
    partition_label: Arc<str>,
}

impl PartitionIntake {
    pub fn new(partition: i32, cap: usize) -> Self {
        Self {
            cap,
            in_flight_events: AtomicUsize::new(0),
            partition_label: Arc::from(partition.to_string()),
        }
    }

    /// Reserve `count` events if they fit under `cap`. An idle partition always admits — even an
    /// over-cap batch — so `cap` is a soft ceiling on the steady state, not a hard per-batch limit.
    ///
    /// Not a CAS: correct only because a single task (the consume loop) admits for a given partition.
    /// Two concurrent admitters could both pass the check and overshoot `cap`.
    pub fn try_admit(&self, count: usize) -> Admission {
        let current = self.in_flight_events.load(Ordering::Acquire);
        if current == 0 || current + count <= self.cap {
            self.in_flight_events.fetch_add(count, Ordering::AcqRel);
            // Sample fresh: a concurrent release may have lowered the counter below the reserved total.
            self.set_gauge(self.in_flight_events.load(Ordering::Acquire));
            Admission::Admitted
        } else {
            Admission::Rejected
        }
    }

    /// Release a reservation once its events drain (or fail to land). Saturating, so an accounting
    /// slip can't underflow into a permanent stall.
    pub fn release(&self, count: usize) {
        if count == 0 {
            return;
        }
        let mut current = self.in_flight_events.load(Ordering::Acquire);
        loop {
            let next = current.saturating_sub(count);
            match self.in_flight_events.compare_exchange_weak(
                current,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    self.set_gauge(next);
                    return;
                }
                Err(observed) => current = observed,
            }
        }
    }

    pub fn in_flight(&self) -> usize {
        self.in_flight_events.load(Ordering::Acquire)
    }

    fn set_gauge(&self, value: usize) {
        gauge!(PARTITION_INTAKE_EVENTS, "partition" => self.partition_label.clone())
            .set(value as f64);
    }
}

/// Worker-side receiver that releases each batch's event reservation back to the partition's
/// [`PartitionIntake`]. Releases on the *next* `recv` and on `Drop`, so the budget also covers the
/// batch the worker currently holds.
pub struct MeteredReceiver {
    receiver: mpsc::Receiver<Vec<ShuffleMessage>>,
    intake: Arc<PartitionIntake>,
    /// Events reserved for the last batch handed out, released on the next `recv`/`Drop`.
    outstanding: usize,
}

impl MeteredReceiver {
    pub fn new(
        receiver: mpsc::Receiver<Vec<ShuffleMessage>>,
        intake: Arc<PartitionIntake>,
    ) -> Self {
        Self {
            receiver,
            intake,
            outstanding: 0,
        }
    }

    /// Uncapped intake wrapper for tests: only the mpsc slots bound.
    pub fn unmetered(receiver: mpsc::Receiver<Vec<ShuffleMessage>>) -> Self {
        Self::new(receiver, Arc::new(PartitionIntake::new(0, usize::MAX)))
    }

    /// Release the previous batch, then await the next.
    pub async fn recv(&mut self) -> Option<Vec<ShuffleMessage>> {
        self.release_outstanding();
        let batch = self.receiver.recv().await?;
        self.outstanding = count_events(&batch);
        Some(batch)
    }

    fn release_outstanding(&mut self) {
        if self.outstanding > 0 {
            self.intake.release(self.outstanding);
            self.outstanding = 0;
        }
    }

    /// Non-awaiting drain for tests; releases like [`recv`](Self::recv).
    #[cfg(test)]
    pub fn try_recv(&mut self) -> Result<Vec<ShuffleMessage>, mpsc::error::TryRecvError> {
        self.release_outstanding();
        let batch = self.receiver.try_recv()?;
        self.outstanding = count_events(&batch);
        Ok(batch)
    }
}

impl Drop for MeteredReceiver {
    fn drop(&mut self) {
        self.release_outstanding();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::consumers::events::CohortStreamEvent;

    fn event() -> ShuffleMessage {
        ShuffleMessage::Event {
            event: Box::new(CohortStreamEvent {
                team_id: 1,
                person_id: "p".to_string(),
                distinct_id: "d".to_string(),
                uuid: "u".to_string(),
                event: "$pageview".to_string(),
                timestamp: "2026-05-26 12:34:56.789000".to_string(),
                properties: None,
                person_properties: None,
                elements_chain: None,
                source_offset: 0,
                source_partition: 0,
                redirected_from: None,
                redirect_hops: 0,
            }),
            cse_offset: 0,
        }
    }

    fn events(n: usize) -> Vec<ShuffleMessage> {
        (0..n).map(|_| event()).collect()
    }

    #[test]
    fn count_events_ignores_maintenance_messages() {
        let batch = vec![
            event(),
            ShuffleMessage::Sweep { due_before_ms: 1 },
            event(),
            ShuffleMessage::RedrivePendingTransfers,
        ];
        assert_eq!(count_events(&batch), 2);
    }

    #[test]
    fn admits_under_cap_and_rejects_over_cap() {
        let intake = PartitionIntake::new(0, 10);
        assert_eq!(intake.try_admit(6), Admission::Admitted);
        assert_eq!(intake.in_flight(), 6);
        assert_eq!(intake.try_admit(5), Admission::Rejected);
        assert_eq!(intake.in_flight(), 6);
        assert_eq!(intake.try_admit(4), Admission::Admitted);
        assert_eq!(intake.in_flight(), 10);
    }

    #[test]
    fn an_idle_partition_admits_an_over_cap_batch_for_progress() {
        let intake = PartitionIntake::new(0, 10);
        assert_eq!(intake.try_admit(25), Admission::Admitted);
        assert_eq!(intake.in_flight(), 25);
        assert_eq!(intake.try_admit(1), Admission::Rejected);
    }

    #[test]
    fn release_is_saturating() {
        let intake = PartitionIntake::new(0, 10);
        intake.try_admit(3);
        intake.release(10);
        assert_eq!(intake.in_flight(), 0);
    }

    #[tokio::test]
    async fn metered_receiver_releases_the_previous_batch_on_the_next_recv() {
        let intake = Arc::new(PartitionIntake::new(0, 100));
        let (tx, rx) = mpsc::channel(8);
        let mut rx = MeteredReceiver::new(rx, intake.clone());

        assert_eq!(intake.try_admit(3), Admission::Admitted);
        tx.send(events(3)).await.unwrap();
        assert_eq!(intake.try_admit(2), Admission::Admitted);
        tx.send(events(2)).await.unwrap();
        assert_eq!(intake.in_flight(), 5);

        assert_eq!(count_events(&rx.recv().await.unwrap()), 3);
        assert_eq!(intake.in_flight(), 5, "the in-hand batch stays counted");

        assert_eq!(count_events(&rx.recv().await.unwrap()), 2);
        assert_eq!(intake.in_flight(), 2, "recv released the previous batch");

        drop(rx);
        assert_eq!(
            intake.in_flight(),
            0,
            "drop releases the last in-hand batch"
        );
    }

    #[tokio::test]
    async fn a_maintenance_batch_does_not_move_the_counter() {
        let intake = Arc::new(PartitionIntake::new(0, 100));
        let (tx, rx) = mpsc::channel(8);
        let mut rx = MeteredReceiver::new(rx, intake.clone());

        tx.send(vec![ShuffleMessage::Sweep { due_before_ms: 1 }])
            .await
            .unwrap();
        rx.recv().await.unwrap();
        drop(rx);
        assert_eq!(intake.in_flight(), 0);
    }
}
