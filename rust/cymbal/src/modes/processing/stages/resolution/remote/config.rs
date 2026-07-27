use std::time::Duration;

use crate::error::UnhandledError;
use crate::modes::processing::config::ProcessingConfig;

/// Narrowed view of [`crate::modes::processing::config::ProcessingConfig`] containing only the fields used
/// by the remote resolution client. Keeping a dedicated struct lets the pool,
/// DNS, and resolver modules be exercised in tests without touching cymbal's
/// full env-var surface.
#[derive(Clone)]
pub struct RemoteResolutionConfig {
    pub host: String,
    pub port: u16,
    /// Shared secret attached to every cymbal-resolution gRPC request.
    pub internal_api_secret: String,
    pub dns_refresh: Duration,
    pub request_deadline: Duration,
    pub connect_timeout: Duration,
    pub max_retries: u32,
    /// Initial backoff between retries; doubles each attempt up to `retry_max_backoff`.
    pub retry_backoff: Duration,
    /// Ceiling for the exponential retry backoff window.
    pub retry_max_backoff: Duration,
    /// Initial process-local endpoint ejection window after a per-item overload outcome.
    pub overload_ejection_initial: Duration,
    /// Maximum process-local endpoint ejection window after repeated overload outcomes.
    pub overload_ejection_max: Duration,
    /// Quiet window after which endpoint ejection backs off to the initial duration.
    pub overload_ejection_decay: Duration,
    /// Event-level deterministic sample rate for sending eligible events to
    /// cymbal-resolution. Defaults to 0.0 in [`Config`] so enabling remote mode
    /// alone does not start sending traffic until rollout is ramped explicitly.
    pub sample_rate: f64,
    /// Rank-distribution factor for selecting among rendezvous-ranked candidates.
    /// `0.0` is fully sticky to rank 0; `1.0` is uniform across candidates.
    pub routing_jitter: f64,
    /// Maximum number of items that can concurrently wait for a pod to accept
    /// routing ownership.
    pub routing_acceptance_concurrency: usize,
    /// Cadence hint sent on `SubscribeRequest.tick_hint_ms`. The server may
    /// clamp this; the caller relies on whatever cadence the server settles on.
    /// Doubles as the freshness window: snapshots older than `2 *
    /// subscribe_tick_hint` are treated as "no signal" and the pool excludes
    /// the endpoint from routing. Coupling staleness to the tick removes a knob
    /// that previously had to be tuned in lockstep.
    pub subscribe_tick_hint: Duration,
    /// Backoff applied before a per-endpoint subscription task reconnects after
    /// the stream ends or errors. Kept small so a transient blip doesn't leave
    /// the pool routing on stale data for long.
    pub subscribe_reconnect_backoff: Duration,
}

impl RemoteResolutionConfig {
    pub fn from_config(config: &ProcessingConfig) -> Result<Self, UnhandledError> {
        if config.remote_resolution_host.trim().is_empty() {
            return Err(UnhandledError::Other(
                "remote resolution enabled but CYMBAL_REMOTE_RESOLUTION_HOST is empty".to_string(),
            ));
        }
        if config.resolver.internal_api_secret.trim().is_empty() {
            return Err(UnhandledError::Other(
                "remote resolution enabled but INTERNAL_API_SECRET is empty".to_string(),
            ));
        }
        Ok(Self {
            host: config.remote_resolution_host.clone(),
            port: config.remote_resolution_port,
            internal_api_secret: config.resolver.internal_api_secret.clone(),
            dns_refresh: Duration::from_secs(config.remote_resolution_dns_refresh_secs.max(1)),
            request_deadline: Duration::from_millis(config.remote_resolution_deadline_ms.max(1)),
            connect_timeout: Duration::from_millis(
                config.remote_resolution_connect_timeout_ms.max(1),
            ),
            max_retries: config.remote_resolution_max_retries,
            retry_backoff: Duration::from_millis(config.remote_resolution_retry_backoff_ms.max(1)),
            retry_max_backoff: Duration::from_millis(
                config
                    .remote_resolution_retry_max_backoff_ms
                    .max(config.remote_resolution_retry_backoff_ms.max(1)),
            ),
            overload_ejection_initial: Duration::from_millis(
                config.remote_resolution_overload_ejection_ms,
            ),
            overload_ejection_max: Duration::from_millis(
                config
                    .remote_resolution_overload_ejection_max_ms
                    .max(config.remote_resolution_overload_ejection_ms),
            ),
            overload_ejection_decay: Duration::from_millis(
                config.remote_resolution_overload_ejection_decay_ms,
            ),
            sample_rate: normalized_probability(config.remote_resolution_sample_rate),
            routing_jitter: normalized_probability(config.remote_resolution_routing_jitter),
            routing_acceptance_concurrency: config
                .remote_resolution_routing_acceptance_concurrency
                .max(1),
            subscribe_tick_hint: Duration::from_millis(
                config.remote_resolution_subscribe_tick_hint_ms.max(1),
            ),
            subscribe_reconnect_backoff: Duration::from_millis(
                config
                    .remote_resolution_subscribe_reconnect_backoff_ms
                    .max(1),
            ),
        })
    }
}

fn normalized_probability(value: f64) -> f64 {
    if !value.is_finite() {
        return 1.0;
    }
    value.clamp(0.0, 1.0)
}

#[cfg(test)]
mod tests {
    use super::normalized_probability;

    #[test]
    fn probability_is_clamped_to_valid_range() {
        assert_eq!(normalized_probability(-0.5), 0.0);
        assert_eq!(normalized_probability(0.25), 0.25);
        assert_eq!(normalized_probability(1.5), 1.0);
        assert_eq!(normalized_probability(f64::NAN), 1.0);
    }
}
