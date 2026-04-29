//! Per-partition stash queue for the write-path.
//!
//! During a partition handoff, the coordinator advances the handoff state
//! through a `Freezing` phase before transferring ownership. While a
//! partition is frozen, routers buffer (stash) incoming write requests for
//! that partition here; once the handoff completes the stashed requests are
//! drained FIFO to the new owner.
//!
//! This gives the protocol a clean "no split-brain writes" guarantee without
//! returning errors to callers.

use std::collections::VecDeque;
use std::sync::Arc;
use std::time::Instant;

use dashmap::DashMap;
use personhog_proto::personhog::types::v1::{
    UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};
use tokio::sync::{oneshot, Mutex};
use tonic::Status;

/// Fixed per-request overhead estimate that approximates the bookkeeping
/// cost of holding a request in the queue (struct fields, oneshot
/// channel, etc.). Combined with the variable payload size below, this
/// approximation is intentionally rough — the goal is a memory bound,
/// not exact accounting. This is an implementation detail of the size
/// approximation, not a user-tunable knob.
const PER_REQUEST_OVERHEAD: usize = 64;

/// Why the stash rejected a request. Used for metric labelling.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RejectCause {
    MaxMessages,
    MaxBytes,
}

impl RejectCause {
    fn label(self) -> &'static str {
        match self {
            RejectCause::MaxMessages => "max_messages",
            RejectCause::MaxBytes => "max_bytes",
        }
    }
}

/// Approximate the memory footprint of a stashed request. Used to
/// enforce the byte-based stash bound. Sums the variable-size fields
/// plus a fixed overhead estimate; doesn't attempt exact proto-encoded
/// sizing because we only need an order-of-magnitude bound, and
/// approximate counting is cheaper.
fn approximate_size(req: &UpdatePersonPropertiesRequest) -> usize {
    PER_REQUEST_OVERHEAD
        + req.event_name.len()
        + req.set_properties.len()
        + req.set_once_properties.len()
        + req.unset_properties.iter().map(|s| s.len()).sum::<usize>()
}

/// A request held in the stash along with the channel used to deliver its
/// response back to the original caller.
pub struct StashedRequest {
    pub request: UpdatePersonPropertiesRequest,
    pub client_name: Option<String>,
    pub reply: oneshot::Sender<Result<UpdatePersonPropertiesResponse, Status>>,
    /// Wall-clock time the request was enqueued. Used to record stash-wait
    /// histograms when drain forwards the request, giving operators
    /// visibility into how long callers spent parked during a handoff.
    pub enqueued_at: Instant,
}

/// Inner queue plus running byte total. Tracked together so the byte
/// count stays consistent with the queue contents.
struct StashQueue {
    requests: VecDeque<StashedRequest>,
    bytes: usize,
}

impl StashQueue {
    fn new() -> Self {
        Self {
            requests: VecDeque::new(),
            bytes: 0,
        }
    }
}

struct PartitionStash {
    max_messages: usize,
    max_bytes: usize,
    /// `Some(queue)` while frozen; `None` in the open (normal) state.
    queue: Mutex<Option<StashQueue>>,
}

impl PartitionStash {
    fn new(max_messages: usize, max_bytes: usize) -> Self {
        Self {
            max_messages,
            max_bytes,
            queue: Mutex::new(None),
        }
    }
}

/// Outcome of an `enqueue_or_forward` call. `Forward` means "not frozen,
/// route normally"; `Stashed` means the request has been enqueued and the
/// caller should await the receiver for its reply; `Rejected` means the
/// stash is full (either too many messages or too many bytes).
pub enum StashDecision {
    Forward,
    Stashed(oneshot::Receiver<Result<UpdatePersonPropertiesResponse, Status>>),
    Rejected,
}

/// Shared stash table. Cheap to clone (holds an `Arc`).
#[derive(Clone)]
pub struct StashTable {
    inner: Arc<DashMap<u32, Arc<PartitionStash>>>,
    max_messages: usize,
    max_bytes: usize,
}

