//! Resolves a project API key to a real team, so a mistyped key gets a 401 at
//! the edge instead of a 200 followed by a silent `team_not_found` drop deep in
//! ingestion. `/flags` and `/decide` already answer 401 for unknown tokens;
//! this makes capture consistent with them.
//!
//! Availability beats correctness here: the hot path never blocks on a cold
//! lookup twice (verdicts are cached, positive and negative), and anything
//! short of a definitive "no team owns this token" is treated as valid. A
//! Redis, S3, or Postgres blip therefore cannot start rejecting real customer
//! traffic — it only stops catching typos.
//!
//! Tiers, in order: in-process cache → team_metadata HyperCache (Redis → S3,
//! the same entries Django writes and `/flags` reads) → Postgres. A HyperCache
//! miss alone is not proof the token is bogus (Django may simply not have
//! warmed that team yet), so only Postgres can produce `Unknown`. With no
//! Postgres configured the validator never rejects.

use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use common_database::{Client as _, PostgresReader};
use common_hypercache::{HyperCacheError, HyperCacheReader, KeyType};
use metrics::counter;
use moka::future::Cache;

const VALIDATION_COUNTER: &str = "capture_token_validation_total";

/// How the deployment treats an unknown token.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum TokenValidationMode {
    /// No lookups at all — the pre-validation behavior.
    #[default]
    Off,
    /// Look up and record the verdict, but still accept the request. Lets the
    /// reject rate be observed before 401s go hot on live ingest.
    DryRun,
    /// Answer 401 for tokens no team owns.
    Enforce,
}

impl std::str::FromStr for TokenValidationMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_ascii_lowercase().as_str() {
            "off" | "disabled" => Ok(Self::Off),
            "dry_run" | "dry-run" | "dryrun" => Ok(Self::DryRun),
            "enforce" | "on" | "enabled" => Ok(Self::Enforce),
            other => Err(format!("unknown token validation mode: {other}")),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TokenVerdict {
    /// A team owns this token, or nothing could prove otherwise.
    Valid,
    /// A definitive answer that no team owns this token.
    Unknown,
}

/// A definitive-only existence check: `Ok(Some(bool))` is proof either way,
/// `Ok(None)` means "cannot say", and `Err` is an infrastructure failure.
#[async_trait]
pub trait TeamTokenStore: Send + Sync {
    async fn team_exists(&self, token: &str) -> anyhow::Result<Option<bool>>;
}

/// team_metadata HyperCache (Redis → S3) fronting Postgres. Only the Postgres
/// tier can say a token is unknown; a cache miss just means "cannot say".
pub struct CachedTeamTokenStore {
    hypercache: Option<Arc<HyperCacheReader>>,
    pg: Option<PostgresReader>,
}

impl CachedTeamTokenStore {
    pub fn new(hypercache: Option<Arc<HyperCacheReader>>, pg: Option<PostgresReader>) -> Self {
        Self { hypercache, pg }
    }

