//! What drops data before it is buffered: the event ingestion restrictions the replay lanes read from Redis, and v4's
//! own new-session rate limiter with the main lane's rules.

use std::borrow::Cow;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use capture::event_restrictions::{
    EventContext, EventRestrictionService, EventRestrictionsRepository, Pipeline,
    RedisRestrictionsRepository,
};
use common_redis::{
    Client, CompressionConfig, CustomRedisError, PipelineCommand, RedisClient, RedisValueFormat,
};
use metrics::counter;

use crate::batch::SessionKey;
use crate::process::{normalize_session_id, Headers, Restriction};

const REDIS_TIMEOUT: Duration = Duration::from_secs(5);

/// The `session_recordings` restrictions, refreshed in the background as capture refreshes them.
#[derive(Clone)]
pub struct Restrictions {
    service: EventRestrictionService,
}

impl Default for Restrictions {
    fn default() -> Self {
        // The replay lanes keep the last list they read while Redis is away. A stale list never turns into no list.
        Self {
            service: EventRestrictionService::new(
                vec![Pipeline::SessionRecordings],
                Duration::from_secs(10 * 365 * 86_400),
            ),
        }
    }
}

impl Restrictions {
    pub async fn refresh_forever(
        self,
        redis_url: String,
        interval: Duration,
        handle: lifecycle::Handle,
    ) {
        self.service
            .start_refresh_task(
                || {
                    let url = redis_url.clone();
                    async move {
                        let repository: Arc<dyn EventRestrictionsRepository> = Arc::new(
                            RedisRestrictionsRepository::new(
                                url,
                                Some(REDIS_TIMEOUT),
                                Some(REDIS_TIMEOUT),
                            )
                            .await?,
                        );
                        Ok(repository)
                    }
                },
                interval,
                handle,
            )
            .await;
    }

    /// Before the first load every message would pass, so the recorder waits for it.
    pub async fn wait_loaded(&self, timeout: Duration) -> bool {
        let deadline = tokio::time::Instant::now() + timeout;
        while !self.service.has_loaded() {
            if tokio::time::Instant::now() >= deadline {
                return false;
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        true
    }

    /// Matches on the headers as the main lane's `parseEventHeaders` reads them: NUL replaced in the token, distinct
    /// ID and session ID, and a UUID session ID in lower case.
    pub async fn get(&self, headers: &Headers<'_>, now_ts: i64) -> Restriction {
        let Some(token) = headers.token.map(sanitize) else {
            return Restriction::default();
        };
        let distinct_id = headers.distinct_id.map(sanitize);
        let session_id = headers.session_id.map(sanitize);
        let session_id = session_id.as_deref().map(normalize_session_id);
        let context = EventContext {
            distinct_id: distinct_id.as_deref(),
            session_id: session_id.as_deref(),
            event_name: headers.event,
            event_uuid: headers.uuid,
            now_ts,
        };
        let applied = self
            .service
            .get_restrictions(&token, &context, Pipeline::SessionRecordings)
            .await;
        Restriction {
            drop: applied.should_drop(),
            dlq: applied.redirect_to_dlq(),
            force_overflow: applied.force_overflow(),
        }
    }
}

fn sanitize(value: &str) -> Cow<'_, str> {
    if value.contains('\0') {
        Cow::Owned(value.replace('\0', "\u{FFFD}"))
    } else {
        Cow::Borrowed(value)
    }
}

/// The seen and blocked keys of v4's own limiter. Its namespace keeps them apart from the main lane's and the v3
/// mirror's, as the mirror keeps its own.
const SEEN_PREFIX: &str = "@posthog/ai-research-v4/session-seen";
const BLOCKED_PREFIX: &str = "@posthog/ai-research-v4/session-blocked";

/// The main lane's TTL for both keys: twice the longest session.
const STATE_TTL_SECS: u64 = 2 * 24 * 3600;

/// The main lane's local caches in front of Redis. They are LRU, as the main lane's are: the limiter asks for a seen
/// session with `contains_key`, which does not count as a read, so moka's default policy would refuse every new
/// session once the cache is full.
const LOCAL_CACHE_SIZE: u64 = 100_000;
const LOCAL_CACHE_TTL: Duration = Duration::from_secs(300);

/// One poll batch's reads and writes together. A Redis that does not answer delays each batch by this much at most.
const LIMITER_DEADLINE: Duration = Duration::from_secs(1);

fn local_cache<V: Clone + Send + Sync + 'static>() -> moka::sync::Cache<SessionKey, V> {
    moka::sync::Cache::builder()
        .max_capacity(LOCAL_CACHE_SIZE)
        .time_to_live(LOCAL_CACHE_TTL)
        .eviction_policy(moka::policy::EvictionPolicy::lru())
        .build()
}