impl StashTable {
    pub fn with_bounds(max_messages: usize, max_bytes: usize) -> Self {
        Self {
            inner: Arc::new(DashMap::new()),
            max_messages,
            max_bytes,
        }
    }

    fn get_or_create(&self, partition: u32) -> Arc<PartitionStash> {
        self.inner
            .entry(partition)
            .or_insert_with(|| Arc::new(PartitionStash::new(self.max_messages, self.max_bytes)))
            .clone()
    }

    /// Begin buffering requests for `partition`. Idempotent: safe to call
    /// multiple times (watch reconnects etc.).
    pub async fn begin_stash(&self, partition: u32) {
        let stash = self.get_or_create(partition);
        let mut guard = stash.queue.lock().await;
        if guard.is_none() {
            *guard = Some(StashQueue::new());
        }
    }

    /// Enqueue a request if the partition is frozen; otherwise return
    /// `Forward` to signal the caller should route normally.
    pub async fn enqueue_or_forward(
        &self,
        partition: u32,
        request: UpdatePersonPropertiesRequest,
        client_name: Option<String>,
    ) -> StashDecision {
        let stash = match self.inner.get(&partition) {
            Some(entry) => Arc::clone(entry.value()),
            None => return StashDecision::Forward,
        };
        let mut guard = stash.queue.lock().await;
        // `None` here means a concurrent `drain` already took this stash's
        // queue and removed the dashmap entry. We arrived holding an Arc to
        // the orphaned PartitionStash. Returning Forward routes via the
        // normal path; the partition is no longer stashing.
        let Some(queue) = guard.as_mut() else {
            return StashDecision::Forward;
        };

        let request_size = approximate_size(&request);

        if queue.requests.len() >= stash.max_messages {
            metrics::counter!(
                "personhog_router_stash_rejected_total",
                "cause" => RejectCause::MaxMessages.label()
            )
            .increment(1);
            return StashDecision::Rejected;
        }
        if queue.bytes.saturating_add(request_size) > stash.max_bytes {
            metrics::counter!(
                "personhog_router_stash_rejected_total",
                "cause" => RejectCause::MaxBytes.label()
            )
            .increment(1);
            return StashDecision::Rejected;
        }

        let (tx, rx) = oneshot::channel();
        queue.requests.push_back(StashedRequest {
            request,
            client_name,
            reply: tx,
            enqueued_at: Instant::now(),
        });
        queue.bytes += request_size;
        metrics::counter!("personhog_router_stash_enqueued_total").increment(1);
        StashDecision::Stashed(rx)
    }

    /// Take the stashed queue and unstash (remove the entry).
    /// Returns the requests in FIFO order; the caller forwards them to the
    /// new owner and sends each result back through its reply channel.
    ///
    /// The dashmap entry is removed so subsequent calls to
    /// `enqueue_or_forward` for this partition skip the lock-and-check
    /// path and short-circuit on `dashmap.get` returning `None`. The
    /// per-entry queue state is also reset to `None` before removal so
    /// any in-flight `enqueue_or_forward` that already acquired the
    /// `Arc<PartitionStash>` will observe the state change and return
    /// `Forward` rather than pushing into a dead queue.
    pub async fn drain(&self, partition: u32) -> VecDeque<StashedRequest> {
        let stash = match self.inner.get(&partition) {
            Some(entry) => Arc::clone(entry.value()),
            None => return VecDeque::new(),
        };
        let queue = {
            let mut guard = stash.queue.lock().await;
            guard.take().map(|q| q.requests).unwrap_or_default()
        };
        self.inner.remove(&partition);
        queue
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mk_request(team_id: i64, person_id: i64) -> UpdatePersonPropertiesRequest {
        UpdatePersonPropertiesRequest {
            team_id,
            person_id,
            partition: 0,
            event_name: "test".to_string(),
            set_properties: Vec::new(),
            set_once_properties: Vec::new(),
            unset_properties: Vec::new(),
        }
    }

    fn mk_request_with_payload(
        person_id: i64,
        payload_size: usize,
    ) -> UpdatePersonPropertiesRequest {
        UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id,
            partition: 0,
            event_name: "test".to_string(),
            set_properties: vec![0u8; payload_size],
            set_once_properties: Vec::new(),
            unset_properties: Vec::new(),
        }
    }

