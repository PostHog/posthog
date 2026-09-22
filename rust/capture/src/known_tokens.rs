//! Edge check for whether a project API token belongs to a team.
//!
//! [`crate::token::validate_token`] only checks a token's shape, so a typo'd,
//! rotated or wrong-region key is accepted with a 200 and dropped much later in
//! ingestion, where the sender never learns about it. This module reads the Redis
//! projection Django maintains (`posthog/storage/capture_known_tokens.py`) so the
//! answer can be given in the response instead.
//!
//! Every uncertainty resolves to [`TokenVerdict::Unverified`], which callers treat
//! as acceptance. A Redis error, a timeout, a paused sweep, or a projection that
//! was never built all leave capture behaving exactly as it did before.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use common_redis::{Client, CustomRedisError};
use metrics::counter;
use moka::future::Cache;
use tokio::time::interval;
use tracing::warn;

const TOKEN_KEY_PREFIX: &str = "capture_known_token";
const SWEEP_MARKER_KEY: &str = "capture_known_tokens_swept_at";

/// What a token lookup concluded.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenVerdict {
    /// The token belongs to a team.
    Known,
    /// The projection is fresh and does not hold the token, so no team owns it.
    Unknown,
    /// No usable answer. Callers accept the request.
    Unverified,
}

impl TokenVerdict {
    fn as_tag(&self) -> &'static str {
        match self {
            Self::Known => "known",
            Self::Unknown => "unknown",
            Self::Unverified => "unverified",
        }
    }
}

/// How far a verdict of [`TokenVerdict::Unknown`] is allowed to go.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenValidationMode {
    /// No lookup at all.
    Off,
    /// Look the token up and count the verdict, but still accept the request.
    DryRun,
    /// Refuse an unknown token with a 401.
    Enforce,
}

impl TokenValidationMode {
    pub fn as_tag(&self) -> &'static str {
        match self {
            Self::Off => "off",
            Self::DryRun => "dry_run",
            Self::Enforce => "enforce",
        }
    }
}

impl std::str::FromStr for TokenValidationMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_ref() {
            "off" => Ok(Self::Off),
            "dry_run" => Ok(Self::DryRun),
            "enforce" => Ok(Self::Enforce),
            _ => Err(format!("Unknown TokenValidationMode: {s}")),
        }
    }
}

/// Reads the known-token projection, in front of two local caches.
///
/// A real sender uses one token, so the positive cache absorbs nearly all traffic
/// and Redis sees a lookup only for a token it has not seen lately. Negative
/// entries expire much sooner than positive ones, so a project created moments
/// after its first event stops being refused within one negative TTL even if the
/// sender never changes anything.
pub struct KnownTokenChecker {
    redis: Arc<dyn Client + Send + Sync>,
    key_prefix: Option<String>,
    timeout: Duration,
    known: Cache<String, ()>,
    unknown: Cache<String, ()>,
    /// Whether the last sweep marker read was recent enough to trust an absent
    /// token as proof of no team. Refreshed by [`Self::spawn_marker_watcher`].
    sweep_fresh: Arc<AtomicBool>,
}

impl KnownTokenChecker {
    pub fn new(
        redis: Arc<dyn Client + Send + Sync>,
        key_prefix: Option<String>,
        timeout: Duration,
        known_ttl: Duration,
        unknown_ttl: Duration,
        cache_max_entries: u64,
    ) -> Self {
        Self {
            redis,
            key_prefix,
            timeout,
            known: Cache::builder()
                .max_capacity(cache_max_entries)
                .time_to_live(known_ttl)
                .build(),
            unknown: Cache::builder()
                .max_capacity(cache_max_entries)
                .time_to_live(unknown_ttl)
                .build(),
            sweep_fresh: Arc::new(AtomicBool::new(false)),
        }
    }

    fn key(&self, suffix: &str) -> String {
        match &self.key_prefix {
            Some(prefix) => format!("{prefix}{suffix}"),
            None => suffix.to_string(),
        }
    }

