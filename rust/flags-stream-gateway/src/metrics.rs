//! The gateway's metric surface (plan §2.10), product label `feature_flags`.
//!
//! Every metric here has only **static** label values (`kind`, `occasion`,
//! `reason`, `source`, `outcome`), so per rust/CLAUDE.md they are `&'static str`
//! passed straight into the `metrics` macros — `Arc<str>` is reserved for dynamic
//! values, of which there are none. Keeping every emission behind a named helper
//! means the label vocabulary lives in one place and can't drift between call
//! sites.

use metrics::{counter, gauge, histogram};

use crate::domain::CacheKind;

/// Live SSE connections, by kind.
pub const ACTIVE_CONNECTIONS: &str = "flags_stream_active_connections";
/// Connect attempts, labelled `reason` = `accepted` | `denied:*`.
pub const CONNECTS_TOTAL: &str = "flags_stream_connects_total";
/// Stream closes, labelled `reason` = `client_closed` | `max_age` | `shutdown`.
pub const DISCONNECTS_TOTAL: &str = "flags_stream_disconnects_total";
/// Every SSE frame sent, labelled `occasion` = `init` | `change` | `heartbeat`.
pub const EVENTS_SENT_TOTAL: &str = "flags_stream_events_sent_total";
/// Change-driven frames only — the "a client was told to refetch" signal.
pub const NOTIFICATIONS_SENT_TOTAL: &str = "flags_stream_notifications_sent_total";
/// The trigger truth table, labelled `source` and `outcome`.
pub const OBSERVATIONS_TOTAL: &str = "flags_stream_observations_total";
/// Hint publish→apply latency; the fast-path latency measure.
pub const HINT_LAG_MS: &str = "flags_stream_hint_lag_ms";
/// Sweep batch (one MGET) duration; the backbone latency measure.
pub const SWEEP_BATCH_MS: &str = "flags_stream_sweep_batch_ms";
/// Reconnects whose `Last-Event-ID` matched the current version ("deploys are
/// nearly free" numerator).
pub const RECONNECT_CURRENT_TOTAL: &str = "flags_stream_reconnect_current_total";
/// Reconnects whose `Last-Event-ID` was stale (a refetch was warranted).
pub const RECONNECT_STALE_TOTAL: &str = "flags_stream_reconnect_stale_total";
/// Topics with at least one subscriber, by kind — the sweep-load driver.
pub const SUBSCRIBED_TOPICS: &str = "flags_stream_subscribed_topics";
/// Hints dropped before apply, labelled `reason`.
pub const HINTS_DROPPED_TOTAL: &str = "flags_stream_hints_dropped_total";

/// SSE frame occasion (`occasion` label).
pub const OCCASION_INIT: &str = "init";
pub const OCCASION_CHANGE: &str = "change";
pub const OCCASION_HEARTBEAT: &str = "heartbeat";

/// Disconnect reasons (`reason` label on [`DISCONNECTS_TOTAL`]).
pub const DISCONNECT_CLIENT_CLOSED: &str = "client_closed";
pub const DISCONNECT_MAX_AGE: &str = "max_age";
pub const DISCONNECT_SHUTDOWN: &str = "shutdown";

/// Trigger source (`source` label on [`OBSERVATIONS_TOTAL`]).
pub const SOURCE_SWEEP: &str = "sweep";
pub const SOURCE_HINT: &str = "hint";

/// Record a connection accepted: bump the live gauge and count the accept.
pub fn connection_opened(kind: CacheKind) {
    gauge!(ACTIVE_CONNECTIONS, "kind" => kind.wire_name()).increment(1.0);
    counter!(CONNECTS_TOTAL, "kind" => kind.wire_name(), "reason" => "accepted").increment(1);
}

/// Record a connect denied at admission (401/403/429/503), `reason` = `denied:*`.
pub fn connection_denied(kind: CacheKind, reason: &'static str) {
    counter!(CONNECTS_TOTAL, "kind" => kind.wire_name(), "reason" => reason).increment(1);
}

/// Record a stream close: drop the live gauge and count the reason.
pub fn connection_closed(kind: CacheKind, reason: &'static str) {
    gauge!(ACTIVE_CONNECTIONS, "kind" => kind.wire_name()).decrement(1.0);
    counter!(DISCONNECTS_TOTAL, "kind" => kind.wire_name(), "reason" => reason).increment(1);
}

/// Record an SSE frame sent (any occasion).
pub fn event_sent(kind: CacheKind, occasion: &'static str) {
    counter!(EVENTS_SENT_TOTAL, "kind" => kind.wire_name(), "occasion" => occasion).increment(1);
}

/// Record a change notification (a subset of [`event_sent`] with `change`).
pub fn notification_sent(kind: CacheKind) {
    counter!(NOTIFICATIONS_SENT_TOTAL, "kind" => kind.wire_name()).increment(1);
}

/// Record one trigger observation with its resolved outcome.
pub fn observation(kind: CacheKind, source: &'static str, outcome: &'static str) {
    counter!(OBSERVATIONS_TOTAL, "kind" => kind.wire_name(), "source" => source, "outcome" => outcome)
        .increment(1);
}

/// Record hint publish→apply latency in milliseconds.
pub fn hint_lag_ms(value_ms: f64) {
    histogram!(HINT_LAG_MS).record(value_ms);
}

/// Record one sweep batch (a single MGET) duration in milliseconds.
pub fn sweep_batch_ms(kind: CacheKind, value_ms: f64) {
    histogram!(SWEEP_BATCH_MS, "kind" => kind.wire_name()).record(value_ms);
}

/// Record a reconnect whose `Last-Event-ID` matched the current version.
pub fn reconnect_current(kind: CacheKind) {
    counter!(RECONNECT_CURRENT_TOTAL, "kind" => kind.wire_name()).increment(1);
}

/// Record a reconnect whose `Last-Event-ID` was stale.
pub fn reconnect_stale(kind: CacheKind) {
    counter!(RECONNECT_STALE_TOTAL, "kind" => kind.wire_name()).increment(1);
}

/// Publish the current subscribed-topic count for a kind (called each sweep tick).
pub fn subscribed_topics(kind: CacheKind, count: usize) {
    gauge!(SUBSCRIBED_TOPICS, "kind" => kind.wire_name()).set(count as f64);
}

/// Record a hint dropped before apply, with the drop reason.
pub fn hint_dropped(reason: &'static str) {
    counter!(HINTS_DROPPED_TOTAL, "reason" => reason).increment(1);
}
