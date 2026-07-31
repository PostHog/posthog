//! Validates project API tokens against real teams, so a typo'd key gets an
//! immediate 401 at the edge instead of a 200 followed by a silent
//! `team_not_found` drop in the ingestion consumer.
//!
//! The hot path never blocks on Postgres: verdicts are cached (positive and
//! negative), and any store failure fails OPEN — ingestion availability wins
//! over rejecting bad tokens. With no store configured the validator is a
//! no-op, preserving today's behavior.

use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use capture::token::validate_token;
use metrics::counter;
use moka::future::Cache;
use sqlx::postgres::{PgPool, PgPoolOptions};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TokenVerdict {
    /// The token maps to a real team (or validation is disabled).
    Valid,
    /// The store definitively answered: no team has this token.
    Unknown,
    /// The store could not answer; callers must fail open.
    Unavailable,
}

#[async_trait]
pub trait TokenStore: Send + Sync {
    /// Ok(true) = a team owns this token; Ok(false) = definitively unknown.
    async fn token_exists(&self, token: &str) -> anyhow::Result<bool>;
}

pub struct PgTokenStore {
    pool: PgPool,
}

impl PgTokenStore {
    pub fn connect(database_url: &str) -> anyhow::Result<Self> {
        // A tiny lazy pool: lookups happen only on cache misses, and no
        // connection is made until the first one — a database that is slow or
        // down at boot must not disable validation for the process lifetime.
        // Per-lookup failures fail open in check() and self-heal when the
        // database returns.
        let pool = PgPoolOptions::new()
            .max_connections(2)
            .acquire_timeout(Duration::from_secs(1))
            .connect_lazy(database_url)?;
        Ok(Self { pool })
    }
}

#[async_trait]
impl TokenStore for PgTokenStore {
    async fn token_exists(&self, token: &str) -> anyhow::Result<bool> {
        let row: Option<i64> =
            sqlx::query_scalar("SELECT 1::bigint FROM posthog_team WHERE api_token = $1 LIMIT 1")
                .bind(token)
                .fetch_optional(&self.pool)
                .await?;
        Ok(row.is_some())
    }
}

pub struct TokenValidator {
    store: Option<Arc<dyn TokenStore>>,
    cache: Cache<String, bool>,
}

impl TokenValidator {
    pub fn new(store: Option<Arc<dyn TokenStore>>, cache_size: u64, cache_ttl: Duration) -> Self {
        Self {
            store,
            cache: Cache::builder()
                .max_capacity(cache_size)
                .time_to_live(cache_ttl)
                .build(),
        }
    }

    pub fn disabled() -> Self {
        Self::new(None, 1, Duration::from_secs(1))
    }

