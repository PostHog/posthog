//! Per-endpoint subscription client for the `cymbal.resolution.v1` load
//! event bus.
//!
//! Each pooled gRPC channel runs a long-lived `Subscribe` stream in the
//! background. The latest [`LoadSnapshot`] is stashed on the endpoint state
//! and consulted by [`super::pool::EndpointPool::select_for_key`] to route
//! the rendezvous-ranked endpoint that is not draining. The
//! subscription is cooperative: stream termination triggers a small
//! backoff (with jitter) and a reconnect, so a transient blip leaves the
//! snapshot cleared and the pool stops routing to that endpoint rather than
//! silently considering it healthy forever.

use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_client::CymbalResolutionClient;
use cymbal_proto::cymbal::resolution::v1::{LoadEvent, SubscribeRequest};
use futures::StreamExt;
use rand::Rng;
use tokio::sync::Notify;
use tokio::task::JoinHandle;
use tonic::transport::Channel;
use tonic::Request;
use tracing::{debug, info, warn};

use crate::metric_consts::REMOTE_RESOLUTION_LOAD_SUBSCRIPTIONS;

use super::client::with_internal_api_secret;

/// Snapshot of an endpoint's server-reported load. Stored in an `Arc<Mutex<…>>`
/// per endpoint and refreshed by the subscription task.
#[derive(Clone, Debug)]
pub struct LoadSnapshot {
    pub draining: bool,
    pub in_flight: u32,
    pub max_in_flight: u32,
    /// Local wall-clock at which this snapshot was received. Used by the pool
    /// to ignore stale snapshots when routing.
    pub observed_at: Instant,
    /// Sequence number from the server. Useful for diagnostics when stream
    /// restarts reset the count.
    pub sequence: u64,
}

impl LoadSnapshot {
    pub fn is_fresh(&self, now: Instant, stale_after: Duration) -> bool {
        now.duration_since(self.observed_at) < stale_after
    }
}

/// Cell holding the latest load snapshot for one endpoint. Wrapped in an
/// `Arc<Mutex<…>>` so the subscription writer and the pool reader can share
/// it cheaply.
pub type LoadCell = Arc<Mutex<Option<LoadSnapshot>>>;

/// Handle returned from [`spawn_subscription`]. Holds the cancellation
/// notifier and the join handle so the pool can stop the task when an
/// endpoint is evicted.
pub struct SubscriptionHandle {
    pub cancel: Arc<Notify>,
    pub join: JoinHandle<()>,
}

impl SubscriptionHandle {
    /// Signal the subscription task to stop. The task will exit at the next
    /// await point — either when receiving an event or when its backoff timer
    /// fires.
    pub fn cancel(&self) {
        self.cancel.notify_waiters();
    }
}

/// Spawn a background task that subscribes to one endpoint's freshness/draining stream
/// and keeps `cell` populated with the latest [`LoadSnapshot`]. The task
/// reconnects automatically on stream end or error, with a fixed backoff so
/// a misbehaving server doesn't spin a hot reconnect loop.
pub fn spawn_subscription(
    addr: SocketAddr,
    channel: Channel,
    cell: LoadCell,
    tick_hint: Duration,
    reconnect_backoff: Duration,
    internal_api_secret: String,
    ready: Arc<Notify>,
) -> SubscriptionHandle {
    let cancel = Arc::new(Notify::new());
    let cancel_clone = cancel.clone();
    let subscriber_id = format!("cymbal/{addr}");

    let join = tokio::spawn(async move {
        let backoff = reconnect_backoff;
        loop {
            let outcome = run_subscription_once(
                channel.clone(),
                cell.clone(),
                tick_hint,
                subscriber_id.clone(),
                cancel_clone.clone(),
                internal_api_secret.clone(),
                ready.clone(),
            )
            .await;
            match outcome {
                SubscriptionExit::Cancelled => {
                    debug!(endpoint = %addr, "load subscription cancelled");
                    return;
                }
                SubscriptionExit::Reconnect(reason) => {
                    metrics::counter!(
                        REMOTE_RESOLUTION_LOAD_SUBSCRIPTIONS,
                        "outcome" => "reconnect",
                    )
                    .increment(1);
                    // Add up to 50% jitter so a fleet of cymbal pods doesn't
                    // synchronize their reconnects after a shared upstream
                    // restart and hammer the server in lockstep.
                    let jittered = backoff + jitter_for(backoff);
                    warn!(
                        endpoint = %addr,
                        reason = %reason,
                        backoff_ms = jittered.as_millis() as u64,
                        "load subscription ended; will reconnect after backoff"
                    );
                    // Reset the snapshot so the pool stops routing on the
                    // stale value while the stream is down.
                    if let Ok(mut slot) = cell.lock() {
                        *slot = None;
                    }
                    tokio::select! {
                        _ = cancel_clone.notified() => return,
                        _ = tokio::time::sleep(jittered) => {}
                    }
                }
            }
        }
    });

    SubscriptionHandle { cancel, join }
}

