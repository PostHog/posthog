//! What the replay lanes read from Redis to drop data: event ingestion restrictions per message, and the sessions
//! their new-session rate limiter blocked.

use std::borrow::Cow;
use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use capture::event_restrictions::{
    EventContext, EventRestrictionService, EventRestrictionsRepository, Pipeline,
    RedisRestrictionsRepository,
};
use common_redis::{Client, CompressionConfig, CustomRedisError, RedisClient, RedisValueFormat};
use metrics::counter;

use crate::batch::SessionKey;
use crate::process::{normalize_session_id, Headers, Restriction};

const REDIS_TIMEOUT: Duration = Duration::from_secs(5);

const BLOCKLIST_DEADLINE: Duration = Duration::from_secs(10);

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

/// Sessions the replay lanes dropped for good.
#[async_trait]
pub trait Blocklist: Send + Sync {
    async fn blocked(&self, sessions: &[SessionKey]) -> HashSet<SessionKey>;
}

/// The blocklists of the main lane and the v3 mirror. A session on either is not recorded.
pub fn blocklist_keys(session: &SessionKey) -> [String; 2] {
    let suffix = format!("{}:{}", session.team_id, session.session_id);
    [
        format!("@posthog/replay/session-blocked:{suffix}"),
        format!("@posthog/replay/ml-mirror/session-blocked:{suffix}"),
    ]
}

pub struct RedisBlocklist {
    redis: Arc<dyn Client + Send + Sync>,
}

impl RedisBlocklist {
    pub async fn connect(redis_url: String) -> Result<Self, CustomRedisError> {
        let redis = RedisClient::with_config(
            redis_url,
            CompressionConfig::disabled(),
            RedisValueFormat::Utf8,
            Some(REDIS_TIMEOUT),
            Some(REDIS_TIMEOUT),
        )
        .await?;
        Ok(Self::new(Arc::new(redis)))
    }

    pub fn new(redis: Arc<dyn Client + Send + Sync>) -> Self {
        Self { redis }
    }
}

#[async_trait]
impl Blocklist for RedisBlocklist {
    /// Fails open as the replay lanes' filter does: without Redis they block nothing either. After the first failure
    /// the rest of the flush is not checked, so a Redis that does not answer delays a flush only once.
    async fn blocked(&self, sessions: &[SessionKey]) -> HashSet<SessionKey> {
        let deadline = tokio::time::Instant::now() + BLOCKLIST_DEADLINE;
        let mut blocked = HashSet::new();
        for chunk in sessions.chunks(500) {
            let keys: Vec<String> = chunk.iter().flat_map(blocklist_keys).collect();
            let error = match tokio::time::timeout_at(deadline, self.redis.mget(keys)).await {
                Ok(Ok(values)) => {
                    for (session, values) in chunk.iter().zip(values.chunks(2)) {
                        if values.iter().any(Option::is_some) {
                            blocked.insert(session.clone());
                        }
                    }
                    continue;
                }
                Ok(Err(error)) => error,
                Err(_) => CustomRedisError::Timeout,
            };
            tracing::warn!(%error, "reading the session blocklist failed");
            counter!("replay_recorder_v4_blocklist_errors_total").increment(1);
            // The connection does not come back by itself after a failover.
            if error.is_unrecoverable_error() {
                self.redis.heal().await;
            }
            break;
        }
        blocked
    }
}

#[cfg(test)]
mod tests {
    use capture::event_restrictions::{
        Restriction as Rule, RestrictionFilters, RestrictionManager, RestrictionScope,
        RestrictionType,
    };
    use common_redis::{MockRedisClient, RedisErrorKind};

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

    #[tokio::test]
    async fn stops_reading_the_blocklist_after_a_failure_and_reconnects() {
        let sessions: Vec<SessionKey> = (0..1000)
            .map(|i| SessionKey {
                team_id: 7,
                session_id: format!("s{i}"),
            })
            .collect();
        let redis = MockRedisClient::new().mget_error(CustomRedisError::from_redis_kind(
            RedisErrorKind::ParseError,
            "the connection closed in a reply",
        ));
        let blocklist = RedisBlocklist::new(Arc::new(redis.clone()));
        assert!(blocklist.blocked(&sessions).await.is_empty());
        let calls: Vec<_> = redis.get_calls().into_iter().map(|c| c.op).collect();
        assert_eq!(calls, ["mget", "heal"]);
    }

    #[tokio::test]
    async fn a_session_either_lane_blocked_is_blocked() {
        let session = |id: &str| SessionKey {
            team_id: 7,
            session_id: id.to_owned(),
        };
        let mut redis = MockRedisClient::new();
        redis.mget_ret(&blocklist_keys(&session("main"))[0], Some(b"1".to_vec()));
        redis.mget_ret(&blocklist_keys(&session("mirror"))[1], Some(b"1".to_vec()));
        let blocklist = RedisBlocklist::new(Arc::new(redis));
        let blocked = blocklist
            .blocked(&[session("main"), session("mirror"), session("open")])
            .await;
        assert_eq!(blocked, HashSet::from([session("main"), session("mirror")]));
    }
}