    /// Reads the sweep marker and records whether it is recent enough to trust.
    ///
    /// Anything other than a fresh timestamp clears the gate, which turns every
    /// later verdict into `Unverified` until a sweep publishes a new marker.
    pub async fn refresh_marker(&self, max_age: Duration) {
        let key = self.key(SWEEP_MARKER_KEY);
        let fresh = match self.redis.get(key.clone()).await {
            Ok(raw) => match raw.trim().parse::<u64>() {
                Ok(swept_at) => Self::age_of(swept_at).is_some_and(|age| age <= max_age),
                Err(_) => {
                    warn!(key = %key, "known-token sweep marker is not a unix timestamp");
                    false
                }
            },
            Err(CustomRedisError::NotFound) => false,
            Err(e) => {
                warn!(key = %key, error = %e, "failed to read known-token sweep marker");
                false
            }
        };

        self.sweep_fresh.store(fresh, Ordering::Relaxed);
        counter!(
            "capture_known_tokens_marker_refresh",
            "result" => if fresh { "fresh" } else { "stale" }
        )
        .increment(1);
    }

    fn age_of(swept_at: u64) -> Option<Duration> {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs();
        now.checked_sub(swept_at).map(Duration::from_secs)
    }

    /// Polls the sweep marker forever, so the gate reflects a sweep that stopped
    /// running without any request paying for the check.
    pub fn spawn_marker_watcher(
        self: Arc<Self>,
        refresh_interval: Duration,
        max_age: Duration,
    ) -> tokio::task::JoinHandle<()> {
        tokio::spawn(async move {
            let mut ticker = interval(refresh_interval);
            loop {
                ticker.tick().await;
                self.refresh_marker(max_age).await;
            }
        })
    }

    pub async fn verify(&self, token: &str) -> TokenVerdict {
        let verdict = self.lookup(token).await;
        counter!("capture_known_tokens_verdict", "verdict" => verdict.as_tag()).increment(1);
        verdict
    }

    async fn lookup(&self, token: &str) -> TokenVerdict {
        if !self.sweep_fresh.load(Ordering::Relaxed) {
            return TokenVerdict::Unverified;
        }

        if self.known.get(token).await.is_some() {
            return TokenVerdict::Known;
        }
        if self.unknown.get(token).await.is_some() {
            return TokenVerdict::Unknown;
        }

        let key = self.key(&format!("{TOKEN_KEY_PREFIX}:{token}"));
        let read = tokio::time::timeout(self.timeout, self.redis.get(key)).await;

        match read {
            Ok(Ok(_)) => {
                self.known.insert(token.to_string(), ()).await;
                TokenVerdict::Known
            }
            Ok(Err(CustomRedisError::NotFound)) => {
                self.unknown.insert(token.to_string(), ()).await;
                TokenVerdict::Unknown
            }
            Ok(Err(e)) => {
                warn!(error = %e, "known-token lookup failed");
                TokenVerdict::Unverified
            }
            Err(_) => TokenVerdict::Unverified,
        }
    }
}