enum SubscriptionExit {
    Cancelled,
    Reconnect(String),
}

async fn run_subscription_once(
    channel: Channel,
    cell: LoadCell,
    tick_hint: Duration,
    subscriber_id: String,
    cancel: Arc<Notify>,
    internal_api_secret: String,
    ready: Arc<Notify>,
) -> SubscriptionExit {
    let mut client = CymbalResolutionClient::new(channel);
    let request = SubscribeRequest {
        subscriber_id,
        tick_hint_ms: u32::try_from(tick_hint.as_millis()).unwrap_or(u32::MAX),
    };

    let request = match with_internal_api_secret(Request::new(request), &internal_api_secret) {
        Ok(request) => request,
        Err(status) => {
            return SubscriptionExit::Reconnect(format!("subscribe auth metadata error: {status}"))
        }
    };
    let subscribe = client.subscribe(request);
    let response = tokio::select! {
        _ = cancel.notified() => return SubscriptionExit::Cancelled,
        res = subscribe => res,
    };
    let mut stream = match response {
        Ok(resp) => {
            metrics::counter!(
                REMOTE_RESOLUTION_LOAD_SUBSCRIPTIONS,
                "outcome" => "connected",
            )
            .increment(1);
            resp.into_inner()
        }
        Err(status) => {
            return SubscriptionExit::Reconnect(format!("subscribe rpc rejected: {status}"));
        }
    };

    loop {
        let next = tokio::select! {
            _ = cancel.notified() => return SubscriptionExit::Cancelled,
            item = stream.next() => item,
        };
        match next {
            Some(Ok(event)) => {
                let snapshot = snapshot_from_event(event);
                let should_notify = !snapshot.draining;
                if let Ok(mut slot) = cell.lock() {
                    *slot = Some(snapshot);
                }
                if should_notify {
                    ready.notify_waiters();
                }
            }
            Some(Err(status)) => {
                return SubscriptionExit::Reconnect(format!("subscribe stream error: {status}"));
            }
            None => {
                info!("load subscription stream ended cleanly; reconnecting");
                return SubscriptionExit::Reconnect("stream closed".to_string());
            }
        }
    }
}

fn jitter_for(backoff: Duration) -> Duration {
    let max_jitter_ms = (backoff.as_millis() as u64) / 2;
    if max_jitter_ms == 0 {
        return Duration::ZERO;
    }
    let offset = rand::thread_rng().gen_range(0..=max_jitter_ms);
    Duration::from_millis(offset)
}

fn snapshot_from_event(event: LoadEvent) -> LoadSnapshot {
    LoadSnapshot {
        draining: event.draining,
        in_flight: event.in_flight,
        max_in_flight: event.max_in_flight.max(1),
        observed_at: Instant::now(),
        sequence: event.sequence,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn freshness_window_distinguishes_recent_and_old_snapshots() {
        let now = Instant::now();
        let snap = LoadSnapshot {
            draining: false,
            in_flight: 0,
            max_in_flight: 64,
            observed_at: now - Duration::from_secs(10),
            sequence: 1,
        };
        assert!(!snap.is_fresh(now, Duration::from_secs(1)));
        assert!(snap.is_fresh(now, Duration::from_secs(30)));
    }

    #[test]
    fn snapshot_from_legacy_event_defaults_capacity_to_one() {
        let snapshot = snapshot_from_event(LoadEvent {
            service_instance_id: "legacy".to_string(),
            draining: false,
            sequence: 1,
            message: String::new(),
            in_flight: 0,
            max_in_flight: 0,
        });

        assert_eq!(snapshot.in_flight, 0);
        assert_eq!(snapshot.max_in_flight, 1);
    }
}
