//! Project tokens that belong to no team, as published by the ingestion consumer.
//!
//! capture-logs has no Postgres, so it cannot tell a well-formed token that belongs to no team from
//! a real one. The consumer can: it drops those messages as `team_not_found` and records the token in
//! a Redis sorted set (`UNKNOWN_TOKENS_KEY`, score = last seen in epoch ms). This module keeps an
//! in-memory copy of that set, refreshed in the background, so a request costs one hash lookup.
//!
//! Everything here fails open. Redis is connected lazily, a failed refresh keeps the last snapshot, a
//! snapshot that has gone stale is ignored, and a process that never loaded one has an empty set.

use std::collections::HashSet;
use std::future::Future;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use common_redis::{Client as RedisClient, CustomRedisError};
use metrics::{counter, gauge};
use tracing::{error, info, warn};

/// Written by the consumer (`nodejs/src/common/services/unknown-token-recorder.ts`).
pub const UNKNOWN_TOKENS_KEY: &str = "capture_logs:unknown_tokens";

/// Only tokens the consumer saw this recently count as unknown. A token that gets a team later
/// stops being turned away once the consumer stops seeing it.
pub const UNKNOWN_TOKEN_WINDOW: Duration = Duration::from_secs(60 * 60);

const SHADOW_LOG_INTERVAL_SECS: u64 = 60;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UnknownTokenMode {
    /// Do nothing.
    Off,
    /// Answer as before, but count (and rarely log) the requests that `Reject` would turn away.
    Shadow,
    /// Answer 401.
    Reject,
}

impl UnknownTokenMode {
    pub fn parse(value: &str) -> Option<Self> {
        match value.trim().to_ascii_lowercase().as_str() {
            "off" | "" => Some(Self::Off),
            "shadow" => Some(Self::Shadow),
            "reject" => Some(Self::Reject),
            _ => None,
        }
    }
}

struct Snapshot {
    tokens: HashSet<String>,
    loaded_at: Option<Instant>,
}

struct Inner {
    mode: UnknownTokenMode,
    fail_open_after: Duration,
    snapshot: RwLock<Snapshot>,
    started: Instant,
    last_shadow_log_secs: AtomicU64,
}

#[derive(Clone)]
pub struct UnknownTokens {
    inner: Arc<Inner>,
}

impl UnknownTokens {
    pub fn new(mode: UnknownTokenMode, fail_open_after: Duration) -> Self {
        Self {
            inner: Arc::new(Inner {
                mode,
                fail_open_after,
                snapshot: RwLock::new(Snapshot {
                    tokens: HashSet::new(),
                    loaded_at: None,
                }),
                started: Instant::now(),
                last_shadow_log_secs: AtomicU64::new(0),
            }),
        }
    }

    pub fn disabled() -> Self {
        Self::new(UnknownTokenMode::Off, Duration::ZERO)
    }

    pub fn mode(&self) -> UnknownTokenMode {
        self.inner.mode
    }

    /// One in-memory set lookup. False when off, when nothing has loaded, and when the snapshot is stale.
    pub fn is_unknown(&self, token: &str) -> bool {
        if self.inner.mode == UnknownTokenMode::Off {
            return false;
        }
        let Ok(snapshot) = self.inner.snapshot.read() else {
            return false;
        };
        match snapshot.loaded_at {
            Some(at) if at.elapsed() <= self.inner.fail_open_after => {
                snapshot.tokens.contains(token)
            }
            _ => false,
        }
    }

    /// True at most once a minute per process, so shadow mode can log without flooding.
    pub fn should_log_shadow_hit(&self) -> bool {
        let now = self.inner.started.elapsed().as_secs().max(1);
        let last = self.inner.last_shadow_log_secs.load(Ordering::Relaxed);
        if last != 0 && now.saturating_sub(last) < SHADOW_LOG_INTERVAL_SECS {
            return false;
        }
        self.inner
            .last_shadow_log_secs
            .compare_exchange(last, now, Ordering::Relaxed, Ordering::Relaxed)
            .is_ok()
    }

    fn replace(&self, tokens: HashSet<String>) {
        gauge!("capture_logs_unknown_tokens_loaded").set(tokens.len() as f64);
        if let Ok(mut snapshot) = self.inner.snapshot.write() {
            snapshot.tokens = tokens;
            snapshot.loaded_at = Some(Instant::now());
        }
    }

