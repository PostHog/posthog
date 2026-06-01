use std::sync::Arc;
use std::time::Duration;

use futures::Stream;
use tonic::Status;
use tracing::info;

use crate::load_monitor::LoadMonitor;
use cymbal_proto::cymbal::resolution::v1::LoadEvent;

const SUBSCRIBE_EVENTS_TOTAL: &str = "cymbal_resolution_subscribe_events_total";
const SUBSCRIBERS_TOTAL: &str = "cymbal_resolution_subscribers_total";

pub(super) struct SubscribeRuntime {
    pub(super) service_instance_id: Arc<str>,
    pub(super) load_monitor: LoadMonitor,
    pub(super) tick: Duration,
    pub(super) subscriber_id: String,
}

/// Logs the subscription closing when the generator future is dropped — which
/// happens both when the client disconnects (tonic drops the stream) and when
/// the loop is otherwise cancelled. Mirrors the "opened" log at the call site.
struct CloseLog {
    subscriber_id: String,
}

impl Drop for CloseLog {
    fn drop(&mut self) {
        info!(subscriber = %self.subscriber_id, "load event subscription closed");
        metrics::counter!(SUBSCRIBERS_TOTAL, "event" => "close").increment(1);
    }
}

pub(super) fn load_event_stream(
    runtime: SubscribeRuntime,
) -> impl Stream<Item = Result<LoadEvent, Status>> {
    async_stream::stream! {
        metrics::counter!(SUBSCRIBERS_TOTAL, "event" => "open").increment(1);
        let _close_log = CloseLog { subscriber_id: runtime.subscriber_id };

        let mut ticker = tokio::time::interval(runtime.tick);
        // First tick fires immediately so the caller sees state without waiting
        // a full period; thereafter Delay matches the pool's polling expectation
        // (skip missed ticks instead of bursting catch-up events).
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        let mut sequence: u64 = 0;

        loop {
            tokio::select! {
                _ = ticker.tick() => {}
                _ = runtime.load_monitor.notified() => {}
            }

            sequence += 1;
            let snapshot = runtime.load_monitor.snapshot();
            metrics::counter!(SUBSCRIBE_EVENTS_TOTAL).increment(1);
            yield Ok(LoadEvent {
                service_instance_id: runtime.service_instance_id.as_ref().to_string(),
                draining: snapshot.draining,
                sequence,
                message: String::new(),
            });
        }
    }
}