fn state_key(prefix: &str, session: &SessionKey) -> String {
    format!("{prefix}:{}:{}", session.team_id, session.session_id)
}

/// A token bucket per team, as the main lane's `Limiter`.
struct Buckets {
    capacity: f64,
    replenish_per_sec: f64,
    teams: HashMap<i64, (f64, tokio::time::Instant)>,
}

impl Buckets {
    fn take(&mut self, team_id: i64, now: tokio::time::Instant) -> bool {
        let (tokens, at) = self.teams.entry(team_id).or_insert((self.capacity, now));
        let refill = now.saturating_duration_since(*at).as_secs_f64() * self.replenish_per_sec;
        *tokens = (*tokens + refill).min(self.capacity);
        *at = now;
        if *tokens < 1.0 {
            return false;
        }
        *tokens -= 1.0;
        true
    }
}

/// The main lane's new-session rate limiter, run by v4 for itself. Each team's new sessions on the main topic take a
/// token from its bucket, and a session denied one is blocked as a whole, so v4 never keeps half of it.
///
/// The replay overflow lane enforces the same blocklist, but its own limiter only counts. v4 does the same: a session
/// first seen on the overflow topic is never blocked for its own rate. Seen and blocked state is shared by both topics.
///
/// Redis errors fail open, as in the main lane: a session whose state is unknown is not blocked, and a block that
/// is not written holds in this process.
pub struct SessionLimiter {
    redis: Arc<dyn Client + Send + Sync>,
    /// The main topic's buckets, then the overflow topic's, which only count.
    buckets: Mutex<[Buckets; 2]>,
    blocking_enabled: bool,
    seen: moka::sync::Cache<SessionKey, ()>,
    blocked: moka::sync::Cache<SessionKey, bool>,
}

impl SessionLimiter {
    pub async fn connect(
        redis_url: String,
        capacity: f64,
        replenish_per_sec: f64,
        blocking_enabled: bool,
    ) -> Result<Self, CustomRedisError> {
        let redis = RedisClient::with_config(
            redis_url,
            CompressionConfig::disabled(),
            RedisValueFormat::Utf8,
            Some(LIMITER_DEADLINE),
            Some(LIMITER_DEADLINE),
        )
        .await?;
        Ok(Self::new(
            Arc::new(redis),
            capacity,
            replenish_per_sec,
            blocking_enabled,
        ))
    }

    pub fn new(
        redis: Arc<dyn Client + Send + Sync>,
        capacity: f64,
        replenish_per_sec: f64,
        blocking_enabled: bool,
    ) -> Self {
        Self {
            redis,
            buckets: Mutex::new(std::array::from_fn(|_| Buckets {
                capacity,
                replenish_per_sec,
                teams: HashMap::new(),
            })),
            blocking_enabled,
            seen: local_cache(),
            blocked: local_cache(),
        }
    }

    /// Returns which of a poll batch's sessions are blocked. Each session maps to true when a message of it came from
    /// the main topic. A session is new when it is neither seen nor blocked, and only a new session takes a token, so
    /// a blocked session does not drain its team's bucket.
    pub async fn blocked(&self, sessions: &BTreeMap<SessionKey, bool>) -> HashSet<SessionKey> {
        let deadline = tokio::time::Instant::now() + LIMITER_DEADLINE;
        let mut blocked = HashSet::new();
        let mut seen = HashSet::new();
        let mut reads: Vec<(String, bool, &SessionKey)> = Vec::new();
        for session in sessions.keys() {
            if self.seen.contains_key(session) {
                seen.insert(session);
            } else {
                reads.push((state_key(SEEN_PREFIX, session), false, session));
            }
            match self.blocked.get(session) {
                Some(true) => {
                    blocked.insert(session.clone());
                }
                Some(false) => {}
                None => reads.push((state_key(BLOCKED_PREFIX, session), true, session)),
            }
        }
        let mut unknown = HashSet::new();
        if !reads.is_empty() {
            let keys = reads.iter().map(|(key, _, _)| key.clone()).collect();
            match self.call(deadline, self.redis.mget(keys)).await {
                Ok(values) => {
                    for ((_, is_block, session), value) in reads.iter().zip(values) {
                        let set = value.is_some();
                        if *is_block {
                            self.blocked.insert((*session).clone(), set);
                            if set {
                                blocked.insert((*session).clone());
                            }
                        } else if set {
                            self.seen.insert((*session).clone(), ());
                            seen.insert(session);
                        }
                    }
                }
                Err(()) => unknown.extend(reads.iter().map(|(_, _, session)| *session)),
            }
        }

        let now = tokio::time::Instant::now();
        let mut writes = Vec::new();
        {
            let mut buckets = self.buckets.lock().unwrap();
            for (session, &main) in sessions {
                if seen.contains(session) || blocked.contains(session) || unknown.contains(session)
                {
                    continue;
                }
                counter!("ai_research_v4_recorder_new_sessions_total").increment(1);
                let blocking = main && self.blocking_enabled;
                let allowed = buckets[usize::from(!main)].take(session.team_id, now);
                if !allowed {
                    let outcome = if blocking { "blocked" } else { "counted" };
                    counter!("ai_research_v4_recorder_rate_limited_sessions_total", "outcome" => outcome)
                        .increment(1);
                }
                let prefix = if allowed || !blocking {
                    self.seen.insert(session.clone(), ());
                    SEEN_PREFIX
                } else {
                    self.blocked.insert(session.clone(), true);
                    blocked.insert(session.clone());
                    BLOCKED_PREFIX
                };
                writes.push(PipelineCommand::SetEx {
                    key: state_key(prefix, session),
                    value: "1".to_owned(),
                    seconds: STATE_TTL_SECS,
                    format: RedisValueFormat::Utf8,
                });
            }
        }
        if !writes.is_empty() {
            let written = self
                .call(deadline, self.redis.execute_pipeline(writes))
                .await;
            if let Ok(results) = written {
                if let Some(Err(error)) = results.into_iter().find(Result::is_err) {
                    tracing::warn!(%error, "writing the session limiter's state failed");
                    counter!("ai_research_v4_recorder_session_limiter_redis_errors_total")
                        .increment(1);
                }
            }
        }
        blocked
    }

