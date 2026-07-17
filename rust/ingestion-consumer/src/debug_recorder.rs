//! In-memory event recorder powering the real-time debug API (consumed by the
//! ingestion control plane UI).
//!
//! When `DEBUG_API_ENABLED` is set, an `Arc<DebugRecorder>` is injected into
//! the dispatcher, consumer, transport, and worker registry. Each records a
//! structured [`DebugEvent`] at the same points it already emits metrics —
//! batch assignment, sub-batch resolution, deferral/flush, retries, worker
//! health transitions. The recorder keeps a bounded rolling window of recent
//! events (for a client connecting mid-stream to see history) and broadcasts
//! every new event to live subscribers (the SSE feed at `/debug/events`).
//!
//! It is a pure observer: it never influences routing. When the feature is off,
//! the recorder is `None` everywhere and nothing is constructed or recorded.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::Serialize;
use tokio::sync::broadcast;

/// One worker's slice of an assigned (or flushed) batch.
#[derive(Clone, Serialize)]
pub struct SubBatchInfo {
    pub worker: String,
    pub messages: usize,
    pub distinct_ids: usize,
}

/// A topic-partition and the batch's max offset there, with observed lag.
#[derive(Clone, Serialize)]
pub struct PartitionOffset {
    pub topic: String,
    pub partition: i32,
    pub offset: i64,
    pub lag_ms: i64,
}

/// The distinct event kinds recorded across the consumer's lifecycle. Serialized
/// with an internal `type` tag so the UI can switch on it.
#[derive(Clone, Serialize)]
#[serde(tag = "type")]
pub enum DebugEventKind {
    /// Consumer loop started — doubles as a restart marker (the buffer is empty
    /// after a process restart, and this is the first event the UI sees).
    ConsumerStarted {
        group_id: String,
        workers: Vec<String>,
    },
    /// A Kafka batch was collected and handed to a processing task.
    BatchDispatched {
        batch_id: String,
        messages: usize,
        partitions: Vec<PartitionOffset>,
    },
    /// The dispatcher grouped a batch by routing key and assigned sub-batches.
    BatchAssigned {
        batch_id: String,
        distinct_ids: usize,
        sub_batches: Vec<SubBatchInfo>,
        deferred_groups: u64,
        unroutable_groups: u64,
    },
    /// A sub-batch resolved (ACK), releasing the worker's outstanding load.
    SubBatchResolved {
        worker: String,
        messages: usize,
        distinct_ids: usize,
        cleared_deferral: bool,
    },
    /// Messages were stashed rather than sent (`reason`: drain/unroutable/send_failed).
    Deferred {
        batch_id: String,
        reason: &'static str,
        groups: u64,
    },
    /// Previously-deferred groups were re-routed to healthy workers.
    DeferredFlushed {
        batch_id: String,
        sub_batches: Vec<SubBatchInfo>,
    },
    /// A batch's offsets were committed to Kafka.
    BatchCommitted {
        batch_id: String,
        accepted: u32,
        duration_ms: u64,
        partitions: Vec<PartitionOffset>,
    },
    /// Batch processing failed; the process will exit and restart.
    BatchFailed {
        batch_id: Option<String>,
        error: String,
    },
    /// A send to a worker was retried (`reason`: busy/error).
    SendRetry {
        worker: String,
        batch_id: String,
        attempt: u32,
        reason: &'static str,
    },
    /// A send exhausted its retries; the messages are deferred for replay.
    SendExhausted {
        worker: String,
        batch_id: String,
        messages: usize,
        error: String,
    },
    /// A worker moved between health states.
    WorkerStateChanged {
        worker: String,
        from: &'static str,
        to: &'static str,
    },
    /// A worker joined, drained, or left the pool (`action`: add/drain/remove).
    WorkerMembership {
        worker: String,
        action: &'static str,
    },
}

/// A recorded event with a monotonic sequence number and wall-clock timestamp.
#[derive(Clone, Serialize)]
pub struct DebugEvent {
    pub seq: u64,
    pub ts_ms: u64,
    #[serde(flatten)]
    pub kind: DebugEventKind,
}

// ---- Point-in-time state snapshot (served at /debug/state) ----

/// One worker's health as seen by the registry.
#[derive(Serialize)]
pub struct WorkerHealthSnapshot {
    pub url: String,
    pub state: String,
    pub draining: bool,
    pub consecutive_probe_failures: u32,
    pub passive_error_rate: f64,
    pub passive_samples: usize,
}

/// Per-worker outstanding in-flight load.
#[derive(Serialize)]
pub struct LoadEntry {
    pub worker: String,
    pub in_flight: usize,
}

/// The dispatcher's current load/pin/stash accounting.
#[derive(Serialize)]
pub struct DispatcherLoad {
    pub per_worker: Vec<LoadEntry>,
    pub total_in_flight: usize,
    pub pin_count: usize,
    pub stashed_messages: usize,
    pub stashed_batches: usize,
}

