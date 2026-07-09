use std::sync::Arc;

use async_trait::async_trait;
use chrono::Utc;
use common_redis::{CustomRedisError, RedisClient};
use uuid::Uuid;

use crate::modes::processing::rules::rate_limit::BucketParams;

/// Outcome of one fused rate-limit call for a single issue group of `n` events.
/// `issue_admitted <= n` passed the per-issue limit; `team_admitted <= issue_admitted`
/// additionally passed the project limit. Everything beyond is dropped.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RateLimitDecision {
    pub issue_admitted: u32,
    pub team_admitted: u32,
}

/// Fused per-issue → per-team token bucket. Both keys carry a `{team_id}` hash
/// tag so a Redis Cluster colocates them on one slot. Per-issue is charged
/// first; the team bucket is debited only by what survives the per-issue limit,
/// so a per-issue drop never costs project budget. A limit whose `max` is
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

  -- Never regress `ts`. `now` is each pod's wall clock, so a pod with a lagging
  -- clock (now < stored ts) must not drag the timestamp backward, or the next
  -- forward call would compute an inflated `elapsed` and over-refill the bucket.
  -- Matches the non-regression guard in the Node.js token-bucket scripts.
  local ts_to_write = now
  if cur[1] ~= false and now < tonumber(cur[1]) then
    ts_to_write = tonumber(cur[1])
  end

  redis.call('hset', key, 'ts', ts_to_write, 'pool', tokens - admit)

  -- EXPIRE dispatch dominated this primitive's Redis CPU in prod, so refresh the TTL
  -- only on creation or once the remaining TTL drops below ttl/2, and write a 2x
  -- ceiling for headroom (mirrors the Node.js v3 token-bucket script). PTTL's -1 (no
  -- TTL) and -2 (missing key) are both below the threshold, so a lost TTL re-arms.
  if cur[1] == false or redis.call('pttl', key) < (ttl * 500) then
    redis.call('expire', key, ttl * 2)
  end
  return admit
end

local now = tonumber(ARGV[1])
local n   = tonumber(ARGV[2])

local issue_admitted = take(KEYS[1], n,              tonumber(ARGV[3]), tonumber(ARGV[4]), tonumber(ARGV[5]), now)
local team_admitted  = take(KEYS[2], issue_admitted, tonumber(ARGV[6]), tonumber(ARGV[7]), tonumber(ARGV[8]), now)

return { issue_admitted, team_admitted }
"#;

/// The single Redis operation the limiter needs: run the Lua script and decode
/// its integer-array reply. Behind a trait so the rate-limiting stage can be
/// unit-tested with an in-memory fake — including a failing one, to prove the
/// stage fails open. Production uses the real `RedisClient`.
#[async_trait]
pub trait ScriptRunner: Send + Sync {
    async fn eval_int_vec(
        &self,
        script: &str,
        keys: Vec<String>,
        args: Vec<String>,
    ) -> Result<Vec<i64>, CustomRedisError>;
}

#[async_trait]
impl ScriptRunner for RedisClient {
    async fn eval_int_vec(
        &self,
        script: &str,
        keys: Vec<String>,
        args: Vec<String>,
    ) -> Result<Vec<i64>, CustomRedisError> {
        RedisClient::eval_int_vec(self, script, keys, args).await
    }
}

pub struct RedisRateLimiter {
    redis: Arc<dyn ScriptRunner>,
    key_prefix: String,
    bucket_ttl_seconds: u64,
}

