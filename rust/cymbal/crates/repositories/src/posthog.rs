use std::sync::{
    atomic::{AtomicU64, AtomicUsize, Ordering},
    Arc, Mutex, OnceLock,
};

use cymbal_symbol_store::saving::SymbolSetReporter;
use posthog_rs::{Error, Event};
use tokio::{sync::mpsc, task::JoinHandle};
use tracing::{debug, error, warn};
use uuid::Uuid;

const ISSUE_CREATED: &str = "error_tracking_issue_created";
const ISSUE_REOPENED: &str = "error_tracking_issue_reopened";
const SYMBOL_SET_SAVED: &str = "error_tracking_symbol_set_saved";
const SYMBOL_SET_DELETED: &str = "error_tracking_symbol_set_deleted";
const DEFAULT_CAPTURE_QUEUE_CAPACITY: usize = 10_000;

const CAPTURE_QUEUE_DEPTH: &str = "cymbal_posthog_capture_queue_depth";
const CAPTURE_ENQUEUED_TOTAL: &str = "cymbal_posthog_capture_enqueued_total";
const CAPTURE_DROPS_TOTAL: &str = "cymbal_posthog_capture_drops_total";
const CAPTURE_FAILURES_TOTAL: &str = "cymbal_posthog_capture_failures_total";

static CAPTURE_QUEUE: OnceLock<Mutex<Option<CaptureQueue>>> = OnceLock::new();
static NEXT_CAPTURE_QUEUE_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone)]
struct CaptureQueue {
    id: u64,
    enabled: bool,
    sender: mpsc::Sender<CaptureRequest>,
    depth: Arc<AtomicUsize>,
}

struct CaptureRequest {
    event_name: &'static str,
    event: Event,
}

#[derive(Debug)]
pub struct PostHogCaptureGuard {
    id: u64,
    handle: Option<JoinHandle<()>>,
}

impl PostHogCaptureGuard {
    pub async fn shutdown(mut self) {
        self.unregister();
        if let Some(handle) = self.handle.take() {
            if let Err(error) = handle.await {
                warn!(?error, "PostHog capture consumer task ended unexpectedly");
            }
        }
    }

    fn unregister(&self) {
        let queue = capture_queue_cell();
        let mut guard = queue.lock().unwrap();
        if guard.as_ref().is_some_and(|queue| queue.id == self.id) {
            *guard = None;
            metrics::gauge!(CAPTURE_QUEUE_DEPTH).set(0.0);
        }
    }
}

impl Drop for PostHogCaptureGuard {
    fn drop(&mut self) {
        self.unregister();
    }
}

pub fn init_posthog_capture(enabled: bool) -> PostHogCaptureGuard {
    init_posthog_capture_with_capacity(enabled, DEFAULT_CAPTURE_QUEUE_CAPACITY)
}

pub fn init_posthog_capture_with_capacity(enabled: bool, capacity: usize) -> PostHogCaptureGuard {
    let capacity = capacity.max(1);
    let id = NEXT_CAPTURE_QUEUE_ID.fetch_add(1, Ordering::Relaxed);
    let (sender, receiver) = mpsc::channel(capacity);
    let depth = Arc::new(AtomicUsize::new(0));
    let queue = CaptureQueue {
        id,
        enabled,
        sender,
        depth: depth.clone(),
    };
    let handle = tokio::spawn(capture_consumer(receiver, depth));

    let queue_cell = capture_queue_cell();
    let mut guard = queue_cell.lock().unwrap();
    *guard = Some(queue);
    metrics::gauge!(CAPTURE_QUEUE_DEPTH).set(0.0);

    PostHogCaptureGuard {
        id,
        handle: Some(handle),
    }
}