    pub async fn check(&self, token: &str) -> TokenVerdict {
        let Some(store) = &self.store else {
            counter!("capture_logs_token_validation_total", "result" => "disabled").increment(1);
            return TokenVerdict::Valid;
        };

        // Shape-check before touching the cache or Postgres. A token that isn't
        // even a well-formed project key has no team, so reject it here — and,
        // critically, unauthenticated junk (unique garbage tokens) can never
        // drive a cache miss or a database lookup, closing the DoS amplifier.
        if validate_token(token).is_err() {
            counter!("capture_logs_token_validation_total", "result" => "malformed").increment(1);
            return TokenVerdict::Unknown;
        }

        // try_get_with coalesces concurrent misses for the same token into a
        // single query (one Postgres round trip per key, not one per request),
        // caches the Ok verdict (positive and negative), and does NOT cache
        // errors — so a store blip fails open per-request and self-heals.
        let token_owned = token.to_string();
        match self
            .cache
            .try_get_with(token_owned, async { store.token_exists(token).await })
            .await
        {
            Ok(exists) => {
                let result = if exists { "valid" } else { "unknown" };
                counter!("capture_logs_token_validation_total", "result" => result).increment(1);
                if exists {
                    TokenVerdict::Valid
                } else {
                    TokenVerdict::Unknown
                }
            }
            Err(e) => {
                // Fail open: never let a store outage take down ingestion.
                tracing::warn!("token validation unavailable, accepting: {e}");
                counter!("capture_logs_token_validation_total", "result" => "unavailable")
                    .increment(1);
                TokenVerdict::Unavailable
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct FakeStore {
        exists: Option<bool>, // None = error
        calls: AtomicUsize,
    }

    #[async_trait]
    impl TokenStore for FakeStore {
        async fn token_exists(&self, _token: &str) -> anyhow::Result<bool> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            match self.exists {
                Some(v) => Ok(v),
                None => anyhow::bail!("pg down"),
            }
        }
    }

    fn validator_with(store: Arc<FakeStore>) -> TokenValidator {
        TokenValidator::new(Some(store), 100, Duration::from_secs(60))
    }

    #[tokio::test]
    async fn disabled_validator_accepts_everything_without_a_store() {
        let v = TokenValidator::disabled();
        assert_eq!(v.check("phc_anything").await, TokenVerdict::Valid);
    }

    #[tokio::test]
    async fn known_token_is_valid_and_cached() {
        let store = Arc::new(FakeStore {
            exists: Some(true),
            calls: AtomicUsize::new(0),
        });
        let v = validator_with(store.clone());
        assert_eq!(v.check("phc_real").await, TokenVerdict::Valid);
        assert_eq!(v.check("phc_real").await, TokenVerdict::Valid);
        assert_eq!(
            store.calls.load(Ordering::SeqCst),
            1,
            "second check must hit the cache"
        );
    }

    #[tokio::test]
    async fn unknown_token_is_rejected_and_negative_cached() {
        let store = Arc::new(FakeStore {
            exists: Some(false),
            calls: AtomicUsize::new(0),
        });
        let v = validator_with(store.clone());
        assert_eq!(v.check("phc_typo").await, TokenVerdict::Unknown);
        assert_eq!(v.check("phc_typo").await, TokenVerdict::Unknown);
        assert_eq!(
            store.calls.load(Ordering::SeqCst),
            1,
            "negative verdicts must also cache"
        );
    }

    #[tokio::test]
    async fn store_error_fails_open_and_is_not_cached() {
        let store = Arc::new(FakeStore {
            exists: None,
            calls: AtomicUsize::new(0),
        });
        let v = validator_with(store.clone());
        assert_eq!(v.check("phc_any").await, TokenVerdict::Unavailable);
        assert_eq!(v.check("phc_any").await, TokenVerdict::Unavailable);
        assert_eq!(
            store.calls.load(Ordering::SeqCst),
            2,
            "unavailable verdicts must not be cached, so recovery is immediate"
        );
    }

    #[tokio::test]
    async fn malformed_tokens_are_rejected_without_touching_the_store() {
        // A personal API key (phx_) is not a project token — it must be
        // rejected on shape alone, and must never reach Postgres, so garbage
        // traffic can't drive database load.
        let store = Arc::new(FakeStore {
            exists: Some(true),
            calls: AtomicUsize::new(0),
        });
        let v = validator_with(store.clone());
        assert_eq!(v.check("phx_personal_key").await, TokenVerdict::Unknown);
        assert_eq!(v.check("").await, TokenVerdict::Unknown);
        assert_eq!(
            store.calls.load(Ordering::SeqCst),
            0,
            "malformed tokens must never query the store"
        );
    }

    #[tokio::test]
    async fn distinct_tokens_get_distinct_verdicts() {
        let store = Arc::new(FakeStore {
            exists: Some(true),
            calls: AtomicUsize::new(0),
        });
        let v = validator_with(store);
        assert_eq!(v.check("phc_a").await, TokenVerdict::Valid);
        // A different token is a cache miss, not a reuse of phc_a's verdict.
        let store2 = Arc::new(FakeStore {
            exists: Some(false),
            calls: AtomicUsize::new(0),
        });
        let v2 = validator_with(store2);
        assert_eq!(v2.check("phc_b").await, TokenVerdict::Unknown);
    }
}