    async fn hypercache_hit(&self, token: &str) -> Option<bool> {
        let reader = self.hypercache.as_ref()?;
        match reader.get(&KeyType::string(token)).await {
            Ok(_) => {
                counter!(VALIDATION_COUNTER, "tier" => "hypercache", "result" => "hit")
                    .increment(1);
                Some(true)
            }
            Err(HyperCacheError::CacheMiss) => {
                counter!(VALIDATION_COUNTER, "tier" => "hypercache", "result" => "miss")
                    .increment(1);
                None
            }
            Err(e) => {
                tracing::warn!("team_metadata hypercache lookup failed: {e}");
                counter!(VALIDATION_COUNTER, "tier" => "hypercache", "result" => "error")
                    .increment(1);
                None
            }
        }
    }
}

#[async_trait]
impl TeamTokenStore for CachedTeamTokenStore {
    async fn team_exists(&self, token: &str) -> anyhow::Result<Option<bool>> {
        if self.hypercache_hit(token).await == Some(true) {
            return Ok(Some(true));
        }

        let Some(pg) = &self.pg else {
            return Ok(None);
        };

        let mut conn = pg.get_connection().await?;
        let found: Option<i64> =
            sqlx::query_scalar("SELECT 1::bigint FROM posthog_team WHERE api_token = $1 LIMIT 1")
                .bind(token)
                .fetch_optional(&mut *conn)
                .await?;
        let exists = found.is_some();
        let result = if exists { "hit" } else { "miss" };
        counter!(VALIDATION_COUNTER, "tier" => "postgres", "result" => result).increment(1);
        Ok(Some(exists))
    }
}

pub struct TokenValidator {
    mode: TokenValidationMode,
    store: Option<Arc<dyn TeamTokenStore>>,
    valid: Cache<String, ()>,
    /// Separate from `valid` so unknown verdicts can carry a shorter TTL: a
    /// project created seconds ago must stop being rejected quickly.
    unknown: Cache<String, ()>,
}

impl TokenValidator {
    pub fn new(
        mode: TokenValidationMode,
        store: Option<Arc<dyn TeamTokenStore>>,
        cache_capacity: u64,
        ttl: Duration,
        negative_ttl: Duration,
    ) -> Self {
        Self {
            mode,
            store,
            valid: Cache::builder()
                .max_capacity(cache_capacity)
                .time_to_live(ttl)
                .build(),
            unknown: Cache::builder()
                .max_capacity(cache_capacity)
                .time_to_live(negative_ttl)
                .build(),
        }
    }

    pub fn disabled() -> Self {
        Self::new(
            TokenValidationMode::Off,
            None,
            1,
            Duration::from_secs(1),
            Duration::from_secs(1),
        )
    }

    /// `Unknown` only when a store definitively said no team owns the token.
    /// Everything else — validation off, no store, cache or database trouble —
    /// is `Valid`, so ingestion keeps flowing.
    pub async fn check(&self, token: &str) -> TokenVerdict {
        if self.mode == TokenValidationMode::Off {
            return TokenVerdict::Valid;
        }

        let Some(store) = &self.store else {
            counter!(VALIDATION_COUNTER, "tier" => "none", "result" => "no_store").increment(1);
            return TokenVerdict::Valid;
        };

        if self.valid.get(token).await.is_some() {
            counter!(VALIDATION_COUNTER, "tier" => "memory", "result" => "valid").increment(1);
            return TokenVerdict::Valid;
        }
        if self.unknown.get(token).await.is_some() {
            counter!(VALIDATION_COUNTER, "tier" => "memory", "result" => "unknown").increment(1);
            return TokenVerdict::Unknown;
        }

        match store.team_exists(token).await {
            Ok(Some(true)) => {
                self.valid.insert(token.to_string(), ()).await;
                counter!(VALIDATION_COUNTER, "tier" => "store", "result" => "valid").increment(1);
                TokenVerdict::Valid
            }
            Ok(Some(false)) => {
                self.unknown.insert(token.to_string(), ()).await;
                counter!(VALIDATION_COUNTER, "tier" => "store", "result" => "unknown").increment(1);
                TokenVerdict::Unknown
            }
            // Not proof of anything: accept, and cache no verdict.
            Ok(None) => {
                counter!(VALIDATION_COUNTER, "tier" => "store", "result" => "indeterminate")
                    .increment(1);
                TokenVerdict::Valid
            }
            Err(e) => {
                tracing::warn!("token validation unavailable, accepting token: {e}");
                counter!(VALIDATION_COUNTER, "tier" => "store", "result" => "unavailable")
                    .increment(1);
                TokenVerdict::Valid
            }
        }
    }

