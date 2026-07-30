use std::sync::Arc;

use tracing::warn;

use crate::metric_consts::{NEW_ISSUE_LIMIT_EXCEEDED, NEW_ISSUE_LIMIT_FAIL_OPEN};
use crate::modes::processing::rules::rate_limit::BucketParams;
use crate::modes::processing::stages::rate_limiting::{RedisRateLimiter, ScriptRunner};

/// Per-team guard on *new issue creation*, distinct from the per-issue and
/// project exception limits: those cap events against an issue that already
/// exists, which is no defence against a team whose exceptions carry something
/// dynamic that survives normalization, so every event fingerprints uniquely and
/// mints its own issue.
///
/// The budget is charged whether or not enforcement is on, so a runaway team
/// shows up in `NEW_ISSUE_LIMIT_EXCEEDED` either way. With enforcement off the
/// decision is reported and ignored.
pub struct NewIssueLimiter {
    limiter: RedisRateLimiter,
    bucket: BucketParams,
    enforced: bool,
}

impl NewIssueLimiter {
    /// `limit` new issues per `bucket_minutes` per team. The bucket is sized to
    /// `limit` (so a team can burst its whole budget) and refills steadily over
    /// the window.
    pub fn new(
        redis: Arc<dyn ScriptRunner>,
        key_prefix: String,
        limit: u32,
        bucket_minutes: u32,
        enforced: bool,
    ) -> Self {
        let window_seconds = f64::from(bucket_minutes.max(1)) * 60.0;
        Self {
            limiter: RedisRateLimiter::new(redis, key_prefix, window_seconds as u64),
            bucket: BucketParams {
                max: f64::from(limit),
                rate: f64::from(limit) / window_seconds,
            },
            enforced,
        }
    }

    /// Charges one new issue against the team's budget. `false` means the team is
    /// over budget *and* enforcement is on — the caller must not create the
    /// issue. Fails open: a Redis error never blocks issue creation.
    pub async fn admit_new_issue(&self, team_id: i32) -> bool {
        // `None` per-issue params disable that half of the fused script, so only
        // the team bucket is charged.
        let decision = match self
            .limiter
            .admit(team_id, None, None, Some(self.bucket), 1)
            .await
        {
            Ok(decision) => decision,
            Err(error) => {
                metrics::counter!(NEW_ISSUE_LIMIT_FAIL_OPEN).increment(1);
                warn!(team_id, error = %error, "new-issue limiter unavailable, allowing creation");
                return true;
            }
        };

        if decision.team_admitted > 0 {
            return true;
        }

        metrics::counter!(NEW_ISSUE_LIMIT_EXCEEDED, "enforced" => if self.enforced { "true" } else { "false" }).increment(1);
        warn!(
            team_id,
            enforced = self.enforced,
            "team is over its new-issue creation budget"
        );
        !self.enforced
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use async_trait::async_trait;
    use common_redis::CustomRedisError;
    use std::sync::Mutex;

    /// A script runner that replays canned replies, so the limiter's own
    /// behavior (enforcement, fail-open) is testable without Redis. The
    /// token-bucket script itself is covered in `rate_limiting::limiter`.
    struct FakeRunner {
        replies: Mutex<Vec<Result<Vec<i64>, CustomRedisError>>>,
    }

    impl FakeRunner {
        fn returning(replies: Vec<Result<Vec<i64>, CustomRedisError>>) -> Arc<Self> {
            Arc::new(Self {
                replies: Mutex::new(replies),
            })
        }
    }

    #[async_trait]
    impl ScriptRunner for FakeRunner {
        async fn eval_int_vec(
            &self,
            _script: &str,
            _keys: Vec<String>,
            _args: Vec<String>,
        ) -> Result<Vec<i64>, CustomRedisError> {
            self.replies.lock().unwrap().remove(0)
        }
    }

    fn limiter(
        replies: Vec<Result<Vec<i64>, CustomRedisError>>,
        enforced: bool,
    ) -> NewIssueLimiter {
        NewIssueLimiter::new(
            FakeRunner::returning(replies),
            "test".into(),
            1,
            60,
            enforced,
        )
    }

    #[tokio::test]
    async fn admits_a_team_inside_its_budget() {
        assert!(limiter(vec![Ok(vec![1, 1])], true).admit_new_issue(7).await);
    }

    #[tokio::test]
    async fn blocks_an_over_budget_team_only_when_enforcement_is_on() {
        let enforcing = limiter(vec![Ok(vec![1, 0])], true);
        let observing = limiter(vec![Ok(vec![1, 0])], false);

        assert!(!enforcing.admit_new_issue(7).await);
        assert!(observing.admit_new_issue(7).await);
    }

    #[tokio::test]
    async fn fails_open_when_redis_is_unavailable() {
        let replies = vec![Err(CustomRedisError::Timeout)];
        assert!(limiter(replies, true).admit_new_issue(7).await);
    }
}