    /// Runs one Redis call within the batch's deadline. A failure is counted, and a dead connection reconnects.
    async fn call<T>(
        &self,
        deadline: tokio::time::Instant,
        call: impl std::future::Future<Output = Result<T, CustomRedisError>>,
    ) -> Result<T, ()> {
        let error = match tokio::time::timeout_at(deadline, call).await {
            Ok(Ok(value)) => return Ok(value),
            Ok(Err(error)) => error,
            Err(_) => CustomRedisError::Timeout,
        };
        tracing::warn!(%error, "the session limiter's redis call failed");
        counter!("ai_research_v4_recorder_session_limiter_redis_errors_total").increment(1);
        // The connection does not come back by itself after a failover.
        if error.is_unrecoverable_error() {
            self.redis.heal().await;
        }
        Err(())
    }
}

#[cfg(test)]
mod tests {
    use capture::event_restrictions::{
        Restriction as Rule, RestrictionFilters, RestrictionManager, RestrictionScope,
        RestrictionType,
    };
    use common_redis::{MockRedisClient, MockRedisValue, RedisErrorKind};

    use super::*;

    #[tokio::test]
    async fn matches_restrictions_on_the_session_id_as_the_main_lane_reads_it() {
        let session = "019a2f3e-8c00-7000-8000-00000000000a";
        let mut manager = RestrictionManager::new();
        manager.insert_restrictions(
            Pipeline::SessionRecordings,
            "token",
            vec![Rule {
                restriction_type: RestrictionType::DropEvent,
                scope: RestrictionScope::Filtered(RestrictionFilters {
                    session_ids: HashSet::from([session.to_owned()]),
                    ..RestrictionFilters::default()
                }),
                args: None,
            }],
        );
        let restrictions = Restrictions::default();
        let now = restrictions.service.update(manager).await;
        let upper = session.to_ascii_uppercase();
        let headers = Headers {
            token: Some("token"),
            session_id: Some(&upper),
            ..Headers::default()
        };
        assert!(restrictions.get(&headers, now).await.drop);
    }

    fn session(team_id: i64, id: &str) -> SessionKey {
        SessionKey {
            team_id,
            session_id: id.to_owned(),
        }
    }

    fn on(main: bool, sessions: &[SessionKey]) -> BTreeMap<SessionKey, bool> {
        sessions.iter().map(|s| (s.clone(), main)).collect()
    }

    fn sorted(blocked: HashSet<SessionKey>) -> Vec<String> {
        let mut ids: Vec<String> = blocked.into_iter().map(|s| s.session_id).collect();
        ids.sort();
        ids
    }

    #[tokio::test(start_paused = true)]
    async fn a_team_bucket_holds_its_capacity_and_refills_at_its_rate() {
        let mut buckets = Buckets {
            capacity: 2.0,
            replenish_per_sec: 0.5,
            teams: HashMap::new(),
        };
        let now = tokio::time::Instant::now();
        let taken = |buckets: &mut Buckets, at: tokio::time::Instant| {
            (0..4).filter(|_| buckets.take(7, at)).count()
        };
        assert_eq!(taken(&mut buckets, now), 2);
        assert_eq!(taken(&mut buckets, now + Duration::from_secs(2)), 1);
        // A long pause refills to the capacity, not past it.
        assert_eq!(taken(&mut buckets, now + Duration::from_secs(600)), 2);
    }