/// Merged worker row: registry health plus the dispatcher's in-flight count.
#[derive(Serialize)]
pub struct WorkerStatus {
    pub url: String,
    pub state: String,
    pub draining: bool,
    pub consecutive_probe_failures: u32,
    pub passive_error_rate: f64,
    pub passive_samples: usize,
    pub in_flight_messages: usize,
}

/// The full snapshot returned by `/debug/state` (workers + load + event backlog).
#[derive(Serialize)]
pub struct DebugState {
    pub group_id: String,
    pub workers: Vec<WorkerStatus>,
    pub dispatcher: DispatcherLoad,
    pub events: Vec<DebugEvent>,
}

/// Lightweight snapshot returned by `/debug/load` — workers + dispatcher load
/// only, no event backlog, so the UI can poll it at a high rate cheaply.
#[derive(Serialize)]
pub struct DebugLoad {
    pub group_id: String,
    pub workers: Vec<WorkerStatus>,
    pub dispatcher: DispatcherLoad,
}

/// Bounded rolling event buffer plus a broadcast channel for live subscribers.
pub struct DebugRecorder {
    buffer: Mutex<VecDeque<DebugEvent>>,
    tx: broadcast::Sender<DebugEvent>,
    seq: AtomicU64,
    max_events: usize,
    window: Duration,
}

impl DebugRecorder {
    /// Create a recorder retaining at most `max_events` within `window`.
    pub fn new(max_events: usize, window: Duration) -> Arc<Self> {
        let (tx, _rx) = broadcast::channel(1024);
        Arc::new(Self {
            buffer: Mutex::new(VecDeque::new()),
            tx,
            seq: AtomicU64::new(0),
            max_events: max_events.max(1),
            window,
        })
    }

    /// Record an event: stamp it, evict anything past the count/time bounds, and
    /// broadcast to live subscribers. Cheap and non-blocking; a slow or absent
    /// subscriber never blocks the caller (broadcast drops for laggards).
    pub fn record(&self, kind: DebugEventKind) {
        let seq = self.seq.fetch_add(1, Ordering::Relaxed);
        let ts_ms = now_ms();
        let event = DebugEvent { seq, ts_ms, kind };

        {
            let mut buf = self.buffer.lock().unwrap();
            buf.push_back(event.clone());
            while buf.len() > self.max_events {
                buf.pop_front();
            }
            let cutoff = ts_ms.saturating_sub(self.window.as_millis() as u64);
            while buf.front().is_some_and(|e| e.ts_ms < cutoff) {
                buf.pop_front();
            }
        }

        // Ignore the error when there are no subscribers — the buffer still holds
        // the event for a client that connects later.
        let _ = self.tx.send(event);
    }

    /// Snapshot of the retained events, oldest first.
    pub fn backlog(&self) -> Vec<DebugEvent> {
        self.buffer.lock().unwrap().iter().cloned().collect()
    }

    /// Subscribe to the live event stream.
    pub fn subscribe(&self) -> broadcast::Receiver<DebugEvent> {
        self.tx.subscribe()
    }
}

/// Record an event iff a recorder is present. Takes a closure so callers pay
/// nothing to build the event payload when the debug UI is disabled.
pub fn record_if(recorder: &Option<Arc<DebugRecorder>>, event: impl FnOnce() -> DebugEventKind) {
    if let Some(recorder) = recorder {
        recorder.record(event());
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[cfg(test)]
mod tests {
    use super::*;

    fn membership(action: &'static str) -> DebugEventKind {
        DebugEventKind::WorkerMembership {
            worker: "http://w:9001".to_string(),
            action,
        }
    }

    #[test]
    fn backlog_is_bounded_by_capacity_and_keeps_newest() {
        let rec = DebugRecorder::new(3, Duration::from_secs(300));
        for _ in 0..5 {
            rec.record(membership("add"));
        }
        let backlog = rec.backlog();
        // Only the 3 most recent survive, in order, and sequence numbers are
        // monotonic — so a client sees a contiguous recent window, not a gap.
        assert_eq!(backlog.len(), 3);
        assert_eq!(
            backlog.iter().map(|e| e.seq).collect::<Vec<_>>(),
            vec![2, 3, 4]
        );
    }

    #[test]
    fn subscribers_receive_events_recorded_after_subscribing() {
        let rec = DebugRecorder::new(10, Duration::from_secs(300));
        let mut rx = rec.subscribe();
        rec.record(membership("drain"));
        let event = rx.try_recv().expect("subscriber should receive the event");
        assert_eq!(event.seq, 0);
        assert!(matches!(
            event.kind,
            DebugEventKind::WorkerMembership {
                action: "drain",
                ..
            }
        ));
    }
}
