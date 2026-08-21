//! Per-team cap on issue-created workflow starts.
//!
//! Only issue-created is charged. It is the one notification type with no ceiling
//! of its own: a high-cardinality fingerprint mints issues as fast as a team sends
//! events. Reopens need somebody to have resolved the issue first, and spikes
//! already carry a per-issue Redis cooldown. Issue-created is also the only type
//! that runs an embedding.
//!
//! A team that exhausts its bucket gets no issue-created workflow, and therefore
//! no embedding and no alert for new issues, until the bucket refills. Its reopen
//! and spike alerts keep working.

use std::sync::Arc;

use common_redis::RedisClient;
use tracing::{info, warn};

use crate::core::error::UnhandledError;
use crate::core::metric_consts::{
    ISSUE_CREATED_RATE_LIMIT_FAIL_OPEN, ISSUE_CREATED_RATE_LIMIT_OUTCOMES,
};
use crate::modes::notifications::config::NotificationsConfig;
use crate::modes::notifications::temporal::WorkflowStart;
use crate::modes::notifications::token_bucket::TokenBucket;

/// What the handler should do with one notification.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Decision {
    /// A token was spent. Start the workflow, then hand the outcome to
    /// [`IssueCreatedRateLimiter::settle`].
    Admitted,
    /// The team is out of budget. Start no workflow.
    Limited,
    /// No token was spent, because the limit is off or Redis failed. Start the
    /// workflow and never refund.
    Uncharged,
}

impl Decision {
    pub fn is_limited(self) -> bool {
        self == Decision::Limited
    }
}

pub struct IssueCreatedRateLimiter {
    /// `None` disables the limit: every notification comes back `Uncharged`.
    bucket: Option<TokenBucket>,
}

impl IssueCreatedRateLimiter {
    pub async fn from_config(config: &NotificationsConfig) -> Result<Self, UnhandledError> {
        let disabled = |reason: &str| {
            info!("Error-tracking issue-created rate limiter disabled: {reason}");
            Self { bucket: None }
        };

        if config.notifications_rate_limit_redis_url.is_empty() {
            return Ok(disabled("no Redis URL"));
        }
        if config.notifications_rate_limit_per_hour <= 0 {
            return Ok(disabled("limit is zero or less"));
        }

        // A Redis that is configured but unreachable is fatal on purpose. The
        // limiter exists to protect shared Temporal and embedding capacity, so a
        // pod that cannot enforce it must not come up and quietly run without it.
        // Runtime failures are different: `decide` fails open, because a limiter
        // outage must not silence alerts for pods that are already serving.
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

    /// Charge one token for a team, and say what the handler should do next.
    /// Redis failures fail open: a limiter outage must not silence alerts.
    pub async fn decide(&self, team_id: i32) -> Decision {
        let Some(bucket) = self.bucket.as_ref() else {
            return Decision::Uncharged;
        };

        match bucket.charge(team_id).await {
            Ok(true) => {
                record("admitted");
                Decision::Admitted
            }
            Ok(false) => {
                record("limited");
                Decision::Limited
            }
            Err(e) => {
                warn!("issue-created rate limiter failed open for team {team_id}: {e}");
                metrics::counter!(ISSUE_CREATED_RATE_LIMIT_FAIL_OPEN).increment(1);
                Decision::Uncharged
            }
        }
    }

    /// Give the token back when Temporal reports the workflow already exists.
    /// The consumer replays a batch after a restart, and `start_workflow` is
    /// idempotent on the workflow id, so a replay does no work and must cost
    /// nothing. This is what keeps the charge idempotent.
    pub async fn settle(&self, team_id: i32, decision: Decision, start: WorkflowStart) {
        if decision != Decision::Admitted || start != WorkflowStart::AlreadyRunning {
            return;
        }
        let Some(bucket) = self.bucket.as_ref() else {
            return;
        };

        match bucket.refund(team_id).await {
            Ok(()) => record("refunded"),
            // A lost refund costs the team one token out of its hourly budget.
            Err(e) => warn!("issue-created rate limiter refund failed for team {team_id}: {e}"),
        }
    }
}

fn record(outcome: &'static str) {
    metrics::counter!(ISSUE_CREATED_RATE_LIMIT_OUTCOMES, "outcome" => outcome).increment(1);
}

fn optional_millis(millis: u64) -> Option<std::time::Duration> {
    (millis > 0).then(|| std::time::Duration::from_millis(millis))
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

    fn disabled_limiter() -> IssueCreatedRateLimiter {
        IssueCreatedRateLimiter { bucket: None }
    }

    #[tokio::test]
    async fn a_denied_charge_limits_the_notification() {
        let limiter = limiter_with(FakeRunner::returning(vec![0]));
        assert_eq!(limiter.decide(42).await, Decision::Limited);
    }

    #[tokio::test]
    async fn a_redis_error_fails_open() {
        let limiter = limiter_with(FakeRunner::failing());
        assert_eq!(limiter.decide(42).await, Decision::Uncharged);
    }

    #[tokio::test]
    async fn a_disabled_limiter_charges_nothing() {
        let limiter = disabled_limiter();
        assert_eq!(limiter.decide(42).await, Decision::Uncharged);
    }

    #[tokio::test]
    async fn only_an_already_running_workflow_refunds() {
        let cases = [
            (Decision::Admitted, WorkflowStart::AlreadyRunning, 1),
            (Decision::Admitted, WorkflowStart::Started, 0),
            (Decision::Uncharged, WorkflowStart::AlreadyRunning, 0),
        ];

        for (decision, start, expected_refunds) in cases {
            let runner = FakeRunner::returning(vec![1]);
            let limiter = limiter_with(runner.clone());
            limiter.settle(42, decision, start).await;
            assert_eq!(runner.refunds(), expected_refunds, "{decision:?} {start:?}");
        }
    }
}
