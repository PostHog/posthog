use std::sync::Arc;

use async_trait::async_trait;
use chrono::Utc;
use common_redis::{CustomRedisError, RedisClient};
use uuid::Uuid;

use crate::modes::processing::rules::rate_limit::TierParams;

/// Outcome of one fused rate-limit call for a single issue group of `n` events.
/// `issue_admitted <= n` passed the per-issue tier; `team_admitted <= issue_admitted`
/// additionally passed the project tier. Everything beyond is dropped.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RateLimitDecision {
    pub issue_admitted: u32,
    pub team_admitted: u32,
}

/// Position-independent rate-limit primitive: given a team, an (optional) issue,
/// and the configured tier params, charge `n` events and report how many each
/// tier admitted. Lives behind a trait so the pipeline stage can be tested with
/// a fake, and so a future pre-resolution early-drop can reuse the same buckets.
#[async_trait]
pub trait RateLimiter: Send + Sync {
    async fn admit(
        &self,
        team_id: i32,
        issue_id: Option<Uuid>,
        per_issue: Option<TierParams>,
        project: Option<TierParams>,
        n: u32,
    ) -> Result<RateLimitDecision, CustomRedisError>;
}

/// Fused per-issue → per-team token bucket. Both keys carry a `{team_id}` hash
/// tag so a Redis Cluster colocates them on one slot. Per-issue is charged
/// first; the team bucket is debited only by what survives the per-issue tier,
/// so a per-issue drop never costs project budget. A tier whose `max` is
/// negative is disabled (admits everything offered to it).
pub const RATE_LIMIT_LUA: &str = r#"
local function take(key, want, max, rate, ttl, now)
  if want <= 0 then return 0 end
  if max < 0 then return want end

  local cur = redis.call('hmget', key, 'ts', 'pool')
  local tokens
  if cur[1] == false then
    tokens = max
  else
    local elapsed = now - tonumber(cur[1])
    if elapsed < 0 then elapsed = 0 end
    tokens = tonumber(cur[2]) + elapsed * rate
    if tokens > max then tokens = max end
  end

  local admit = math.floor(tokens)
  if admit > want then admit = want end

  redis.call('hset', key, 'ts', now, 'pool', tokens - admit)
  redis.call('expire', key, ttl)
  return admit
end

local now = tonumber(ARGV[1])
local n   = tonumber(ARGV[2])

local issue_admitted = take(KEYS[1], n,              tonumber(ARGV[3]), tonumber(ARGV[4]), tonumber(ARGV[5]), now)
local team_admitted  = take(KEYS[2], issue_admitted, tonumber(ARGV[6]), tonumber(ARGV[7]), tonumber(ARGV[8]), now)

return { issue_admitted, team_admitted }
"#;

pub struct RedisRateLimiter {
    redis: Arc<RedisClient>,
    key_prefix: String,
    bucket_ttl_seconds: u64,
}

impl RedisRateLimiter {
    pub fn new(redis: Arc<RedisClient>, key_prefix: String, bucket_ttl_seconds: u64) -> Self {
        Self {
            redis,
            key_prefix,
            bucket_ttl_seconds,
        }
    }

    fn issue_key(&self, team_id: i32, issue_id: Option<Uuid>) -> String {
        match issue_id {
            Some(id) => format!("{}/{{{team_id}}}/issue/{id}", self.key_prefix),
            None => format!("{}/{{{team_id}}}/issue/none", self.key_prefix),
        }
    }

    fn team_key(&self, team_id: i32) -> String {
        format!("{}/{{{team_id}}}/project", self.key_prefix)
    }
}

#[async_trait]
impl RateLimiter for RedisRateLimiter {
    async fn admit(
        &self,
        team_id: i32,
        issue_id: Option<Uuid>,
        per_issue: Option<TierParams>,
        project: Option<TierParams>,
        n: u32,
    ) -> Result<RateLimitDecision, CustomRedisError> {
        // Negative max disables a tier inside the script.
        let (issue_max, issue_rate) = per_issue.map_or((-1.0, 0.0), |t| (t.max, t.rate));
        let (team_max, team_rate) = project.map_or((-1.0, 0.0), |t| (t.max, t.rate));
        let now = Utc::now().timestamp();

        let keys = vec![self.issue_key(team_id, issue_id), self.team_key(team_id)];
        let args = vec![
            now.to_string(),
            n.to_string(),
            issue_max.to_string(),
            issue_rate.to_string(),
            self.bucket_ttl_seconds.to_string(),
            team_max.to_string(),
            team_rate.to_string(),
            self.bucket_ttl_seconds.to_string(),
        ];

        let res = self.redis.eval_int_vec(RATE_LIMIT_LUA, keys, args).await?;

        // Defensive clamps: team_admitted <= issue_admitted <= n.
        let issue_admitted = (res.first().copied().unwrap_or(0).max(0) as u32).min(n);
        let team_admitted = (res.get(1).copied().unwrap_or(0).max(0) as u32).min(issue_admitted);
        Ok(RateLimitDecision {
            issue_admitted,
            team_admitted,
        })
    }
}