    /// Whether this request should be rejected. Always consults the store (so
    /// dry-run reports the same reject rate enforcement would produce) but only
    /// enforcing mode turns an unknown token into a rejection.
    pub async fn should_reject(&self, token: &str) -> bool {
        if self.check(token).await == TokenVerdict::Valid {
            return false;
        }

        if self.mode == TokenValidationMode::Enforce {
            true
        } else {
            counter!(VALIDATION_COUNTER, "tier" => "policy", "result" => "dry_run_would_reject")
                .increment(1);
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct FakeStore {
        answer: anyhow::Result<Option<bool>>,
        calls: AtomicUsize,
    }

    impl FakeStore {
        fn answering(answer: Option<bool>) -> Arc<Self> {
            Arc::new(Self {
                answer: Ok(answer),
                calls: AtomicUsize::new(0),
            })
        }

        fn failing() -> Arc<Self> {
            Arc::new(Self {
                answer: Err(anyhow::anyhow!("postgres is away")),
                calls: AtomicUsize::new(0),
            })
        }
    }

    #[async_trait]
    impl TeamTokenStore for FakeStore {
        async fn team_exists(&self, _token: &str) -> anyhow::Result<Option<bool>> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            match &self.answer {
                Ok(answer) => Ok(*answer),
                Err(e) => Err(anyhow::anyhow!("{e}")),
            }
        }
    }

    fn validator(mode: TokenValidationMode, store: Arc<FakeStore>) -> TokenValidator {
        let store: Arc<dyn TeamTokenStore> = store;
        TokenValidator::new(
            mode,
            Some(store),
            100,
            Duration::from_secs(300),
            Duration::from_secs(30),
        )
    }

    #[tokio::test]
    async fn off_mode_never_consults_the_store() {
        let store = FakeStore::answering(Some(false));
        let v = validator(TokenValidationMode::Off, store.clone());
        assert!(!v.should_reject("phc_typo").await);
        assert_eq!(store.calls.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn enforce_rejects_only_a_definitive_miss() {
        let cases = [
            (Some(true), false),
            // A store that cannot say (e.g. no Postgres configured) must not reject.
            (None, false),
            (Some(false), true),
        ];
        for (answer, expected_reject) in cases {
            let v = validator(TokenValidationMode::Enforce, FakeStore::answering(answer));
            assert_eq!(
                v.should_reject("phc_token").await,
                expected_reject,
                "store answer {answer:?}"
            );
        }
    }

    #[tokio::test]
    async fn store_failure_fails_open_and_is_not_cached() {
        let store = FakeStore::failing();
        let v = validator(TokenValidationMode::Enforce, store.clone());
        assert!(!v.should_reject("phc_any").await);
        assert!(!v.should_reject("phc_any").await);
        assert_eq!(
            store.calls.load(Ordering::SeqCst),
            2,
            "a failed lookup must not be cached, so validation recovers immediately"
        );
    }

    #[tokio::test]
    async fn dry_run_looks_up_but_never_rejects() {
        let store = FakeStore::answering(Some(false));
        let v = validator(TokenValidationMode::DryRun, store.clone());
        assert!(!v.should_reject("phc_typo").await);
        assert_eq!(store.calls.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn verdicts_are_cached_in_both_directions() {
        for answer in [true, false] {
            let store = FakeStore::answering(Some(answer));
            let v = validator(TokenValidationMode::Enforce, store.clone());
            v.check("phc_token").await;
            v.check("phc_token").await;
            assert_eq!(
                store.calls.load(Ordering::SeqCst),
                1,
                "answer {answer} should be served from the in-process cache"
            );
        }
    }

    #[tokio::test]
    async fn an_unknown_verdict_expires_so_a_new_project_recovers() {
        let store = FakeStore::answering(Some(false));
        let erased: Arc<dyn TeamTokenStore> = store.clone();
        let v = TokenValidator::new(
            TokenValidationMode::Enforce,
            Some(erased),
            100,
            Duration::from_secs(300),
            Duration::from_millis(10),
        );
        assert!(v.should_reject("phc_brand_new").await);
        tokio::time::sleep(Duration::from_millis(100)).await;
        // The token now resolves, so the expired rejection must not stick.
        assert!(v.should_reject("phc_brand_new").await);
        assert_eq!(
            store.calls.load(Ordering::SeqCst),
            2,
            "an expired unknown verdict must be looked up again"
        );
    }

    #[tokio::test]
    async fn distinct_tokens_do_not_share_a_verdict() {
        let store = FakeStore::answering(Some(false));
        let v = validator(TokenValidationMode::Enforce, store.clone());
        v.check("phc_a").await;
        v.check("phc_b").await;
        assert_eq!(store.calls.load(Ordering::SeqCst), 2);
    }
}
