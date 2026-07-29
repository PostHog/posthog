//! Capture-side billing quota enforcement for the OTLP signals.
//!
//! Without this, an over-quota project is answered 200 here and has its data dropped later by
//! the ingestion consumer, so the sender has no way to notice that nothing was stored.

use std::sync::Arc;
use std::time::Duration;

use common_redis::Client;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY};

/// The OTLP signal a request carries. Billing meters and limits each one separately, so they
/// each get their own quota bucket and an over-quota project keeps ingesting the other two.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Signal {
    Logs,
    Metrics,
    Traces,
}

impl Signal {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Logs => "logs",
            Self::Metrics => "metrics",
            Self::Traces => "traces",
        }
    }

    fn resource(&self) -> QuotaResource {
        match self {
            Self::Logs => QuotaResource::Logs,
            Self::Metrics => QuotaResource::Metrics,
            Self::Traces => QuotaResource::Traces,
        }
    }
}

pub struct QuotaLimiter {
    logs: RedisLimiter,
    metrics: RedisLimiter,
    traces: RedisLimiter,
    retry_after_seconds: u64,
}

impl QuotaLimiter {
    pub fn new(
        redis: Arc<dyn Client + Send + Sync>,
        refresh_interval: Duration,
        redis_key_prefix: Option<String>,
        retry_after_seconds: u64,
    ) -> anyhow::Result<Self> {
        let limiter_for = |signal: Signal| {
            RedisLimiter::new(
                refresh_interval,
                redis.clone(),
                QUOTA_LIMITER_CACHE_KEY.to_string(),
                redis_key_prefix.clone(),
                signal.resource(),
                ServiceName::CaptureLogs,
            )
        };

        Ok(Self {
            logs: limiter_for(Signal::Logs)?,
            metrics: limiter_for(Signal::Metrics)?,
            traces: limiter_for(Signal::Traces)?,
            retry_after_seconds,
        })
    }

    /// `Some(retry_after_seconds)` when this token is over its quota for `signal`.
    ///
    /// The answer comes from a snapshot the limiter refreshes in the background, which shapes
    /// two Redis failure modes differently. A Redis that has never been reached leaves the
    /// snapshot empty, so a service that starts without Redis accepts everything rather than
    /// rejecting everything. An outage that begins after a successful load keeps serving the
    /// last snapshot rather than clearing it, so tokens already known to be over quota stay
    /// rejected until Redis returns.
    pub async fn retry_after_if_limited(&self, signal: Signal, token: &str) -> Option<u64> {
        let limiter = match signal {
            Signal::Logs => &self.logs,
            Signal::Metrics => &self.metrics,
            Signal::Traces => &self.traces,
        };

        limiter
            .is_limited(token)
            .await
            .then_some(self.retry_after_seconds)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;

    const RETRY_AFTER: u64 = 900;

    fn limiter(redis: MockRedisClient) -> QuotaLimiter {
        QuotaLimiter::new(Arc::new(redis), Duration::from_millis(5), None, RETRY_AFTER)
            .expect("failed to build quota limiter")
    }

    /// The limiters load their caches from spawned tasks, so poll the observable condition
    /// instead of sleeping for a duration the test would have to guess.
    async fn await_limited(quota: &QuotaLimiter, signal: Signal, token: &str) -> Option<u64> {
        for _ in 0..200 {
            if let Some(retry_after) = quota.retry_after_if_limited(signal, token).await {
                return Some(retry_after);
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        None
    }

    #[tokio::test]
    async fn each_signal_reads_its_own_quota_bucket() {
        // Populating exactly one bucket per case pins each signal to its own Redis key. Wiring
        // a signal to the wrong key would leave it permanently unlimited rather than erroring.
        for (signal, key) in [
            (Signal::Logs, "@posthog/quota-limits/logs_mb_ingested"),
            (Signal::Metrics, "@posthog/quota-limits/metrics_mb_ingested"),
            (Signal::Traces, "@posthog/quota-limits/traces_mb_ingested"),
        ] {
            let quota =
                limiter(MockRedisClient::new().zrangebyscore_ret(key, vec!["phc_over".into()]));

            assert_eq!(
                await_limited(&quota, signal, "phc_over").await,
                Some(RETRY_AFTER),
                "{} did not read {key}",
                signal.as_str()
            );
        }
    }

    #[tokio::test]
    async fn a_project_over_one_signals_quota_keeps_ingesting_the_others() {
        let quota = limiter(
            MockRedisClient::new()
                .zrangebyscore_ret(
                    "@posthog/quota-limits/logs_mb_ingested",
                    vec!["phc_over_on_logs".into()],
                )
                .zrangebyscore_ret(
                    "@posthog/quota-limits/traces_mb_ingested",
                    vec!["phc_over_on_traces".into()],
                ),
        );

        // Awaiting a token that *is* traces-limited proves the traces cache has loaded, so the
        // negative assertions below cannot pass merely because the snapshot was still empty.
        assert_eq!(
            await_limited(&quota, Signal::Traces, "phc_over_on_traces").await,
            Some(RETRY_AFTER)
        );

        assert_eq!(
            quota
                .retry_after_if_limited(Signal::Traces, "phc_over_on_logs")
                .await,
            None
        );
        assert_eq!(
            quota
                .retry_after_if_limited(Signal::Logs, "phc_over_on_traces")
                .await,
            None
        );
    }

    #[tokio::test]
    async fn a_redis_that_was_never_reached_limits_nobody() {
        // The mock errors for every key it was not given. A limiter that never loaded a
        // snapshot has to accept traffic, because rejecting instead would take ingestion down
        // for every project the moment Redis is unavailable at startup.
        let quota = limiter(MockRedisClient::new());

        assert_eq!(
            quota
                .retry_after_if_limited(Signal::Logs, "phc_anything")
                .await,
            None
        );
    }
}
