use async_trait::async_trait;
use std::sync::Arc; // Add this crate for async traits
use thiserror::Error;

use common_database::Client as DatabaseClient;
use common_redis::CustomRedisError;

use crate::redirect::redirect_cache::RedirectCacheManager;
use crate::redirect::redirect_query::fetch_redirect_url;

#[derive(Error, Debug)]
pub enum RedirectError {
    #[error("Link not found")]
    LinkNotFound,
    #[error("Database error: {0}")]
    DatabaseError(#[from] sqlx::Error),
    #[error("Redis error: {0}")]
    RedisError(#[from] CustomRedisError),
    #[error("Database Unavailable")]
    DatabaseUnavailable,
    #[error("Invalid operation: {0}")]
    InvalidOperation(String),
}

#[async_trait]
pub trait RedirectServiceTrait {
    async fn redirect_url(
        &self,
        short_code: &str,
        short_link_domain: &str,
    ) -> Result<String, RedirectError>;

    async fn store_url(
        &self,
        redirect_url: &str,
        short_string: &str,
    ) -> Result<String, RedirectError>;
}

pub struct ExternalRedirectService {
    cache_manager: Arc<dyn RedirectCacheManager + Send + Sync>,
    default_domain_for_public_store: String,
}

impl ExternalRedirectService {
    pub fn new(
        cache_manager: Arc<dyn RedirectCacheManager + Send + Sync>,
        default_domain_for_public_store: String,
    ) -> Self {
        Self {
            cache_manager,
            default_domain_for_public_store,
        }
    }
}

pub struct InternalRedirectService {
    db_reader_client: Arc<dyn DatabaseClient + Send + Sync>,
    cache_manager: Arc<dyn RedirectCacheManager + Send + Sync>,
}

impl InternalRedirectService {
    pub fn new(
        db_reader_client: Arc<dyn DatabaseClient + Send + Sync>,
        cache_manager: Arc<dyn RedirectCacheManager + Send + Sync>,
    ) -> Self {
        Self {
            db_reader_client,
            cache_manager,
        }
    }

    async fn fetch_redirect_url_from_database(
        &self,
        short_code: &str,
        short_link_domain: &str,
    ) -> Result<String, RedirectError> {
        fetch_redirect_url(self.db_reader_client.clone(), short_link_domain, short_code).await
    }
}

const TWENTY_FOUR_HOURS_IN_SECONDS: u64 = 60 * 60 * 24;

#[async_trait]
impl RedirectServiceTrait for ExternalRedirectService {
    async fn redirect_url(
        &self,
        short_code: &str,
        short_link_domain: &str,
    ) -> Result<String, RedirectError> {
        match self
            .cache_manager
            .get_cached_url(short_code, short_link_domain)
            .await
        {
            Ok(url) => {
                tracing::debug!(
                    "Cache hit via manager for {}:{}",
                    short_link_domain,
                    short_code
                );
                Ok(url)
            }
            Err(e) => {
                tracing::error!(
                    "Error from cache manager for {}:{}: {}",
                    short_link_domain,
                    short_code,
                    e
                );
                Err(e)
            }
        }
    }

    async fn store_url(
        &self,
        redirect_url: &str,
        short_string: &str,
    ) -> Result<String, RedirectError> {
        // Cache the URL using the cache manager
        self.cache_manager
            .cache_url(
                short_string,
                &self.default_domain_for_public_store,
                redirect_url.to_string(),
                Some(TWENTY_FOUR_HOURS_IN_SECONDS),
            )
            .await?;
        Ok(short_string.to_string())
    }
}

#[async_trait]
impl RedirectServiceTrait for InternalRedirectService {
    async fn redirect_url(
        &self,
        short_code: &str,
        short_link_domain: &str,
    ) -> Result<String, RedirectError> {
        // Attempt to get from the cache manager (local Moka cache then Redis)
        match self
            .cache_manager
            .get_cached_url(short_code, short_link_domain)
            .await
        {
            Ok(url) => {
                tracing::debug!(
                    "Cache hit via manager for {}:{}",
                    short_link_domain,
                    short_code
                );
                Ok(url)
            }
            Err(RedirectError::LinkNotFound) => {
                // Cache miss from both local and Redis tier of the cache manager
                tracing::debug!(
                    "Cache miss via manager for {}:{}, fetching from database.",
                    short_link_domain,
                    short_code
                );
                let db_url = self
                    .fetch_redirect_url_from_database(short_code, short_link_domain)
                    .await?;

                // Cache the freshly fetched URL using the cache manager.
                // This will populate both local Moka cache and Redis.
                // Using default TTL as defined in RedisRedirectCacheManager, or pass a specific one if needed.
                if let Err(cache_err) = self
                    .cache_manager
                    .cache_url(short_code, short_link_domain, db_url.clone(), None)
                    .await
                {
                    // Log caching error but still return the URL from DB as the primary operation succeeded.
                    tracing::error!(
                        "Failed to cache URL for {}:{} via manager: {}",
                        short_link_domain,
                        short_code,
                        cache_err
                    );
                }
                Ok(db_url)
            }
            Err(e) => {
                // Other errors from cache_manager (e.g., underlying RedisError propagated by RedirectCacheManager)
                tracing::error!(
                    "Error from cache manager for {}:{}: {}",
                    short_link_domain,
                    short_code,
                    e
                );
                Err(e)
            }
        }
    }

    async fn store_url(
        &self,
        _redirect_url: &str,
        _short_string: &str,
    ) -> Result<String, RedirectError> {
        Err(RedirectError::InvalidOperation(
            "store_url not supported for internal redirects".into(),
        ))
    }
}

#[cfg(test)]
mod tests {
    use crate::{
        redirect::{
            redirect_cache::RedisRedirectCacheManager, redis_utils::RedisRedirectKeyPrefix,
        },
        utils::test_utils::{
            insert_new_link_in_pg, insert_new_team_in_pg, random_string, setup_pg_client,
        },
    };

    use super::*;
    use crate::utils::generator::generate_base62_string;
    use anyhow::Result;
    use common_redis::{MockRedisClient, MockRedisValue};
    use std::sync::Arc;

    const PHOG_GG_DOMAIN: &str = "phog.gg";

    #[tokio::test]
    async fn test_should_redirect_external_url() {
        let mut redis_client = MockRedisClient::new();
        let key = "p2dsws3";
        let short_link_domain = "example.com";
        let redirect_url = "https://example.com".to_string();
        redis_client.get_ret(
            &RedisRedirectKeyPrefix::External.get_redis_key_for_url(short_link_domain, key),
            Ok(redirect_url.clone()),
        );
        let cache_manager = RedisRedirectCacheManager::new(
            Arc::new(redis_client),
            RedisRedirectKeyPrefix::External,
        );

        let service =
            ExternalRedirectService::new(Arc::new(cache_manager), PHOG_GG_DOMAIN.to_string());
        let result = service.redirect_url(key, short_link_domain).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), redirect_url);
    }

