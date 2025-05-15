use async_trait::async_trait;
use std::sync::Arc; // Add this crate for async traits
use thiserror::Error;

use common_database::Client as DatabaseClient;
use common_redis::{Client as RedisClient, CustomRedisError};

use super::{redirect_query::fetch_redirect_url, redis_utils::RedisRedirectKeyPrefix};

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
}

#[async_trait]
pub trait RedirectServiceTrait {
    async fn redirect_url(
        &self,
        origin_key: &str,
        origin_domain: &str,
    ) -> Result<String, RedirectError>;
}

pub struct ExternalRedirectService {
    redis_client: Arc<dyn RedisClient + Send + Sync>,
}

impl ExternalRedirectService {
    pub fn new(redis_client: Arc<dyn RedisClient + Send + Sync>) -> Self {
        Self { redis_client }
    }
}

pub struct InternalRedirectService {
    db_reader_client: Arc<dyn DatabaseClient + Send + Sync>,
    redis_client: Arc<dyn RedisClient + Send + Sync>,
}

impl InternalRedirectService {
    pub fn new(
        db_reader_client: Arc<dyn DatabaseClient + Send + Sync>,
        redis_client: Arc<dyn RedisClient + Send + Sync>,
    ) -> Self {
        Self {
            db_reader_client,
            redis_client,
        }
    }

    async fn fetch_redirect_url_from_database(
        &self,
        origin_key: &str,
        origin_domain: &str,
    ) -> Result<String, RedirectError> {
        let redirect_url =
            fetch_redirect_url(self.db_reader_client.clone(), origin_domain, origin_key).await?;
        // If redis set fails, we shouldn't fail the retrieval and just log
        if let Err(error) = self
            .redis_client
            .set(
                RedisRedirectKeyPrefix::Internal.get_redis_key_for_url(origin_domain, origin_key),
                redirect_url.clone(),
            )
            .await
        {
            // TODO: add metric here
            tracing::error!("Failed to write to redis: {}", error);
        }
        Ok(redirect_url)
    }
}

#[async_trait]
impl RedirectServiceTrait for ExternalRedirectService {
    async fn redirect_url(
        &self,
        origin_key: &str,
        origin_domain: &str,
    ) -> Result<String, RedirectError> {
        // Try Redis first
        tracing::info!(
            "Fetching redirect URL from Redis for key {} and domain {}",
            origin_key,
            origin_domain
        );
        match self
            .redis_client
            .get(RedisRedirectKeyPrefix::External.get_redis_key_for_url(origin_domain, origin_key))
            .await
        {
            Ok(redirect_url) => Ok(redirect_url),
            Err(error) => match error {
                CustomRedisError::NotFound => Err(RedirectError::LinkNotFound),
                error => Err(error.into()),
            },
        }
    }
}

#[async_trait]
impl RedirectServiceTrait for InternalRedirectService {
    async fn redirect_url(
        &self,
        origin_key: &str,
        origin_domain: &str,
    ) -> Result<String, RedirectError> {
        match self
            .redis_client
            .get(RedisRedirectKeyPrefix::Internal.get_redis_key_for_url(origin_domain, origin_key))
            .await
        {
            Ok(redirect_url) => Ok(redirect_url),
            Err(error) => match error {
                CustomRedisError::NotFound => {
                    self.fetch_redirect_url_from_database(origin_key, origin_domain)
                        .await
                }
                error => Err(error.into()),
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;
    use std::sync::Arc;

    #[tokio::test]
    async fn test_should_redirect_external_url() {
        let mut redis_client = MockRedisClient::new();
        let key = "p2dsws3";
        let origin_domain = "example.com";
        let redirect_url = "https://example.com".to_string();
        let ret = Ok(redirect_url.clone());
        redis_client.get_ret(
            &RedisRedirectKeyPrefix::External.get_redis_key_for_url(origin_domain, key),
            ret,
        );

        let service = ExternalRedirectService::new(Arc::new(redis_client));
        let result = service.redirect_url(key, origin_domain).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), redirect_url);
    }

    #[tokio::test]
    async fn test_should_return_link_not_found_for_internal() {
        let mut redis_client = MockRedisClient::new();
        let key = "p2dsws3";
        let origin_domain = "example.com";
        redis_client.get_ret(
            &RedisRedirectKeyPrefix::External.get_redis_key_for_url(origin_domain, key),
            Err(CustomRedisError::NotFound),
        );

        let service = ExternalRedirectService::new(Arc::new(redis_client));
        let result = service.redirect_url(key, origin_domain).await;
        if !matches!(result, Err(RedirectError::LinkNotFound)) {
            panic!("Expected LinkNotFound error");
        }
    }
}