    /// One refresh. On any error the previous snapshot stays in place.
    pub async fn refresh(
        &self,
        client: &dyn RedisClient,
        now_ms: i64,
        window: Duration,
    ) -> Result<usize, CustomRedisError> {
        let min = now_ms.saturating_sub(window.as_millis() as i64);
        let tokens = client
            .zrangebyscore(
                UNKNOWN_TOKENS_KEY.to_string(),
                min.to_string(),
                "+inf".to_string(),
            )
            .await?;
        let count = tokens.len();
        self.replace(tokens.into_iter().collect());
        Ok(count)
    }

    /// One tick of the refresh loop: connect if there is no connection, then refresh. A failure drops
    /// the connection so the next tick reconnects, and leaves the snapshot alone.
    pub async fn tick<F, Fut>(
        &self,
        client: &mut Option<Arc<dyn RedisClient + Send + Sync>>,
        connect: &F,
        now_ms: i64,
        window: Duration,
    ) -> bool
    where
        F: Fn() -> Fut,
        Fut: Future<Output = Result<Arc<dyn RedisClient + Send + Sync>, CustomRedisError>>,
    {
        if client.is_none() {
            match connect().await {
                Ok(connected) => {
                    info!("Connected to the unknown project token Redis");
                    *client = Some(connected);
                }
                Err(e) => {
                    error!(error = %e, "Failed to connect to the unknown project token Redis, will retry");
                    counter!("capture_logs_unknown_token_refresh_total", "outcome" => "connect_error")
                        .increment(1);
                    return false;
                }
            }
        }
        let Some(connected) = client.as_ref() else {
            return false;
        };
        match self.refresh(connected.as_ref(), now_ms, window).await {
            Ok(_) => {
                counter!("capture_logs_unknown_token_refresh_total", "outcome" => "ok")
                    .increment(1);
                true
            }
            Err(e) => {
                warn!(error = %e, "Failed to refresh unknown project tokens, keeping the last snapshot");
                counter!("capture_logs_unknown_token_refresh_total", "outcome" => "error")
                    .increment(1);
                *client = None;
                false
            }
        }
    }

    /// Refresh in the background for the life of the process.
    pub fn spawn_refresher<F, Fut>(&self, connect: F, interval: Duration)
    where
        F: Fn() -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<Arc<dyn RedisClient + Send + Sync>, CustomRedisError>>
            + Send
            + 'static,
    {
        let this = self.clone();
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(interval);
            ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
            let mut client: Option<Arc<dyn RedisClient + Send + Sync>> = None;
            loop {
                ticker.tick().await;
                let now_ms = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .map(|d| d.as_millis() as i64)
                    .unwrap_or(0);
                this.tick(&mut client, &connect, now_ms, UNKNOWN_TOKEN_WINDOW)
                    .await;
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;

    const NOW: i64 = 1_700_000_000_000;
    const WINDOW: Duration = UNKNOWN_TOKEN_WINDOW;

    fn tokens(mode: UnknownTokenMode) -> UnknownTokens {
        UnknownTokens::new(mode, Duration::from_secs(600))
    }

    fn mock_with(members: &[&str]) -> Arc<dyn RedisClient + Send + Sync> {
        Arc::new(MockRedisClient::new().zrangebyscore_ret(
            UNKNOWN_TOKENS_KEY,
            members.iter().map(|s| s.to_string()).collect(),
        ))
    }

    #[test]
    fn mode_parses_leniently_and_rejects_typos() {
        assert_eq!(UnknownTokenMode::parse("off"), Some(UnknownTokenMode::Off));
        assert_eq!(UnknownTokenMode::parse(""), Some(UnknownTokenMode::Off));
        assert_eq!(
            UnknownTokenMode::parse("Shadow"),
            Some(UnknownTokenMode::Shadow)
        );
        assert_eq!(
            UnknownTokenMode::parse(" reject "),
            Some(UnknownTokenMode::Reject)
        );
        assert_eq!(UnknownTokenMode::parse("rejct"), None);
    }

    #[tokio::test]
    async fn nothing_is_unknown_before_the_first_load() {
        let unknown = tokens(UnknownTokenMode::Reject);
        assert!(!unknown.is_unknown("phc_anything"));
    }

    #[tokio::test]
    async fn a_loaded_token_is_unknown_and_others_are_not() {
        let unknown = tokens(UnknownTokenMode::Shadow);
        let client = mock_with(&["phc_ghost"]);
        unknown.refresh(client.as_ref(), NOW, WINDOW).await.unwrap();

        assert!(unknown.is_unknown("phc_ghost"));
        assert!(!unknown.is_unknown("phc_real"));
    }

    #[tokio::test]
    async fn refresh_asks_for_the_last_hour_only() {
        let unknown = tokens(UnknownTokenMode::Shadow);
        let mock = MockRedisClient::new();
        unknown.refresh(&mock, NOW, WINDOW).await.ok();

        let calls = mock.get_calls();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].key, UNKNOWN_TOKENS_KEY);
        assert_eq!(
            format!("{:?}", calls[0].value),
            format!(
                "{:?}",
                common_redis::MockRedisValue::MinMax(
                    (NOW - 3_600_000).to_string(),
                    "+inf".to_string()
                )
            )
        );
    }