    #[tokio::test]
    async fn test_should_return_link_not_found_for_external() {
        let mut redis_client = MockRedisClient::new();
        let key = "p2dsws3";
        let short_link_domain = "example.com";
        redis_client.get_ret(
            &RedisRedirectKeyPrefix::External.get_redis_key_for_url(short_link_domain, key),
            Err(CustomRedisError::NotFound),
        );
        let cache_manager = RedisRedirectCacheManager::new(
            Arc::new(redis_client),
            RedisRedirectKeyPrefix::External,
        );

        let service =
            ExternalRedirectService::new(Arc::new(cache_manager), PHOG_GG_DOMAIN.to_string());
        let result = service.redirect_url(key, short_link_domain).await;
        if !matches!(result, Err(RedirectError::LinkNotFound)) {
            panic!("Expected LinkNotFound error");
        }
    }

    #[tokio::test]
    async fn test_should_redirect_internal_url_if_in_cache_manager() {
        let db_client = setup_pg_client(None).await;

        let key = "p2dsws3";
        let short_link_domain = "example.com";
        let redirect_url = "https://example.com".to_string();
        let mut redis_client = MockRedisClient::new();
        redis_client.get_ret(
            &RedisRedirectKeyPrefix::Internal.get_redis_key_for_url(short_link_domain, key),
            Ok(redirect_url.clone()),
        );
        let cache_manager = RedisRedirectCacheManager::new(
            Arc::new(redis_client),
            RedisRedirectKeyPrefix::Internal,
        );

        let service = InternalRedirectService::new(db_client, Arc::new(cache_manager));
        let result = service.redirect_url(key, short_link_domain).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), "https://example.com");
    }

    #[tokio::test]
    async fn test_should_store_external_url() {
        let mut redis_client = MockRedisClient::new();
        let redirect_url = "https://example.com";
        let short_code = generate_base62_string();
        let key =
            RedisRedirectKeyPrefix::External.get_redis_key_for_url(PHOG_GG_DOMAIN, &short_code);

        redis_client.set_nx_ex_ret(&key, Ok(true));
        let cache_manager = RedisRedirectCacheManager::new(
            Arc::new(redis_client),
            RedisRedirectKeyPrefix::External,
        );

        let service =
            ExternalRedirectService::new(Arc::new(cache_manager), PHOG_GG_DOMAIN.to_string());
        let result = service.store_url(redirect_url, &short_code).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), short_code);
    }

    #[tokio::test]
    async fn test_should_redirect_internal_url_if_in_database_and_should_be_cached() -> Result<()> {
        let mut redis_client = MockRedisClient::new();
        let cache_manager = Arc::new(RedisRedirectCacheManager::new(
            Arc::new(redis_client.clone()),
            RedisRedirectKeyPrefix::Internal,
        ));
        let db_client = setup_pg_client(None).await;

        let key = &random_string("", 6);
        let short_link_domain = "example.com";
        let redirect_url = "https://example.com".to_string();

        redis_client.get_ret(
            &RedisRedirectKeyPrefix::Internal.get_redis_key_for_url(short_link_domain, key),
            Err(CustomRedisError::NotFound),
        );

        redis_client.set_nx_ex_ret(
            &RedisRedirectKeyPrefix::Internal.get_redis_key_for_url(short_link_domain, key),
            Ok(true),
        );

        let team = insert_new_team_in_pg(db_client.clone(), None).await?;
        insert_new_link_in_pg(
            db_client.clone(),
            short_link_domain,
            key,
            &redirect_url,
            team.id,
        )
        .await?;

        let service = InternalRedirectService::new(db_client, cache_manager.clone());
        let result = service.redirect_url(key, short_link_domain).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), redirect_url);
        // Check that the URL was cached
        let calls = redis_client.get_calls();

        assert_eq!(calls.len(), 2);
        assert_eq!(calls[1].op, "set_nx_ex");
        assert_eq!(
            calls[1].key,
            RedisRedirectKeyPrefix::Internal.get_redis_key_for_url(short_link_domain, key)
        );
        assert_eq!(
            calls[1].value,
            MockRedisValue::StringWithTTL(redirect_url, 24 * 60 * 60)
        );

        Ok(())
    }

    #[tokio::test]
    async fn test_should_fail_store_on_redis_error() {
        let mut redis_client = MockRedisClient::new();
        let redirect_url = "https://example.com";
        let short_string = generate_base62_string();
        let key =
            RedisRedirectKeyPrefix::External.get_redis_key_for_url(PHOG_GG_DOMAIN, &short_string);

        redis_client.set_nx_ex_ret(&key, Err(CustomRedisError::NotFound));
        let cache_manager = RedisRedirectCacheManager::new(
            Arc::new(redis_client),
            RedisRedirectKeyPrefix::External,
        );

        let service =
            ExternalRedirectService::new(Arc::new(cache_manager), PHOG_GG_DOMAIN.to_string());
        let result = service.store_url(redirect_url, &short_string).await;
        assert!(result.is_err());
        assert!(matches!(result, Err(RedirectError::RedisError(_))));
    }

    #[tokio::test]
    async fn test_should_fail_when_url_exists() {
        let mut redis_client = MockRedisClient::new();
        let redirect_url = "https://example.com";
        let short_string = generate_base62_string();
        let key =
            RedisRedirectKeyPrefix::External.get_redis_key_for_url(PHOG_GG_DOMAIN, &short_string);

        redis_client.set_nx_ex_ret(&key, Ok(false));
        let cache_manager = RedisRedirectCacheManager::new(
            Arc::new(redis_client),
            RedisRedirectKeyPrefix::External,
        );

        let service =
            ExternalRedirectService::new(Arc::new(cache_manager), PHOG_GG_DOMAIN.to_string());
        let result = service.store_url(redirect_url, &short_string).await;
        assert!(result.is_err());
        assert!(matches!(result, Err(RedirectError::InvalidOperation(_))));
    }
}
