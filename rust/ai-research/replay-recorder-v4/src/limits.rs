//! What the replay lanes read from Redis to drop data: event ingestion restrictions per message, and the sessions
//! their new-session rate limiter blocked.

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
use crate::process::{Headers, Restriction};

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

    /// The main lane matches restrictions on the raw headers, so these are not normalized.
    pub async fn get(&self, headers: &Headers<'_>, now_ts: i64) -> Restriction {
        let Some(token) = headers.token else {
            return Restriction::default();
        };
        let context = EventContext {
            distinct_id: headers.distinct_id,
            session_id: headers.session_id,
            event_name: headers.event,
            event_uuid: headers.uuid,
            now_ts,
        };
        let applied = self
            .service
            .get_restrictions(token, &context, Pipeline::SessionRecordings)
            .await;
        Restriction {
            drop: applied.should_drop(),
            dlq: applied.redirect_to_dlq(),
            force_overflow: applied.force_overflow(),
        }
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
    /// Fails open as the replay lanes' filter does: without Redis they block nothing either.
    async fn blocked(&self, sessions: &[SessionKey]) -> HashSet<SessionKey> {
        let mut blocked = HashSet::new();
        for chunk in sessions.chunks(500) {
            let keys: Vec<String> = chunk.iter().flat_map(blocklist_keys).collect();
            match self.redis.mget(keys).await {
                Ok(values) => {
                    for (session, values) in chunk.iter().zip(values.chunks(2)) {
                        if values.iter().any(Option::is_some) {
                            blocked.insert(session.clone());
                        }
                    }
                }
                Err(error) => {
                    tracing::warn!(%error, "reading the session blocklist failed");
                    counter!("replay_recorder_v4_blocklist_errors_total").increment(1);
                }
            }
        }
        blocked
    }
}

#[cfg(test)]
mod tests {
    use common_redis::MockRedisClient;

    use super::*;

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