    #[tokio::test]
    async fn off_never_reports_a_token_unknown() {
        let unknown = tokens(UnknownTokenMode::Off);
        let client = mock_with(&["phc_ghost"]);
        unknown.refresh(client.as_ref(), NOW, WINDOW).await.unwrap();

        assert!(!unknown.is_unknown("phc_ghost"));
    }

    #[tokio::test]
    async fn a_failed_refresh_keeps_the_last_snapshot() {
        let unknown = tokens(UnknownTokenMode::Reject);
        let good = mock_with(&["phc_ghost"]);
        unknown.refresh(good.as_ref(), NOW, WINDOW).await.unwrap();

        // A mock with no configured key answers with an error, like a Redis that went away.
        let failing = MockRedisClient::new();
        assert!(unknown.refresh(&failing, NOW, WINDOW).await.is_err());

        assert!(unknown.is_unknown("phc_ghost"));
    }

    #[tokio::test]
    async fn a_stale_snapshot_fails_open() {
        let unknown = UnknownTokens::new(UnknownTokenMode::Reject, Duration::from_millis(20));
        let client = mock_with(&["phc_ghost"]);
        unknown.refresh(client.as_ref(), NOW, WINDOW).await.unwrap();
        assert!(unknown.is_unknown("phc_ghost"));

        tokio::time::sleep(Duration::from_millis(40)).await;

        assert!(!unknown.is_unknown("phc_ghost"));
    }

    #[tokio::test]
    async fn redis_down_at_startup_leaves_the_set_empty_and_retries() {
        let unknown = tokens(UnknownTokenMode::Reject);
        let attempts = Arc::new(AtomicU64::new(0));
        let connect = {
            let attempts = attempts.clone();
            move || {
                let attempts = attempts.clone();
                async move {
                    if attempts.fetch_add(1, Ordering::SeqCst) == 0 {
                        Err(CustomRedisError::Timeout)
                    } else {
                        Ok(mock_with(&["phc_ghost"]))
                    }
                }
            }
        };
        let mut client = None;

        assert!(!unknown.tick(&mut client, &connect, NOW, WINDOW).await);
        assert!(client.is_none());
        assert!(!unknown.is_unknown("phc_ghost"));

        assert!(unknown.tick(&mut client, &connect, NOW, WINDOW).await);
        assert!(unknown.is_unknown("phc_ghost"));
    }

    #[tokio::test]
    async fn a_failed_refresh_drops_the_connection_so_the_next_tick_reconnects() {
        let unknown = tokens(UnknownTokenMode::Reject);
        let connects = Arc::new(AtomicU64::new(0));
        let connect = {
            let connects = connects.clone();
            move || {
                let connects = connects.clone();
                async move {
                    connects.fetch_add(1, Ordering::SeqCst);
                    let client: Arc<dyn RedisClient + Send + Sync> =
                        Arc::new(MockRedisClient::new());
                    Ok(client)
                }
            }
        };
        let mut client = None;

        assert!(!unknown.tick(&mut client, &connect, NOW, WINDOW).await);
        assert!(client.is_none());
        assert!(!unknown.tick(&mut client, &connect, NOW, WINDOW).await);
        assert_eq!(connects.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn shadow_logging_is_limited_to_once_per_interval() {
        let unknown = tokens(UnknownTokenMode::Shadow);
        assert!(unknown.should_log_shadow_hit());
        for _ in 0..100 {
            assert!(!unknown.should_log_shadow_hit());
        }
    }
}