    #[tokio::test]
    async fn forward_when_not_frozen() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        match table.enqueue_or_forward(0, mk_request(1, 1), None).await {
            StashDecision::Forward => {}
            _ => panic!("expected Forward"),
        }
    }

    #[tokio::test]
    async fn begin_then_enqueue_then_drain_preserves_fifo() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;

        let _rx1 = match table.enqueue_or_forward(0, mk_request(1, 1), None).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        let _rx2 = match table.enqueue_or_forward(0, mk_request(1, 2), None).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        let queue = table.drain(0).await;
        assert_eq!(queue.len(), 2);
        let ids: Vec<i64> = queue.iter().map(|s| s.request.person_id).collect();
        assert_eq!(ids, vec![1, 2]);

        // After drain, new requests forward.
        match table.enqueue_or_forward(0, mk_request(1, 3), None).await {
            StashDecision::Forward => {}
            _ => panic!("expected Forward after drain"),
        }
    }

    /// Drain must remove the dashmap entry so subsequent steady-state
    /// requests for that partition can short-circuit on `dashmap.get`
    /// returning `None`, avoiding the per-request Mutex lock that
    /// `enqueue_or_forward` would otherwise take.
    #[tokio::test]
    async fn drain_removes_dashmap_entry() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;
        assert!(
            table.inner.contains_key(&0),
            "begin_stash must populate the entry"
        );
        drop(table.drain(0).await);
        assert!(
            !table.inner.contains_key(&0),
            "drain must remove the entry so future requests skip the lock path"
        );
    }

    /// Back-to-back handoffs: drain → begin_stash for the same partition
    /// must produce a fresh empty queue, not preserve stale state.
    #[tokio::test]
    async fn drain_then_begin_stash_starts_fresh() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;
        let _rx = match table.enqueue_or_forward(0, mk_request(1, 1), None).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        let drained = table.drain(0).await;
        assert_eq!(drained.len(), 1);

        // New handoff begins
        table.begin_stash(0).await;
        // Fresh queue; brand-new requests stash, not forward
        match table.enqueue_or_forward(0, mk_request(1, 2), None).await {
            StashDecision::Stashed(_) => {}
            _ => panic!("expected Stashed for fresh handoff"),
        }
    }

    #[tokio::test]
    async fn reject_when_message_count_exceeds_max() {
        let table = StashTable::with_bounds(2, usize::MAX);
        table.begin_stash(0).await;

        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 1), None).await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 2), None).await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 3), None).await,
            StashDecision::Rejected
        ));
    }

    #[tokio::test]
    async fn reject_when_byte_total_exceeds_max() {
        // Cap at ~5KB; each request below has ~2KB payload. After two
        // requests we're near 4KB; a third request would push over the cap.
        let table = StashTable::with_bounds(usize::MAX, 5 * 1024);
        table.begin_stash(0).await;

        assert!(matches!(
            table
                .enqueue_or_forward(0, mk_request_with_payload(1, 2 * 1024), None)
                .await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            table
                .enqueue_or_forward(0, mk_request_with_payload(2, 2 * 1024), None)
                .await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            table
                .enqueue_or_forward(0, mk_request_with_payload(3, 2 * 1024), None)
                .await,
            StashDecision::Rejected
        ));
    }

    /// Either bound triggers rejection — whichever is hit first.
    #[tokio::test]
    async fn message_count_takes_precedence_when_hit_first() {
        // Generous byte budget but tight message budget.
        let table = StashTable::with_bounds(1, 100 * 1024 * 1024);
        table.begin_stash(0).await;

        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 1), None).await,
            StashDecision::Stashed(_)
        ));
        // Second message rejected on count even though bytes are nowhere near.
        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 2), None).await,
            StashDecision::Rejected
        ));
    }

    #[tokio::test]
    async fn partitions_are_independent() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;

        // p0 stashes, p1 forwards
        assert!(matches!(
            table.enqueue_or_forward(0, mk_request(1, 1), None).await,
            StashDecision::Stashed(_)
        ));
        assert!(matches!(
            table.enqueue_or_forward(1, mk_request(1, 1), None).await,
            StashDecision::Forward
        ));
    }

    /// Race between concurrent enqueue and drain. The `Arc<PartitionStash>`
    /// + `Option<StashQueue>` design exists so that an enqueue that has
    /// already cloned the Arc when drain runs sees `None` after drain
    /// takes the queue, and returns `Forward` rather than pushing into a
    /// dead queue. With many iterations this drives the race window
    /// repeatedly; the invariant is that every request must end up either
    /// in the drained batch or forwarded — never lost, never duplicated.
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn enqueue_and_drain_race() {
        for iteration in 0..200 {
            let table = StashTable::with_bounds(usize::MAX, usize::MAX);
            table.begin_stash(0).await;

            const ENQUEUERS: usize = 8;
            let mut handles = Vec::with_capacity(ENQUEUERS);
            for i in 0..ENQUEUERS {
                let table = table.clone();
                handles.push(tokio::spawn(async move {
                    table
                        .enqueue_or_forward(0, mk_request(1, i as i64), None)
                        .await
                }));
            }

            // Race the drain against the in-flight enqueues.
            let drain_table = table.clone();
            let drain_handle = tokio::spawn(async move { drain_table.drain(0).await });

            let drained = drain_handle.await.unwrap();
            let mut stashed_count = 0usize;
            let mut forwarded_count = 0usize;
            for h in handles {
                match h.await.unwrap() {
                    StashDecision::Stashed(_) => stashed_count += 1,
                    StashDecision::Forward => forwarded_count += 1,
                    StashDecision::Rejected => {
                        panic!("unexpected Rejected on iteration {iteration}")
                    }
                }
            }

            assert_eq!(
                drained.len() + forwarded_count,
                ENQUEUERS,
                "every request must be either drained or forwarded (iteration {iteration})"
            );
            // Stashed count must equal what drain actually took — anything
            // still in the queue at drain time should be drained.
            assert_eq!(
                drained.len(),
                stashed_count,
                "drained batch size must equal stashed count (iteration {iteration})"
            );
        }
    }

    /// When a stashed request's drain handler delivers a result via the
    /// reply channel, the original caller (waiting on the receiver) must
    /// see it. This exercises the contract the `RouterStashHandler` drain
    /// path relies on.
    #[tokio::test]
    async fn drained_request_reply_round_trips() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;

        let rx = match table.enqueue_or_forward(0, mk_request(1, 1), None).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };

        let mut drained = table.drain(0).await;
        let req = drained.pop_front().unwrap();
        let response = UpdatePersonPropertiesResponse {
            person: None,
            updated: true,
        };
        req.reply
            .send(Ok(response.clone()))
            .expect("send must succeed when receiver is alive");

        let received = rx.await.expect("receiver must observe sender");
        assert_eq!(received.unwrap(), response);
    }

    /// If the original caller dropped its receiver (e.g. the gRPC client
    /// disconnected) before drain delivered the reply, the `send` must
    /// return `Err`. The drain handler relies on this signal to bump the
    /// `personhog_router_stash_dropped_total` counter.
    #[tokio::test]
    async fn dropped_receiver_makes_send_fail() {
        let table = StashTable::with_bounds(usize::MAX, usize::MAX);
        table.begin_stash(0).await;

        let rx = match table.enqueue_or_forward(0, mk_request(1, 1), None).await {
            StashDecision::Stashed(rx) => rx,
            _ => panic!("expected Stashed"),
        };
        drop(rx);

        let mut drained = table.drain(0).await;
        let req = drained.pop_front().unwrap();
        let response = UpdatePersonPropertiesResponse {
            person: None,
            updated: false,
        };
        assert!(
            req.reply.send(Ok(response)).is_err(),
            "send must return Err after the receiver is dropped"
        );
    }
}
