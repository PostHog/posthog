//! Per-team cap on issue lifecycle workflow starts.
//!
//! One bucket per team, charged by every notification type. A team that exhausts
//! it gets no lifecycle workflow, and therefore no embedding and no alert, until
//! the bucket refills.

use std::collections::HashSet;
use std::sync::Arc;

use common_redis::RedisClient;
use tracing::{info, warn};

use crate::core::error::UnhandledError;
use crate::core::metric_consts::{LIFECYCLE_RATE_LIMIT_FAIL_OPEN, LIFECYCLE_RATE_LIMIT_OUTCOMES};
use crate::modes::notifications::config::NotificationsConfig;
use crate::modes::notifications::temporal::WorkflowStart;
use crate::modes::notifications::token_bucket::TokenBucket;

/// What the handler should do with one notification.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LifecycleDecision {
    /// A token was spent. Start the workflow, then hand the outcome to
    /// [`LifecycleRateLimiter::settle`].
    Admitted,
    /// The team is out of budget. Start no workflow.
    Limited,
    /// No token was spent, because the limit is off, the team is not covered, or
    /// Redis failed. Start the workflow and never refund.
    Uncharged,
}

impl LifecycleDecision {
    pub fn is_limited(self) -> bool {
        self == LifecycleDecision::Limited
    }
}

pub struct LifecycleRateLimiter {
    /// `None` disables the limit: every notification comes back `Uncharged`.
    bucket: Option<TokenBucket>,
    /// `None` covers every team.
    enabled_team_ids: Option<HashSet<i32>>,
}

impl LifecycleRateLimiter {
    pub async fn from_config(config: &NotificationsConfig) -> Result<Self, UnhandledError> {
        let disabled = |reason: &str| {
            info!("Error-tracking lifecycle rate limiter disabled: {reason}");
            Self {
                bucket: None,
                enabled_team_ids: None,
            }
        };

        if config.lifecycle_rate_limit_redis_url.is_empty() {
            return Ok(disabled("no Redis URL"));
        }
        if config.lifecycle_rate_limit_per_hour <= 0 {
            return Ok(disabled("limit is zero or less"));
        }

        let client = RedisClient::with_config(
            config.lifecycle_rate_limit_redis_url.clone(),
            common_redis::CompressionConfig::disabled(),
            common_redis::RedisValueFormat::Utf8,
            optional_millis(config.redis_response_timeout_ms),
            optional_millis(config.redis_connection_timeout_ms),
        )
        .await?;

        let enabled_team_ids =
            parse_team_id_allowlist(&config.lifecycle_rate_limit_enabled_team_ids);
        info!(
            per_hour = config.lifecycle_rate_limit_per_hour,
            teams = enabled_team_ids.as_ref().map_or(0, HashSet::len),
            "Error-tracking lifecycle rate limiter enabled",
        );

        Ok(Self {
            bucket: Some(TokenBucket::per_hour(
                Arc::new(client),
                config.lifecycle_rate_limit_key_prefix.clone(),
                config.lifecycle_rate_limit_per_hour as f64,
                config.lifecycle_rate_limit_bucket_ttl_seconds,
            )),
            enabled_team_ids,
        })
    }

    /// Charge one token for a team, and say what the handler should do next.
    /// Redis failures fail open: a limiter outage must not silence alerts.
    pub async fn decide(&self, team_id: i32, notification_type: &'static str) -> LifecycleDecision {
        let Some(bucket) = self.bucket.as_ref() else {
            return LifecycleDecision::Uncharged;
        };
        if self
            .enabled_team_ids
            .as_ref()
            .is_some_and(|allowed| !allowed.contains(&team_id))
        {
            return LifecycleDecision::Uncharged;
        }

        match bucket.charge(team_id).await {
            Ok(true) => {
                record("admitted", notification_type);
                LifecycleDecision::Admitted
            }
            Ok(false) => {
                record("limited", notification_type);
                LifecycleDecision::Limited
            }
            Err(e) => {
                warn!("lifecycle rate limiter failed open for team {team_id}: {e}");
                metrics::counter!(LIFECYCLE_RATE_LIMIT_FAIL_OPEN).increment(1);
                LifecycleDecision::Uncharged
            }
        }
    }

    /// Give the token back when Temporal reports the workflow already exists.
    /// The consumer replays a batch after a restart, and `start_workflow` is
    /// idempotent on the workflow id, so a replay does no work and must cost
    /// nothing. This is what keeps the charge idempotent.
    pub async fn settle(
        &self,
        team_id: i32,
        notification_type: &'static str,
        decision: LifecycleDecision,
        start: WorkflowStart,
    ) {
        if decision != LifecycleDecision::Admitted || start != WorkflowStart::AlreadyRunning {
            return;
        }
        let Some(bucket) = self.bucket.as_ref() else {
            return;
        };

        match bucket.refund(team_id).await {
            Ok(()) => record("refunded", notification_type),
            // A lost refund costs the team one token out of its hourly budget.
            Err(e) => warn!("lifecycle rate limiter refund failed for team {team_id}: {e}"),
        }
    }
}

