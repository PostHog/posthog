//! Per-team cap on issue-created workflow starts.
//!
//! Only issue-created is charged, because it is the only notification type with
//! no ceiling of its own: reopens need somebody to have resolved the issue first,
//! and spikes carry a per-issue Redis cooldown. It is also the only type that
//! runs an embedding.

use std::sync::Arc;

use common_redis::RedisClient;
use tracing::{info, warn};

use crate::core::error::UnhandledError;
use crate::core::metric_consts::{
    ISSUE_CREATED_RATE_LIMIT_FAIL_OPEN, ISSUE_CREATED_RATE_LIMIT_OUTCOMES,
    ISSUE_CREATED_RATE_LIMIT_REFUNDS,
};
use crate::modes::notifications::config::NotificationsConfig;
use crate::modes::notifications::token_bucket::TokenBucket;
use crate::modes::processing::redis_heal::is_connection_error;

pub struct IssueCreatedRateLimiter {
    /// `None` disables the limit: every notification is admitted.
    bucket: Option<TokenBucket>,
}

impl IssueCreatedRateLimiter {
    pub async fn from_config(config: &NotificationsConfig) -> Result<Self, UnhandledError> {
        if config.notifications_rate_limit_per_hour <= 0 {
            info!("Error-tracking issue-created rate limiter disabled: limit is zero or less");
            return Ok(Self { bucket: None });
        }

        // Fatal on purpose: a pod that cannot reach the Redis it was told to use
        // must not come up and run without the limit. Runtime failures differ,
        // because `admit` fails open rather than silence a serving pod's alerts.
        let client = RedisClient::with_config(
            config.notifications_rate_limit_redis_url.clone(),
            common_redis::CompressionConfig::disabled(),
            common_redis::RedisValueFormat::Utf8,
            optional_millis(config.redis_response_timeout_ms),
            optional_millis(config.redis_connection_timeout_ms),
        )
        .await?;

        info!(
            per_hour = config.notifications_rate_limit_per_hour,
            "Error-tracking issue-created rate limiter enabled for all teams",
        );

        Ok(Self {
            bucket: Some(TokenBucket::per_hour(
                Arc::new(client),
                config.notifications_rate_limit_key_prefix.clone(),
                config.notifications_rate_limit_per_hour as f64,
                config.notifications_rate_limit_bucket_ttl_seconds,
            )),
        })
    }

    /// Charge one token. `false` means the team is out of budget, so the
    /// notification starts no workflow. A Redis failure admits, because a limiter
    /// outage must not silence alerts.
    pub async fn admit(&self, team_id: i32) -> bool {
        let Some(bucket) = self.bucket.as_ref() else {
            return true;
        };

        match bucket.charge(team_id).await {
            Ok(true) => {
                record("admitted");
                true
            }
            Ok(false) => {
                record("limited");
                false
            }
            Err(e) => {
                // Without this, one Redis failover leaves this pod admitting
                // everything for its whole lifetime, which is the state
                // `from_config` refuses to boot into.
                if is_connection_error(&e) {
                    bucket.spawn_heal();
                }
                warn!("issue-created rate limiter failed open for team {team_id}: {e}");
                metrics::counter!(ISSUE_CREATED_RATE_LIMIT_FAIL_OPEN).increment(1);
                true
            }
        }
    }

    /// Hand back a token charged for a workflow that turned out to be already
    /// running, so a Kafka replay does not spend a team's budget twice. Best
    /// effort: a failed refund costs the team one token and is not retried,
    /// because a retry risks crediting twice. A refund that follows a
    /// failed-open charge credits a token that was never spent, which the bucket
    /// size caps and which errs the way the rest of the limiter already does.
    pub async fn refund(&self, team_id: i32) {
        let Some(bucket) = self.bucket.as_ref() else {
            return;
        };

        match bucket.refund(team_id).await {
            Ok(()) => record_refund("refunded"),
            Err(e) => {
                if is_connection_error(&e) {
                    bucket.spawn_heal();
                }
                warn!("issue-created rate limiter could not refund team {team_id}: {e}");
                record_refund("error");
            }
        }
    }
}

fn record(outcome: &'static str) {
    metrics::counter!(ISSUE_CREATED_RATE_LIMIT_OUTCOMES, "outcome" => outcome).increment(1);
}

fn record_refund(outcome: &'static str) {
    metrics::counter!(ISSUE_CREATED_RATE_LIMIT_REFUNDS, "outcome" => outcome).increment(1);
}

fn optional_millis(millis: u64) -> Option<std::time::Duration> {
    (millis > 0).then(|| std::time::Duration::from_millis(millis))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::FakeRunner;

    fn limiter_with(runner: Arc<FakeRunner>) -> IssueCreatedRateLimiter {
        IssueCreatedRateLimiter {
            bucket: Some(TokenBucket::per_hour(
                runner,
                "test".to_string(),
                1000.0,
                3600,
            )),
        }
    }

    #[tokio::test]
    async fn a_denied_charge_limits_the_notification() {
        let limiter = limiter_with(FakeRunner::returning(vec![0]));
        assert!(!limiter.admit(42).await);
    }

    #[tokio::test]
    async fn a_redis_error_fails_open() {
        let limiter = limiter_with(FakeRunner::failing());
        assert!(limiter.admit(42).await);
    }

    #[tokio::test]
    async fn a_disabled_limiter_admits_everything() {
        let limiter = IssueCreatedRateLimiter { bucket: None };
        assert!(limiter.admit(42).await);
    }
}