/// Applies the deployment's mode to a token, for a caller that holds the state.
///
/// `Ok(())` means carry on. `Err(CaptureError::UnknownToken)` is only ever
/// returned in [`TokenValidationMode::Enforce`], and only for a token the fresh
/// projection does not hold.
pub async fn enforce_known_token(
    checker: Option<&Arc<KnownTokenChecker>>,
    mode: TokenValidationMode,
    token: &str,
) -> Result<(), crate::api::CaptureError> {
    if mode == TokenValidationMode::Off {
        return Ok(());
    }

    let Some(checker) = checker else {
        return Ok(());
    };

    if checker.verify(token).await == TokenVerdict::Unknown && mode == TokenValidationMode::Enforce
    {
        return Err(crate::api::CaptureError::UnknownToken);
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;

    fn now_secs() -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
    }

    fn checker(redis: MockRedisClient) -> KnownTokenChecker {
        KnownTokenChecker::new(
            Arc::new(redis),
            None,
            Duration::from_millis(100),
            Duration::from_secs(600),
            Duration::from_secs(60),
            1000,
        )
    }

    fn with_fresh_marker() -> MockRedisClient {
        let mut redis = MockRedisClient::new();
        redis.get_ret(SWEEP_MARKER_KEY, Ok(now_secs().to_string()));
        redis
    }

    #[tokio::test]
    async fn accepts_every_token_when_no_sweep_has_run() {
        // No marker at all: the projection cannot be trusted to be complete, so an
        // absent token proves nothing.
        let checker = checker(MockRedisClient::new());
        checker.refresh_marker(Duration::from_secs(3600)).await;

        assert_eq!(checker.verify("phc_nobody").await, TokenVerdict::Unverified);
    }

    #[tokio::test]
    async fn accepts_every_token_when_the_sweep_marker_is_stale() {
        let mut redis = MockRedisClient::new();
        redis.get_ret(SWEEP_MARKER_KEY, Ok((now_secs() - 7200).to_string()));

        let checker = checker(redis);
        checker.refresh_marker(Duration::from_secs(3600)).await;

        assert_eq!(checker.verify("phc_nobody").await, TokenVerdict::Unverified);
    }

    #[tokio::test]
    async fn reports_a_token_the_fresh_projection_holds_as_known() {
        let mut redis = with_fresh_marker();
        redis.get_ret("capture_known_token:phc_real", Ok("1".to_string()));

        let checker = checker(redis);
        checker.refresh_marker(Duration::from_secs(3600)).await;

        assert_eq!(checker.verify("phc_real").await, TokenVerdict::Known);
    }

    #[tokio::test]
    async fn reports_a_token_the_fresh_projection_lacks_as_unknown() {
        let checker = checker(with_fresh_marker());
        checker.refresh_marker(Duration::from_secs(3600)).await;

        assert_eq!(checker.verify("phc_typo").await, TokenVerdict::Unknown);
    }

    #[tokio::test]
    async fn accepts_a_token_when_the_lookup_itself_errors() {
        let mut redis = with_fresh_marker();
        redis.get_ret(
            "capture_known_token:phc_real",
            Err(CustomRedisError::Timeout),
        );

        let checker = checker(redis);
        checker.refresh_marker(Duration::from_secs(3600)).await;

        assert_eq!(checker.verify("phc_real").await, TokenVerdict::Unverified);
    }

    #[tokio::test]
    async fn caches_a_verdict_instead_of_re_reading_redis_per_request() {
        let redis = Arc::new({
            let mut r = with_fresh_marker();
            r.get_ret("capture_known_token:phc_real", Ok("1".to_string()));
            r
        });

        let checker = KnownTokenChecker::new(
            redis.clone(),
            None,
            Duration::from_millis(100),
            Duration::from_secs(600),
            Duration::from_secs(60),
            1000,
        );
        checker.refresh_marker(Duration::from_secs(3600)).await;

        for _ in 0..5 {
            assert_eq!(checker.verify("phc_real").await, TokenVerdict::Known);
        }

        let token_reads = redis
            .get_calls()
            .into_iter()
            .filter(|c| c.key == "capture_known_token:phc_real")
            .count();
        assert_eq!(token_reads, 1);
    }

    #[tokio::test]
    async fn dry_run_counts_an_unknown_token_without_refusing_it() {
        let checker = Arc::new(checker(with_fresh_marker()));
        checker.refresh_marker(Duration::from_secs(3600)).await;

        assert!(
            enforce_known_token(Some(&checker), TokenValidationMode::DryRun, "phc_typo")
                .await
                .is_ok()
        );
    }

    #[tokio::test]
    async fn enforce_refuses_an_unknown_token_but_not_a_known_one() {
        let mut redis = with_fresh_marker();
        redis.get_ret("capture_known_token:phc_real", Ok("1".to_string()));

        let checker = Arc::new(checker(redis));
        checker.refresh_marker(Duration::from_secs(3600)).await;

        assert!(
            enforce_known_token(Some(&checker), TokenValidationMode::Enforce, "phc_real")
                .await
                .is_ok()
        );
        assert!(
            enforce_known_token(Some(&checker), TokenValidationMode::Enforce, "phc_typo")
                .await
                .is_err()
        );
    }

    #[tokio::test]
    async fn off_never_reads_redis() {
        let redis = Arc::new(with_fresh_marker());
        let checker = Arc::new(KnownTokenChecker::new(
            redis.clone(),
            None,
            Duration::from_millis(100),
            Duration::from_secs(600),
            Duration::from_secs(60),
            1000,
        ));

        assert!(
            enforce_known_token(Some(&checker), TokenValidationMode::Off, "phc_typo")
                .await
                .is_ok()
        );
        assert!(redis.get_calls().is_empty());
    }
}