fn record(outcome: &'static str, notification_type: &'static str) {
    metrics::counter!(
        LIFECYCLE_RATE_LIMIT_OUTCOMES,
        "outcome" => outcome,
        "type" => notification_type,
    )
    .increment(1);
}

fn optional_millis(millis: u64) -> Option<std::time::Duration> {
    (millis > 0).then(|| std::time::Duration::from_millis(millis))
}

/// `None` (empty input) covers every team. `Some(set)` restricts the limit to
/// the listed ones. Mirrors the event limiter's allowlist.
fn parse_team_id_allowlist(value: &str) -> Option<HashSet<i32>> {
    if value.is_empty() {
        return None;
    }

    let ids: HashSet<i32> = value
        .split(',')
        .filter_map(|id| id.trim().parse().ok())
        .collect();
    (!ids.is_empty()).then_some(ids)
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use common_redis::CustomRedisError;
    use std::sync::Mutex;

    use crate::modes::notifications::token_bucket::LuaRunner;

    /// A `ScriptRunner` that never touches Redis: it returns a canned reply, or
    /// an error, and records the scripts it was asked to run.
    struct FakeRunner {
        reply: Option<Vec<i64>>,
        calls: Mutex<Vec<String>>,
    }

    impl FakeRunner {
        fn returning(reply: Vec<i64>) -> Arc<Self> {
            Arc::new(Self {
                reply: Some(reply),
                calls: Mutex::new(Vec::new()),
            })
        }

        fn failing() -> Arc<Self> {
            Arc::new(Self {
                reply: None,
                calls: Mutex::new(Vec::new()),
            })
        }

        fn call_count(&self) -> usize {
            self.calls.lock().unwrap().len()
        }

        fn refunds(&self) -> usize {
            self.calls
                .lock()
                .unwrap()
                .iter()
                .filter(|script| script.contains("math.min(tokens + 1, max)"))
                .count()
        }
    }

    #[async_trait]
    impl LuaRunner for FakeRunner {
        async fn eval_int_vec(
            &self,
            script: &str,
            _keys: Vec<String>,
            _args: Vec<String>,
        ) -> Result<Vec<i64>, CustomRedisError> {
            self.calls.lock().unwrap().push(script.to_string());
            self.reply.clone().ok_or(CustomRedisError::Timeout)
        }
    }

    fn limiter_with(runner: Arc<FakeRunner>) -> LifecycleRateLimiter {
        LifecycleRateLimiter {
            bucket: Some(TokenBucket::per_hour(
                runner,
                "test".to_string(),
                1000.0,
                3600,
            )),
            enabled_team_ids: None,
        }
    }

    fn disabled_limiter() -> LifecycleRateLimiter {
        LifecycleRateLimiter {
            bucket: None,
            enabled_team_ids: None,
        }
    }

    #[tokio::test]
    async fn a_denied_charge_limits_the_notification() {
        let limiter = limiter_with(FakeRunner::returning(vec![0]));
        assert_eq!(
            limiter.decide(42, "issue_created").await,
            LifecycleDecision::Limited
        );
    }

    #[tokio::test]
    async fn a_redis_error_fails_open() {
        let limiter = limiter_with(FakeRunner::failing());
        assert_eq!(
            limiter.decide(42, "issue_created").await,
            LifecycleDecision::Uncharged
        );
    }

    #[tokio::test]
    async fn a_team_outside_the_allowlist_is_never_charged() {
        let runner = FakeRunner::returning(vec![0]);
        let mut limiter = limiter_with(runner.clone());
        limiter.enabled_team_ids = Some(HashSet::from([7]));

        assert_eq!(
            limiter.decide(42, "issue_created").await,
            LifecycleDecision::Uncharged
        );
        assert_eq!(runner.call_count(), 0);
    }

    #[tokio::test]
    async fn a_disabled_limiter_charges_nothing() {
        let limiter = disabled_limiter();
        assert_eq!(
            limiter.decide(42, "issue_created").await,
            LifecycleDecision::Uncharged
        );
    }

    #[tokio::test]
    async fn only_an_already_running_workflow_refunds() {
        let cases = [
            (
                LifecycleDecision::Admitted,
                WorkflowStart::AlreadyRunning,
                1,
            ),
            (LifecycleDecision::Admitted, WorkflowStart::Started, 0),
            (
                LifecycleDecision::Uncharged,
                WorkflowStart::AlreadyRunning,
                0,
            ),
        ];

        for (decision, start, expected_refunds) in cases {
            let runner = FakeRunner::returning(vec![1]);
            let limiter = limiter_with(runner.clone());
            limiter.settle(42, "issue_created", decision, start).await;
            assert_eq!(runner.refunds(), expected_refunds, "{decision:?} {start:?}");
        }
    }
}