    #[tokio::test(start_paused = true)]
    async fn a_flood_of_new_sessions_blocks_the_excess_of_its_team_only() {
        let redis = MockRedisClient::new();
        let limiter = SessionLimiter::new(Arc::new(redis.clone()), 2.0, 1.0, true);
        let flood: Vec<SessionKey> = (0..4)
            .map(|i| session(7, &format!("s{i}")))
            .chain([session(8, "other")])
            .collect();
        assert_eq!(
            sorted(limiter.blocked(&on(true, &flood)).await),
            ["s2", "s3"]
        );

        // Later messages: a blocked session stays blocked, and a seen one takes no token from the empty bucket.
        let later = [session(7, "s0"), session(7, "s3")];
        assert_eq!(sorted(limiter.blocked(&on(true, &later)).await), ["s3"]);

        let writes: Vec<String> = redis
            .get_calls()
            .into_iter()
            .filter_map(|c| match c.value {
                MockRedisValue::StringWithTTLAndFormat(_, STATE_TTL_SECS, _) => Some(c.key),
                _ => None,
            })
            .collect();
        assert_eq!(
            writes,
            [
                format!("{SEEN_PREFIX}:7:s0"),
                format!("{SEEN_PREFIX}:7:s1"),
                format!("{BLOCKED_PREFIX}:7:s2"),
                format!("{BLOCKED_PREFIX}:7:s3"),
                format!("{SEEN_PREFIX}:8:other"),
            ]
        );
    }

    #[tokio::test(start_paused = true)]
    async fn the_overflow_topic_only_counts_but_drops_blocked_sessions() {
        let limiter = SessionLimiter::new(Arc::new(MockRedisClient::new()), 1.0, 0.0, true);
        let flood: Vec<SessionKey> = (0..3).map(|i| session(7, &format!("o{i}"))).collect();
        assert!(limiter.blocked(&on(false, &flood)).await.is_empty());

        let main = [session(7, "m0"), session(7, "m1")];
        assert_eq!(sorted(limiter.blocked(&on(true, &main)).await), ["m1"]);
        assert_eq!(sorted(limiter.blocked(&on(false, &main)).await), ["m1"]);
    }

    #[tokio::test(start_paused = true)]
    async fn reads_the_state_other_processes_wrote() {
        let mut redis = MockRedisClient::new();
        redis.mget_ret(&format!("{SEEN_PREFIX}:7:seen"), Some(b"1".to_vec()));
        redis.mget_ret(&format!("{BLOCKED_PREFIX}:7:blocked"), Some(b"1".to_vec()));
        let limiter = SessionLimiter::new(Arc::new(redis), 1.0, 0.0, true);
        let sessions = [
            session(7, "seen"),
            session(7, "blocked"),
            session(7, "new"),
            session(7, "late"),
        ];
        // Neither known session takes the one token, so the first new one gets it.
        assert_eq!(
            sorted(limiter.blocked(&on(true, &sessions)).await),
            ["blocked", "new"]
        );
    }

    #[tokio::test(start_paused = true)]
    async fn fails_open_when_redis_does_not_answer() {
        let redis = MockRedisClient::new().mget_error(CustomRedisError::from_redis_kind(
            RedisErrorKind::ParseError,
            "the connection closed in a reply",
        ));
        let limiter = SessionLimiter::new(Arc::new(redis.clone()), 0.0, 0.0, true);
        assert!(limiter
            .blocked(&on(true, &[session(7, "a")]))
            .await
            .is_empty());
        let ops: Vec<_> = redis.get_calls().into_iter().map(|c| c.op).collect();
        assert_eq!(ops, ["mget", "heal"]);

        // A block that misses the deadline holds in this process.
        let redis = MockRedisClient::new().pipeline_block(Duration::from_secs(60));
        let limiter = SessionLimiter::new(Arc::new(redis), 0.0, 0.0, true);
        let started = tokio::time::Instant::now();
        let a = on(true, &[session(7, "a")]);
        assert_eq!(sorted(limiter.blocked(&a).await), ["a"]);
        assert_eq!(started.elapsed(), LIMITER_DEADLINE);
        assert_eq!(sorted(limiter.blocked(&a).await), ["a"]);
    }

    #[tokio::test(start_paused = true)]
    async fn without_blocking_only_counts() {
        let redis = MockRedisClient::new();
        let limiter = SessionLimiter::new(Arc::new(redis.clone()), 0.0, 0.0, false);
        assert!(limiter
            .blocked(&on(true, &[session(7, "a"), session(7, "b")]))
            .await
            .is_empty());
        assert!(redis
            .get_calls()
            .iter()
            .all(|c| !c.key.starts_with(BLOCKED_PREFIX)));
    }
}