impl RedisRateLimiter {
    pub fn new(redis: Arc<dyn ScriptRunner>, key_prefix: String, bucket_ttl_seconds: u64) -> Self {
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

impl RedisRateLimiter {
    /// Charge `n` events for a team's (optional) issue against the configured
    /// per-issue and project limits, and report how many each limit admitted.
    pub async fn admit(
        &self,
        team_id: i32,
        issue_id: Option<Uuid>,
        per_issue: Option<BucketParams>,
        project: Option<BucketParams>,
        n: u32,
    ) -> Result<RateLimitDecision, CustomRedisError> {
        // Negative max disables a limit inside the script.
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

/// Rate-limiter tests against a real `redis:7-alpine` (via testcontainers), in
/// two layers:
///
/// - [`script`] — semi-unit tests that call `RATE_LIMIT_LUA` directly with an
///   explicit clock, pinning down the token-bucket primitive: capacity, refill,
///   the `floor` on partial tokens, disabling, and the per-issue→project order.
/// - [`scenarios`] — real-world stories told through a small DSL on top of the
///   public `admit` API, built up from a single limit to multiple teams.
///
/// Ignored by default (need Docker, slower). Run with:
/// ```sh
/// cargo test -p cymbal limiter::tests -- --ignored --test-threads=1
/// ```
#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::{CompressionConfig, RedisValueFormat};
    use std::time::Duration;
    use testcontainers::core::{IntoContainerPort, WaitFor};
    use testcontainers::runners::AsyncRunner;
    use testcontainers::{ContainerAsync, GenericImage};

    /// Boot a throwaway Redis and return a connected client. The readiness banner
    /// can land a hair before the socket accepts, so we probe with a trivial
    /// script until it answers — otherwise the first command occasionally races
    /// the container and flakes with "connection refused".
    async fn start_redis() -> (Arc<RedisClient>, ContainerAsync<GenericImage>) {
        let container = GenericImage::new("redis", "7-alpine")
            .with_exposed_port(6379.tcp())
            .with_wait_for(WaitFor::message_on_stdout("Ready to accept connections"))
            .start()
            .await
            .unwrap();
        let host = container.get_host().await.unwrap();
        let port = container.get_host_port_ipv4(6379).await.unwrap();
        let url = format!("redis://{host}:{port}");

        for _ in 0..20 {
            if let Ok(client) = RedisClient::with_config(
                url.clone(),
                CompressionConfig::disabled(),
                RedisValueFormat::Utf8,
                None,
                None,
            )
            .await
            {
                if client
                    .eval_int_vec("return {1, 1}", vec![], vec![])
                    .await
                    .is_ok()
                {
                    return (Arc::new(client), container);
                }
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        panic!("redis container never became ready");
    }

    // ===================================================================
    // Layer 1 — semi-unit tests: the token-bucket script, called directly.
    // ===================================================================
    mod script {
        use super::*;

        /// One token bucket's script inputs. `max < 0` disables the limit.
        #[derive(Clone, Copy)]
        struct Bucket {
            max: f64,
            rate: f64,
        }

        /// A bucket big enough to never be the binding limit in a test.
        fn unlimited() -> Bucket {
            Bucket {
                max: 1e9,
                rate: 0.0,
            }
        }

        /// A disabled limit — admits everything offered to it.
        fn disabled() -> Bucket {
            Bucket {
                max: -1.0,
                rate: 0.0,
            }
        }

        /// Inputs for one direct evaluation of `RATE_LIMIT_LUA`. Named fields so
        /// every number at the call site says what it is. It's `Copy`, so a test
        /// can set up a base and tweak one field: `Charge { now: 1003, ..base }`.
        #[derive(Clone, Copy)]
        struct Charge {
            team_id: i32,
            issue: &'static str,
            now: i64,
            n: u32,
            per_issue: Bucket,
            project: Bucket,
        }

        /// Evaluate the fused script directly with an explicit clock (so refill is
        /// deterministic — the public `admit` uses wall-clock time). Returns
        /// `(issue_admitted, team_admitted)`.
        async fn charge(client: &RedisClient, c: Charge) -> (i64, i64) {
            let keys = vec![
                format!("test/{{{}}}/issue/{}", c.team_id, c.issue),
                format!("test/{{{}}}/project", c.team_id),
            ];
            let args = vec![
                c.now.to_string(),
                c.n.to_string(),
                c.per_issue.max.to_string(),
                c.per_issue.rate.to_string(),
                "3600".to_string(),
                c.project.max.to_string(),
                c.project.rate.to_string(),
                "3600".to_string(),
            ];
            let res = client
                .eval_int_vec(RATE_LIMIT_LUA, keys, args)
                .await
                .unwrap();
            (res[0], res[1])
        }

        #[tokio::test]
        #[ignore]
        async fn fresh_bucket_admits_up_to_capacity() {
            let (client, _c) = start_redis().await;
            // 10 offered into a fresh per-issue bucket of capacity 5 (project
            // unlimited). A fresh bucket starts full, so exactly 5 pass.
            let admitted = charge(
                &client,
                Charge {
                    team_id: 1,
                    issue: "a",
                    now: 1000,
                    n: 10,
                    per_issue: Bucket {
                        max: 5.0,
                        rate: 0.0,
                    },
                    project: unlimited(),
                },
            )
            .await;
            assert_eq!(admitted.0, 5);
        }

        #[tokio::test]
        #[ignore]
        async fn depletes_then_refills_proportional_to_elapsed_time() {
            let (client, _c) = start_redis().await;
            // Capacity 5, refilling 1 token/sec. Only `now` changes between calls.
            let base = Charge {
                team_id: 2,
                issue: "a",
                now: 1000,
                n: 10,
                per_issue: Bucket {
                    max: 5.0,
                    rate: 1.0,
                },
                project: unlimited(),
            };
            assert_eq!(charge(&client, base).await.0, 5); // drains the bucket
            assert_eq!(charge(&client, base).await.0, 0); // same second: empty
            assert_eq!(charge(&client, Charge { now: 1003, ..base }).await.0, 3);
            // +3s -> +3 tokens
        }

        #[tokio::test]
        #[ignore]
        async fn refill_is_capped_at_capacity() {
            let (client, _c) = start_redis().await;
            // Capacity 5, refill 1/sec. Drain, then jump far ahead: unclamped that
            // would be millions of tokens, but the bucket clamps to `max`.
            let base = Charge {
                team_id: 3,
                issue: "a",
                now: 1000,
                n: 10,
                per_issue: Bucket {
                    max: 5.0,
                    rate: 1.0,
                },
                project: unlimited(),
            };
            assert_eq!(charge(&client, base).await.0, 5);
            assert_eq!(
                charge(
                    &client,
                    Charge {
                        now: 1_001_000_000,
                        ..base
                    }
                )
                .await
                .0,
                5
            );
        }

        #[tokio::test]
        #[ignore]
        async fn creates_bucket_with_double_ttl_ceiling() {
            let (client, _c) = start_redis().await;
            // `charge` passes ttl = 3600; a freshly created bucket must get the 2x
            // ceiling (7200s), proving the conditional EXPIRE armed the key. A key
            // with no TTL (-1) would be a Redis memory leak.
            let base = Charge {
                team_id: 30,
                issue: "a",
                now: 1000,
                n: 1,
                per_issue: Bucket {
                    max: 5.0,
                    rate: 0.0,
                },
                project: unlimited(),
            };
            charge(&client, base).await;

            let key = format!("test/{{{}}}/issue/{}", base.team_id, base.issue);
            let pttl_ms = client
                .eval_int_vec("return {redis.call('pttl', KEYS[1])}", vec![key], vec![])
                .await
                .unwrap()[0];
            // Between 1x and 2x ttl (ms): the 2x ceiling, not the old unconditional 1x.
            assert!(
                pttl_ms > 3_600_000 && pttl_ms <= 7_200_000,
                "expected a ~7200s TTL, got {pttl_ms}ms"
            );
        }

        #[tokio::test]
        #[ignore]
        async fn partial_tokens_carry_over_but_admit_floors() {
            let (client, _c) = start_redis().await;
            // Capacity 10, refilling 0.5 tokens/sec.
            let base = Charge {
                team_id: 4,
                issue: "a",
                now: 1000,
                n: 10,
                per_issue: Bucket {
                    max: 10.0,
                    rate: 0.5,
                },
                project: unlimited(),
            };
            assert_eq!(charge(&client, base).await.0, 10); // drain at t=1000
                                                           // +1s -> 0.5 tokens -> floor -> admit 0, but the 0.5 stays in the pool.
            assert_eq!(charge(&client, Charge { now: 1001, ..base }).await.0, 0);
            // +1s more -> 0.5 carried + 0.5 fresh = 1.0 -> admit 1.
            assert_eq!(charge(&client, Charge { now: 1002, ..base }).await.0, 1);
        }

        #[tokio::test]
        #[ignore]
        async fn negative_max_disables_the_limit() {
            let (client, _c) = start_redis().await;
            // Per-issue disabled admits everything; the project cap of 4 still
            // applies to the full batch.
            let admitted = charge(
                &client,
                Charge {
                    team_id: 5,
                    issue: "a",
                    now: 1000,
                    n: 10,
                    per_issue: disabled(),
                    project: Bucket {
                        max: 4.0,
                        rate: 0.0,
                    },
                },
            )
            .await;
            assert_eq!(admitted, (10, 4));
        }

        #[tokio::test]
        #[ignore]
        async fn charges_issue_bucket_before_project_bucket() {
            let (client, _c) = start_redis().await;
            // Per-issue cap 5, project cap 3. The issue bucket trims 10 -> 5, then
            // the project bucket sees only those 5 and admits 3: team <= issue <= n.
            let base = Charge {
                team_id: 6,
                issue: "a",
                now: 1000,
                n: 10,
                per_issue: Bucket {
                    max: 5.0,
                    rate: 0.0,
                },
                project: Bucket {
                    max: 3.0,
                    rate: 0.0,
                },
            };
            assert_eq!(charge(&client, base).await, (5, 3));
            // A different issue on the same team draws on the *shared* project
            // bucket, which is already drained — so nothing survives.
            assert_eq!(charge(&client, Charge { issue: "b", ..base }).await, (5, 0));
        }
    }

    // ===================================================================
    // Layer 2 — real-world scenarios, told through a small readable DSL.
    //
    // Limits here are fixed budgets with refill disabled, so each story is
    // about how a budget is *shared* (across issues, across teams), not about
    // timing. Read these top to bottom.
    // ===================================================================
    mod scenarios {
        use super::*;
        use std::sync::atomic::{AtomicI32, Ordering};

        /// One Redis-backed limiter plus a fresh team-id allocator. Hand out teams
        /// with `harness.team()`, configure their limits, then send events.
        struct TestHarness {
            limiter: Arc<RedisRateLimiter>,
            next_team_id: AtomicI32,
            _container: ContainerAsync<GenericImage>,
        }

        impl TestHarness {
            async fn new() -> Self {
                let (client, container) = start_redis().await;
                Self {
                    limiter: Arc::new(RedisRateLimiter::new(client, "et-scenario".into(), 3600)),
                    next_team_id: AtomicI32::new(1),
                    _container: container,
                }
            }

            /// A new team with no limits configured yet.
            fn team(&self) -> Team {
                Team {
                    limiter: self.limiter.clone(),
                    team_id: self.next_team_id.fetch_add(1, Ordering::Relaxed),
                    per_issue: None,
                    project: None,
                }
            }
        }

        /// A team with its configured limits. `send` returns how many events the
        /// limiter accepted, so a test reads like "send 10, expect 3 accepted".
        struct Team {
            limiter: Arc<RedisRateLimiter>,
            team_id: i32,
            per_issue: Option<BucketParams>,
            project: Option<BucketParams>,
        }

        impl Team {
            /// Cap the *whole team* to `capacity` events (shared across all issues).
            fn with_project_limit(mut self, capacity: u32) -> Self {
                self.project = Some(budget(capacity));
                self
            }

            /// Cap *each issue* to `capacity` events independently.
            fn with_issue_limit(mut self, capacity: u32) -> Self {
                self.per_issue = Some(budget(capacity));
                self
            }

            /// Send `n` events for `issue`; returns how many were accepted (passed
            /// both the per-issue and project limits).
            async fn send(&self, issue: Issue, n: u32) -> u32 {
                self.limiter
                    .admit(self.team_id, Some(issue.0), self.per_issue, self.project, n)
                    .await
                    .unwrap()
                    .team_admitted
            }
        }

        /// A fixed budget of `capacity` events with refill disabled.
        fn budget(capacity: u32) -> BucketParams {
            BucketParams {
                max: capacity as f64,
                rate: 0.0,
            }
        }

        /// A distinct issue. Bind it to a name (`let issue_a = Issue::new();`) so
        /// scenarios read naturally.
        #[derive(Clone, Copy)]
        struct Issue(Uuid);

        impl Issue {
            fn new() -> Self {
                Self(Uuid::now_v7())
            }
        }

        #[tokio::test]
        #[ignore]
        async fn a_project_limit_caps_total_volume_across_all_issues() {
            let harness = TestHarness::new().await;
            // The team allows 5 events total, regardless of which issue they hit.
            let team = harness.team().with_project_limit(5);
            let (issue_a, issue_b) = (Issue::new(), Issue::new());

            // The shared budget is spent in arrival order, across any issue...
            assert_eq!(team.send(issue_a, 3).await, 3);
            assert_eq!(team.send(issue_b, 2).await, 2);
            // ...and once it's gone, everything else is dropped.
            assert_eq!(team.send(issue_a, 5).await, 0);
            assert_eq!(team.send(issue_b, 5).await, 0);
        }

        #[tokio::test]
        #[ignore]
        async fn an_issue_limit_applies_separately_to_each_issue() {
            let harness = TestHarness::new().await;
            // Each issue gets 3 events; there is no team-wide cap.
            let team = harness.team().with_issue_limit(3);
            let (issue_a, issue_b) = (Issue::new(), Issue::new());

            // Every issue has its own budget...
            assert_eq!(team.send(issue_a, 10).await, 3);
            assert_eq!(team.send(issue_b, 10).await, 3);
            // ...and a noisy issue can't borrow from another's.
            assert_eq!(team.send(issue_a, 10).await, 0);
        }

        #[tokio::test]
        #[ignore]
        async fn mixed_limits_charge_per_issue_first_then_the_project_budget() {
            let harness = TestHarness::new().await;
            // Each issue is capped at 3, and the team as a whole at 5.
            let team = harness.team().with_issue_limit(3).with_project_limit(5);
            let (issue_a, issue_b, issue_c) = (Issue::new(), Issue::new(), Issue::new());

            // Issue A is trimmed to 3 by its own limit (the team still has room).
            assert_eq!(team.send(issue_a, 10).await, 3);
            // Issue B's own limit allows 3, but only 2 of the team budget remain.
            assert_eq!(team.send(issue_b, 10).await, 2);
            // Team budget exhausted: a brand-new issue gets nothing, even though its
            // own per-issue budget is untouched.
            assert_eq!(team.send(issue_c, 10).await, 0);
        }

        #[tokio::test]
        #[ignore]
        async fn each_team_has_its_own_independent_budget() {
            let harness = TestHarness::new().await;
            // Two teams, each capped at 4 events.
            let team_one = harness.team().with_project_limit(4);
            let team_two = harness.team().with_project_limit(4);
            let issue = Issue::new();

            // Team one spends its whole budget...
            assert_eq!(team_one.send(issue, 10).await, 4);
            assert_eq!(team_one.send(issue, 10).await, 0);
            // ...which leaves team two completely untouched.
            assert_eq!(team_two.send(issue, 10).await, 4);
        }

        #[tokio::test]
        #[ignore]
        async fn a_busy_issue_cannot_starve_the_rest_of_the_team_or_other_teams() {
            let harness = TestHarness::new().await;
            // A larger team: 5 per issue, 8 across the whole project.
            let big = harness.team().with_issue_limit(5).with_project_limit(8);
            let (a, b, c) = (Issue::new(), Issue::new(), Issue::new());

            // Two issues fill the team budget (5 + 3 = 8); the project cap is the
            // real ceiling, so the third issue is shut out despite its free
            // per-issue budget.
            assert_eq!(big.send(a, 5).await, 5);
            assert_eq!(big.send(b, 5).await, 3);
            assert_eq!(big.send(c, 5).await, 0);

            // A second, smaller team (2 per issue, 3 project) is wholly unaffected
            // by the big team draining its own buckets.
            let small = harness.team().with_issue_limit(2).with_project_limit(3);
            assert_eq!(small.send(a, 10).await, 2);
            assert_eq!(small.send(b, 10).await, 1);
        }
    }
}
