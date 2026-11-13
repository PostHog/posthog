//! Per-issue exception counts in fixed buckets, shared by the rules that need rolling windows.

use common_redis::{CustomRedisError, ScriptRunner};
use uuid::Uuid;

// Each window owns a run of KEYS, newest bucket first, and three ARGV entries: the run length, the bucket expiry,
// and whether it counts issues. The reply holds, per window and per bucket: the team total, then for a window
// that counts issues the number of fields and one count per issue.
const RECORD_LUA: &str = r#"
local windows = tonumber(ARGV[1])
local first_issue = 2 + 3 * windows
local issues = {}
local total = 0
for arg = first_issue, #ARGV, 2 do
  issues[#issues + 1] = ARGV[arg]
  total = total + tonumber(ARGV[arg + 1])
end
-- unpack() fails past the Lua stack limit of a few thousand values, after the increments are already written.
local chunk = 1000

local out = {}
local key = 1
for window = 0, windows - 1 do
  local buckets = tonumber(ARGV[2 + 3 * window])
  local per_issue = ARGV[4 + 3 * window] == '1'
  local current = KEYS[key]
  local created = redis.call('exists', current) == 0
  if per_issue then
    for arg = first_issue, #ARGV, 2 do
      redis.call('hincrby', current, ARGV[arg], ARGV[arg + 1])
    end
  end
  redis.call('hincrby', current, '_n', total)
  if created then
    redis.call('expire', current, tonumber(ARGV[3 + 3 * window]))
  end
  for bucket = 0, buckets - 1 do
    local bucket_key = KEYS[key + bucket]
    out[#out + 1] = tonumber(redis.call('hget', bucket_key, '_n')) or 0
    if per_issue then
      out[#out + 1] = redis.call('hlen', bucket_key)
      for first = 1, #issues, chunk do
        local last = math.min(first + chunk - 1, #issues)
        local counts = redis.call('hmget', bucket_key, unpack(issues, first, last))
        for index = 1, #counts do
          out[#out + 1] = tonumber(counts[index]) or 0
        end
      end
    end
  end
  key = key + buckets
end
return out
"#;

/// Every window of one width must use the same number of buckets, because the first writer of a bucket sets its expiry.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Window {
    pub width_seconds: i64,
    pub buckets: usize,
    /// A window that keeps the team total only costs one field per bucket, so it can cover many days.
    pub per_issue: bool,
}

impl Window {
    // One bucket beyond the window: the rolling count needs the part of it that the window still covers.
    fn stored_buckets(&self) -> usize {
        self.buckets + 1
    }
}

/// Counts in consecutive buckets, newest first. The first bucket is still open.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Series {
    pub window: Window,
    pub counts: Vec<u64>,
}

impl Series {
    pub fn current(&self) -> u64 {
        self.counts[0]
    }

    /// The oldest bucket counts for the share of it that the window ending at `now` still covers.
    /// This assumes that its events were spread evenly.
    pub fn rolling(&self, now: i64) -> f64 {
        let elapsed = now.rem_euclid(self.window.width_seconds) as f64;
        let covered = 1.0 - elapsed / self.window.width_seconds as f64;
        let (oldest, inside) = self
            .counts
            .split_last()
            .expect("a series has one bucket or more");
        inside.iter().sum::<u64>() as f64 + *oldest as f64 * covered
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WindowCounts {
    pub team: Series,
    pub active_issues: Vec<u64>,
    /// One series per input issue, in input order.
    pub issues: Vec<Series>,
}

#[derive(Debug, Clone)]
pub struct Ledger {
    pub windows: Vec<Window>,
}

impl Ledger {
    /// Returns one entry per window. `issue_counts` holds each issue once, and the returned counts include it.
    pub async fn record(
        &self,
        redis: &dyn ScriptRunner,
        team_id: i32,
        now: i64,
        issue_counts: &[(Uuid, u32)],
    ) -> Result<Vec<WindowCounts>, CustomRedisError> {
        let mut keys = Vec::new();
        let mut args = vec![self.windows.len().to_string()];
        for window in &self.windows {
            let width = window.width_seconds;
            let current = now.div_euclid(width);
            keys.extend(
                (0..window.stored_buckets() as i64)
                    .map(|age| format!("et:c1:{{{team_id}}}:b:{width}:{}", current - age)),
            );
            args.push(window.stored_buckets().to_string());
            args.push(((window.stored_buckets() as i64 + 1) * width).to_string());
            args.push(u8::from(window.per_issue).to_string());
        }
        for (issue_id, events) in issue_counts {
            args.push(issue_id.to_string());
            args.push(events.to_string());
        }

        let reply = redis.eval_int_vec(RECORD_LUA, keys, args).await?;
        let total: u64 = issue_counts.iter().map(|(_, n)| u64::from(*n)).sum();
        self.decode(&reply, total, issue_counts.len())
            .ok_or_else(|| CustomRedisError::ParseError("invalid ledger reply".into()))
    }

    fn decode(&self, reply: &[i64], total: u64, issues: usize) -> Option<Vec<WindowCounts>> {
        let mut values = reply.iter().map(|value| u64::try_from(*value).ok());
        let mut next = || values.next().flatten();
        let mut decoded = Vec::with_capacity(self.windows.len());
        for window in &self.windows {
            let mut team = Vec::new();
            let mut active_issues = Vec::new();
            let mut per_issue = vec![Vec::new(); if window.per_issue { issues } else { 0 }];
            for _ in 0..window.stored_buckets() {
                team.push(next()?);
                if !window.per_issue {
                    continue;
                }
                // The team total is a field of the bucket, not an issue.
                active_issues.push(next()?.saturating_sub(1));
                for counts in &mut per_issue {
                    counts.push(next()?);
                }
            }
            if team[0] < total {
                return None;
            }
            let series = |counts| Series {
                window: *window,
                counts,
            };
            decoded.push(WindowCounts {
                team: series(team),
                active_issues,
                issues: per_issue.into_iter().map(series).collect(),
            });
        }
        values.next().is_none().then_some(decoded)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::{start_redis, FakeRunner};

    const FIVE_MINUTES: Window = Window {
        width_seconds: 300,
        buckets: 2,
        per_issue: true,
    };
    const HOURLY: Window = Window {
        width_seconds: 3_600,
        buckets: 24,
        per_issue: true,
    };
    const DAILY_TEAM_ONLY: Window = Window {
        width_seconds: 86_400,
        buckets: 2,
        per_issue: false,
    };

    fn ledger() -> Ledger {
        Ledger {
            windows: vec![FIVE_MINUTES, HOURLY],
        }
    }

    #[test]
    fn rolling_count_weighs_the_oldest_bucket_by_its_share_inside_the_window() {
        let series = Series {
            window: FIVE_MINUTES,
            counts: vec![4, 10, 100],
        };
        assert_eq!(series.current(), 4);
        assert_eq!(series.rolling(600), 114.0);
        assert_eq!(series.rolling(600 + 75), 89.0);
        assert!((series.rolling(600 + 299) - (14.0 + 100.0 / 300.0)).abs() < 1e-9);
    }

    #[tokio::test]
    async fn rejects_a_reply_that_does_not_match_the_batch() {
        let ledger = Ledger {
            windows: vec![FIVE_MINUTES],
        };
        let batch = [(Uuid::now_v7(), 2)];
        let valid = vec![2, 2, 2, 0, 0, 0, 0, 0, 0];
        assert!(ledger
            .record(&*FakeRunner::returning(valid.clone()), 7, 0, &batch)
            .await
            .is_ok());
        for reply in [
            valid[..8].to_vec(),
            valid.iter().copied().chain([0]).collect(),
            std::iter::once(-1).chain(valid[1..].to_vec()).collect(),
            std::iter::once(1).chain(valid[1..].to_vec()).collect(),
        ] {
            let result = ledger
                .record(&*FakeRunner::returning(reply), 7, 0, &batch)
                .await;
            assert!(result.is_err());
        }
    }

    #[tokio::test]
    #[ignore = "requires Docker for Redis container"]
    async fn counts_issues_per_bucket_and_slides_old_buckets_out() {
        let (redis, _container) = start_redis().await;
        let (noisy, quiet) = (Uuid::now_v7(), Uuid::now_v7());
        let ledger = ledger();

        let first = ledger
            .record(&*redis, 7, 0, &[(noisy, 5), (quiet, 1)])
            .await
            .unwrap();
        assert_eq!(first[0].team.counts, [6, 0, 0]);
        assert_eq!(first[0].active_issues, [2, 0, 0]);
        assert_eq!(first[0].issues[0].counts, [5, 0, 0]);
        assert_eq!(first[1].issues[1].current(), 1);

        let with_days = Ledger {
            windows: vec![DAILY_TEAM_ONLY],
        };
        let days = with_days
            .record(&*redis, 9, 86_400, &[(noisy, 5), (quiet, 1)])
            .await
            .unwrap();
        assert_eq!(days[0].team.counts, [6, 0, 0]);
        assert!(days[0].issues.is_empty() && days[0].active_issues.is_empty());
        let fields = redis
            .eval_int_vec(
                "return { redis.call('hlen', KEYS[1]) }",
                vec!["et:c1:{9}:b:86400:1".into()],
                vec![],
            )
            .await
            .unwrap();
        assert_eq!(fields, [1]);

        let other_team = ledger.record(&*redis, 8, 0, &[(noisy, 3)]).await.unwrap();
        assert_eq!(other_team[0].team.counts, [3, 0, 0]);

        let next_bucket = ledger.record(&*redis, 7, 300, &[(noisy, 2)]).await.unwrap();
        assert_eq!(next_bucket[0].issues[0].counts, [2, 5, 0]);
        assert_eq!(next_bucket[0].active_issues, [1, 2, 0]);
        assert_eq!(next_bucket[1].issues[0].current(), 7);

        let slid_out = ledger.record(&*redis, 7, 900, &[(noisy, 1)]).await.unwrap();
        assert_eq!(slid_out[0].issues[0].counts, [1, 0, 2]);
        assert_eq!(slid_out[1].issues[0].rolling(900), 8.0);

        let next_hour = ledger
            .record(&*redis, 7, 3_600, &[(noisy, 1)])
            .await
            .unwrap();
        assert_eq!(next_hour[1].issues[0].counts[..2], [1, 8]);
        assert_eq!(next_hour[1].team.counts[..2], [1, 9]);
    }

    #[tokio::test]
    #[ignore = "requires Docker for Redis container"]
    async fn records_a_batch_with_more_issues_than_the_lua_stack_holds() {
        let (redis, _container) = start_redis().await;
        let batch: Vec<_> = (0..10_000).map(|_| (Uuid::now_v7(), 1)).collect();
        let counts = ledger().record(&*redis, 7, 0, &batch).await.unwrap();
        assert_eq!(counts[0].team.current(), 10_000);
        assert_eq!(counts[0].active_issues[0], 10_000);
        assert!(counts[1].issues.iter().all(|issue| issue.current() == 1));
    }

    #[tokio::test]
    #[ignore = "requires Docker for Redis container"]
    async fn buckets_expire_one_width_after_they_leave_the_window() {
        let (redis, _container) = start_redis().await;
        let ledger = ledger();
        for _ in 0..2 {
            ledger
                .record(&*redis, 7, 0, &[(Uuid::now_v7(), 1)])
                .await
                .unwrap();
        }
        let ttl = |key: &str| {
            let redis = redis.clone();
            let key = key.to_string();
            async move {
                redis
                    .eval_int_vec("return { redis.call('ttl', KEYS[1]) }", vec![key], vec![])
                    .await
                    .unwrap()[0]
            }
        };
        let five_minutes = ttl("et:c1:{7}:b:300:0").await;
        assert!((1_100..=1_200).contains(&five_minutes));
        let hourly = ttl("et:c1:{7}:b:3600:0").await;
        assert!((93_000..=93_600).contains(&hourly));
    }
}
