use async_trait::async_trait;
use chrono::{DateTime, Utc};
use moka::sync::Cache;
use sha2::{Digest, Sha256};
use sqlx::{FromRow, PgPool};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use std::time::Duration;
use uuid::Uuid;

use crate::error::AppError;
use crate::types::AuthContext;

const DEFAULT_RATE_LIMIT_MAX_ATTEMPTS: u32 = 10;
const DEFAULT_RATE_LIMIT_WINDOW_SECS: u64 = 60;
const METRIC_AUTH_RATE_LIMITED: &str = "agent_sync_auth_rate_limited_total";

#[async_trait]
pub trait AuthService: Send + Sync {
    async fn authenticate(&self, token: &str) -> Result<AuthContext, AppError>;
    async fn authorize_run(
        &self,
        user_id: i32,
        project_id: i64,
        task_id: &Uuid,
        run_id: &Uuid,
    ) -> Result<(), AppError>;
}

#[derive(FromRow)]
struct OAuthTokenRow {
    user_id: i32,
    expires: Option<DateTime<Utc>>,
    current_team_id: Option<i32>,
}

pub struct CachedAuthService {
    cache: Cache<String, Option<AuthContext>>,
    rate_limit_cache: Cache<String, Arc<AtomicU32>>,
    postgres: PgPool,
    rate_limit_max_attempts: u32,
}

impl CachedAuthService {
    pub fn new(postgres: PgPool, cache_ttl: Duration, cache_max_size: usize) -> Arc<Self> {
        Self::with_rate_limit(
            postgres,
            cache_ttl,
            cache_max_size,
            DEFAULT_RATE_LIMIT_MAX_ATTEMPTS,
            Duration::from_secs(DEFAULT_RATE_LIMIT_WINDOW_SECS),
        )
    }

    pub fn with_rate_limit(
        postgres: PgPool,
        cache_ttl: Duration,
        cache_max_size: usize,
        rate_limit_max_attempts: u32,
        rate_limit_window: Duration,
    ) -> Arc<Self> {
        let cache = Cache::builder()
            .max_capacity(cache_max_size as u64)
            .time_to_live(cache_ttl)
            .build();

        let rate_limit_cache = Cache::builder()
            .max_capacity(cache_max_size as u64)
            .time_to_live(rate_limit_window)
            .build();

        Arc::new(Self {
            cache,
            rate_limit_cache,
            postgres,
            rate_limit_max_attempts,
        })
    }

    fn check_rate_limit(&self, token_hash: &str) -> Result<(), AppError> {
        let counter = self
            .rate_limit_cache
            .get_with(token_hash.to_string(), || Arc::new(AtomicU32::new(0)));

        let count = counter.load(Ordering::Relaxed);
        if count >= self.rate_limit_max_attempts {
            let labels = vec![];
            common_metrics::inc(METRIC_AUTH_RATE_LIMITED, &labels, 1);
            return Err(AppError::TooManyRequests);
        }
        Ok(())
    }

    fn record_failed_attempt(&self, token_hash: &str) {
        let counter = self
            .rate_limit_cache
            .get_with(token_hash.to_string(), || Arc::new(AtomicU32::new(0)));
        counter.fetch_add(1, Ordering::Relaxed);
    }

    fn hash_token(token: &str) -> String {
        let mut hasher = Sha256::new();
        hasher.update(token.as_bytes());
        hex::encode(hasher.finalize())
    }

    async fn lookup_oauth_token(&self, token_hash: &str) -> Result<AuthContext, AppError> {
        let row: Option<OAuthTokenRow> = sqlx::query_as(
            r#"
            SELECT oat.user_id, oat.expires, u.current_team_id
            FROM posthog_oauthaccesstoken oat
            JOIN posthog_user u ON oat.user_id = u.id
            WHERE oat.token_checksum = $1 AND u.is_active = true
            "#,
        )
        .bind(token_hash)
        .fetch_optional(&self.postgres)
        .await?;

        let row = row.ok_or(AppError::InvalidToken)?;

        if let Some(expires) = row.expires {
            if expires < Utc::now() {
                return Err(AppError::TokenExpired);
            }
        }

        Ok(AuthContext {
            user_id: row.user_id,
            team_id: row.current_team_id,
        })
    }

    async fn verify_run_access(
        &self,
        user_id: i32,
        project_id: i64,
        task_id: &Uuid,
        run_id: &Uuid,
    ) -> Result<(), AppError> {
        let exists: Option<(bool,)> = sqlx::query_as(
            r#"
            SELECT EXISTS(
                SELECT 1 FROM posthog_task_run tr
                JOIN posthog_task t ON tr.task_id = t.id
                JOIN posthog_team team ON t.team_id = team.id
                JOIN posthog_organizationmembership om ON team.organization_id = om.organization_id
                WHERE tr.id = $1
                  AND t.id = $2
                  AND team.project_id = $3
                  AND om.user_id = $4
            ) as exists
            "#,
        )
        .bind(run_id)
        .bind(task_id)
        .bind(project_id)
        .bind(user_id)
        .fetch_optional(&self.postgres)
        .await?;

        match exists {
            Some((true,)) => Ok(()),
            _ => Err(AppError::Forbidden("Access denied to this task run".to_string())),
        }
    }
}

#[async_trait]
impl AuthService for CachedAuthService {
    async fn authenticate(&self, token: &str) -> Result<AuthContext, AppError> {
        if !token.starts_with("pha_") {
            return Err(AppError::InvalidToken);
        }

        let token_hash = Self::hash_token(token);

        self.check_rate_limit(&token_hash)?;

        if let Some(entry) = self.cache.get(&token_hash) {
            return entry.clone().ok_or(AppError::InvalidToken);
        }

        let result = self.lookup_oauth_token(&token_hash).await;

        match &result {
            Ok(ctx) => {
                self.cache.insert(token_hash, Some(ctx.clone()));
            }
            Err(AppError::InvalidToken | AppError::TokenExpired) => {
                self.cache.insert(token_hash.clone(), None);
                self.record_failed_attempt(&token_hash);
            }
            Err(_) => {
                // Don't cache transient errors (DB errors, etc.)
            }
        }

        result
    }

    async fn authorize_run(
        &self,
        user_id: i32,
        project_id: i64,
        task_id: &Uuid,
        run_id: &Uuid,
    ) -> Result<(), AppError> {
        self.verify_run_access(user_id, project_id, task_id, run_id)
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct MockAuthService {
        context: AuthContext,
    }

    #[async_trait]
    impl AuthService for MockAuthService {
        async fn authenticate(&self, _token: &str) -> Result<AuthContext, AppError> {
            Ok(self.context.clone())
        }

        async fn authorize_run(
            &self,
            _user_id: i32,
            _project_id: i64,
            _task_id: &Uuid,
            _run_id: &Uuid,
        ) -> Result<(), AppError> {
            Ok(())
        }
    }

    #[test]
    fn test_hash_token() {
        let hash = CachedAuthService::hash_token("pha_test_token");
        assert!(!hash.is_empty());
        assert_eq!(hash.len(), 64);
    }

    #[tokio::test]
    async fn test_mock_auth_service() {
        let service = MockAuthService {
            context: AuthContext::test(),
        };
        let result = service.authenticate("pha_test").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().user_id, 1);
    }
}