pub fn capture_issue_created(team_id: i32, issue_id: Uuid, sentry_integration: bool) {
    let mut event = Event::new_anon(ISSUE_CREATED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("issue_id", issue_id.to_string()).unwrap();
    event
        .insert_prop("sentry_integration", sentry_integration)
        .unwrap();
    enqueue_capture(ISSUE_CREATED, event);
}

pub fn capture_issue_reopened(team_id: i32, issue_id: Uuid) {
    let mut event = Event::new_anon(ISSUE_REOPENED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("issue_id", issue_id.to_string()).unwrap();
    enqueue_capture(ISSUE_REOPENED, event);
}

pub fn capture_symbol_set_saved(team_id: i32, set_ref: &str, storage_ptr: &str, was_retry: bool) {
    let mut event = Event::new_anon(SYMBOL_SET_SAVED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("set_ref", set_ref).unwrap();
    event.insert_prop("storage_ptr", storage_ptr).unwrap();
    event.insert_prop("was_retry", was_retry).unwrap();
    enqueue_capture(SYMBOL_SET_SAVED, event);
}

pub fn capture_symbol_set_deleted(team_id: i32, set_ref: &str, storage_ptr: Option<&str>) {
    let mut event = Event::new_anon(SYMBOL_SET_DELETED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("set_ref", set_ref).unwrap();
    if let Some(ptr) = storage_ptr {
        event.insert_prop("storage_ptr", ptr).unwrap();
    }
    enqueue_capture(SYMBOL_SET_DELETED, event);
}

pub struct PostHogSymbolSetReporter;

impl SymbolSetReporter for PostHogSymbolSetReporter {
    fn symbol_set_saved(&self, team_id: i32, set_ref: &str, storage_ptr: &str, was_retry: bool) {
        capture_symbol_set_saved(team_id, set_ref, storage_ptr, was_retry);
    }

    fn symbol_set_deleted(&self, team_id: i32, set_ref: &str, storage_ptr: Option<&str>) {
        capture_symbol_set_deleted(team_id, set_ref, storage_ptr);
    }
}

fn enqueue_capture(event_name: &'static str, event: Event) {
    let Some(queue) = capture_queue_cell().lock().unwrap().clone() else {
        metrics::counter!(CAPTURE_DROPS_TOTAL, "event" => event_name, "reason" => "not_initialized")
            .increment(1);
        debug!(
            event = event_name,
            "PostHog capture dropped because capture queue is not initialized"
        );
        return;
    };

    if !queue.enabled {
        metrics::counter!(CAPTURE_DROPS_TOTAL, "event" => event_name, "reason" => "capture_disabled")
            .increment(1);
        debug!(
            event = event_name,
            "PostHog capture skipped because capture is disabled"
        );
        return;
    }

    let new_depth = queue.depth.fetch_add(1, Ordering::Relaxed) + 1;
    match queue.sender.try_send(CaptureRequest { event_name, event }) {
        Ok(()) => {
            metrics::gauge!(CAPTURE_QUEUE_DEPTH).set(new_depth as f64);
            metrics::counter!(CAPTURE_ENQUEUED_TOTAL, "event" => event_name).increment(1);
        }
        Err(mpsc::error::TrySendError::Full(_)) => {
            decrement_capture_depth(&queue.depth);
            metrics::counter!(CAPTURE_DROPS_TOTAL, "event" => event_name, "reason" => "queue_full")
                .increment(1);
            warn!(
                event = event_name,
                "PostHog capture queue is full; dropping newest event"
            );
        }
        Err(mpsc::error::TrySendError::Closed(_)) => {
            decrement_capture_depth(&queue.depth);
            metrics::counter!(CAPTURE_DROPS_TOTAL, "event" => event_name, "reason" => "queue_closed")
                .increment(1);
            debug!(
                event = event_name,
                "PostHog capture queue is closed; dropping event"
            );
        }
    }
}

async fn capture_consumer(mut receiver: mpsc::Receiver<CaptureRequest>, depth: Arc<AtomicUsize>) {
    while let Some(request) = receiver.recv().await {
        decrement_capture_depth(&depth);

        if let Err(error) = posthog_rs::capture(request.event).await {
            match error {
                Error::NotInitialized => {
                    debug!(
                        event = request.event_name,
                        "PostHog capture skipped because client is disabled"
                    )
                }
                other => {
                    metrics::counter!(CAPTURE_FAILURES_TOTAL, "event" => request.event_name)
                        .increment(1);
                    error!(event = request.event_name, error = ?other, "PostHog capture failed");
                }
            }
        }
    }
}

fn decrement_capture_depth(depth: &AtomicUsize) {
    let new_depth = depth
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
            Some(current.saturating_sub(1))
        })
        .unwrap_or(0)
        .saturating_sub(1);
    metrics::gauge!(CAPTURE_QUEUE_DEPTH).set(new_depth as f64);
}

fn capture_queue_cell() -> &'static Mutex<Option<CaptureQueue>> {
    CAPTURE_QUEUE.get_or_init(|| Mutex::new(None))
}

/// Returns the current in-flight depth reported by the active capture queue.
/// Zero when no queue is initialized.
#[cfg(test)]
pub(crate) fn test_queue_depth() -> usize {
    capture_queue_cell()
        .lock()
        .unwrap()
        .as_ref()
        .map_or(0, |q| q.depth.load(Ordering::Relaxed))
}

/// Returns `true` when a capture queue is currently installed (enabled or not).
#[cfg(test)]
pub(crate) fn test_queue_is_active() -> bool {
    capture_queue_cell().lock().unwrap().is_some()
}

/// Forcibly removes the current capture queue without waiting for a consumer task to drain.
/// Use only from tests to establish a known "not-initialized" baseline.
#[cfg(test)]
pub(crate) fn test_clear_queue() {
    *capture_queue_cell().lock().unwrap() = None;
}

#[cfg(test)]
mod tests {
    use std::sync::OnceLock;

    use uuid::Uuid;

    use super::*;

    // Serializes all tests that touch global capture-queue state.  These tests mutate a
    // process-wide singleton so they cannot run concurrently.
    fn capture_lock() -> std::sync::MutexGuard<'static, ()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(())).lock().unwrap()
    }

    #[tokio::test(flavor = "current_thread")]
    async fn not_initialized_drops_event_without_panic() {
        let _lock = capture_lock();
        test_clear_queue();

        // Must not panic even when no queue is installed.
        capture_issue_created(1, Uuid::nil(), false);
        capture_issue_reopened(2, Uuid::nil());

        assert!(!test_queue_is_active());
    }

    #[tokio::test(flavor = "current_thread")]
    async fn disabled_queue_drops_event_without_depth_change() {
        let _lock = capture_lock();

        let _guard = init_posthog_capture_with_capacity(false, 100);

        let depth_before = test_queue_depth();
        capture_issue_created(1, Uuid::nil(), false);
        let depth_after = test_queue_depth();

        assert_eq!(
            depth_before, depth_after,
            "disabled queue must not increment depth"
        );
    }

    #[tokio::test(flavor = "current_thread")]
    async fn enabled_queue_increments_depth_on_enqueue() {
        let _lock = capture_lock();

        // large capacity so the queue never fills
        let _guard = init_posthog_capture_with_capacity(true, 1_000);

        assert_eq!(test_queue_depth(), 0, "depth must start at zero");
        capture_issue_created(42, Uuid::nil(), false);

        // current_thread flavor: the consumer task cannot run until we yield,
        // so the depth counter reflects the enqueued (but not yet consumed) event.
        assert_eq!(test_queue_depth(), 1, "depth must be 1 after one enqueue");
    }

    #[tokio::test(flavor = "current_thread")]
    async fn full_queue_does_not_overflow_depth() {
        let _lock = capture_lock();

        // capacity=1: the first event fills the buffer; the second is dropped.
        let _guard = init_posthog_capture_with_capacity(true, 1);

        capture_issue_created(1, Uuid::nil(), false); // enqueued
        let depth_after_first = test_queue_depth();
        capture_issue_created(2, Uuid::nil(), false); // dropped (queue full)
        let depth_after_second = test_queue_depth();

        assert_eq!(depth_after_first, 1);
        assert_eq!(
            depth_after_second, 1,
            "depth must not increase when event is dropped due to full queue"
        );
    }

    // The MutexGuard is held across the .await intentionally: current_thread runtime
    // means the consumer task cannot run until we yield, so the guard never causes
    // actual lock contention.  Suppress the lint rather than rewrite the serialisation
    // strategy.
    #[allow(clippy::await_holding_lock)]
    #[tokio::test(flavor = "current_thread")]
    async fn shutdown_completes_without_hanging() {
        let _lock = capture_lock();

        let guard = init_posthog_capture_with_capacity(true, 10);
        capture_issue_created(1, Uuid::nil(), false);

        // Shutdown drains the consumer task and clears the queue.
        guard.shutdown().await;

        assert!(
            !test_queue_is_active(),
            "queue must be cleared after shutdown"
        );
    }

    #[tokio::test(flavor = "current_thread")]
    async fn symbol_set_reporter_enqueues_saved_and_deleted_events() {
        let _lock = capture_lock();

        let _guard = init_posthog_capture_with_capacity(true, 100);
        let reporter = PostHogSymbolSetReporter;

        reporter.symbol_set_saved(5, "ref-1", "ptr-1", false);
        let after_saved = test_queue_depth();

        reporter.symbol_set_deleted(5, "ref-1", Some("ptr-1"));
        let after_deleted = test_queue_depth();

        assert_eq!(after_saved, 1);
        assert_eq!(after_deleted, 2);
    }

    #[tokio::test(flavor = "current_thread")]
    async fn symbol_set_reporter_deleted_without_ptr_enqueues_event() {
        let _lock = capture_lock();

        let _guard = init_posthog_capture_with_capacity(true, 100);
        let reporter = PostHogSymbolSetReporter;

        reporter.symbol_set_deleted(5, "ref-no-ptr", None);

        assert_eq!(
            test_queue_depth(),
            1,
            "deleted-without-ptr event must still be enqueued"
        );
    }
}
