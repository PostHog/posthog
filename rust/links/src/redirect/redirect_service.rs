use async_trait::async_trait;
use std::sync::Arc; // Add this crate for async traits
use thiserror::Error;

use common_database::Client as DatabaseClient;
use common_redis::{Client as RedisClient, CustomRedisError};

use crate::types::LinksRedisItem;

use super::{redirect_query::fetch_redirect_item, redis_utils::RedisRedirectKeyPrefix};

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
    ) -> Result<LinksRedisItem, RedirectError>;

    async fn store_url(
        &self,
        redirect_url: &str,
        short_string: &str,
    ) -> Result<String, RedirectError>;
}

pub struct ExternalRedirectService {
    redis_client: Arc<dyn RedisClient + Send + Sync>,
    default_domain_for_public_store: String,
}

impl ExternalRedirectService {
    pub fn new(
        redis_client: Arc<dyn RedisClient + Send + Sync>,
        default_domain_for_public_store: String,
    ) -> Self {
        Self {
            redis_client,
            default_domain_for_public_store,
        }
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

    async fn fetch_redirect_item_from_database(
        &self,
        short_code: &str,
        short_link_domain: &str,
    ) -> Result<LinksRedisItem, RedirectError> {
        let redirect_item =
            fetch_redirect_item(self.db_reader_client.clone(), short_link_domain, short_code)
                .await?;

        // If serialization or redis set fails, we shouldn't fail the retrieval and just log
        if let Ok(serialized) = serde_json::to_string(&redirect_item) {
            if let Err(error) = self
                .redis_client
                .set_nx_ex(
                    RedisRedirectKeyPrefix::Internal
                        .get_redis_key_for_url(short_link_domain, short_code),
                    serialized,
                    60 * 60 * 24, // 1 day
                )
                .await
            {
                // TODO: add metric here
                tracing::error!("Failed to write to redis: {}", error);
            }
        } else {
            tracing::error!("Failed to serialize redirect item");
        }

        Ok(redirect_item)
    }
}

const TWENTY_FOUR_HOURS_IN_SECONDS: u64 = 60 * 60 * 24;

#[async_trait]
impl RedirectServiceTrait for ExternalRedirectService {
    async fn redirect_url(
        &self,
        short_code: &str,
        short_link_domain: &str,
    ) -> Result<LinksRedisItem, RedirectError> {
        // Try Redis first
        tracing::info!(
            "Fetching redirect URL from Redis for key {} and domain {}",
            short_code,
            short_link_domain
        );

        match self
            .redis_client
            .get(
                RedisRedirectKeyPrefix::External
                    .get_redis_key_for_url(short_link_domain, short_code),
            )
            .await
        {
            Ok(item_str) => {
                let item = serde_json::from_str(&item_str).map_err(|e| {
                    tracing::error!("Failed to parse item: {}", e);
                    RedirectError::InvalidOperation(e.to_string())
                })?;

                Ok(item)
            }
            Err(error) => match error {
                CustomRedisError::NotFound => Err(RedirectError::LinkNotFound),
                error => Err(error.into()),
            },
        }
    }

    async fn store_url(
        &self,
        redirect_url: &str,
        short_string: &str,
    ) -> Result<String, RedirectError> {
        let key = RedisRedirectKeyPrefix::External
            .get_redis_key_for_url(&self.default_domain_for_public_store, short_string);

        // First check if the key exists
        match self
            .redis_client
            .set_nx_ex(key, redirect_url.to_string(), TWENTY_FOUR_HOURS_IN_SECONDS)
            .await
        {
            Ok(true) => Ok(short_string.to_string()),
            Ok(false) => Err(RedirectError::InvalidOperation(
                "Redirect URL already exists".into(),
            )),
            Err(e) => Err(e.into()),
        }
    }
}

#[async_trait]
impl RedirectServiceTrait for InternalRedirectService {
    async fn redirect_url(
        &self,
        short_code: &str,
        short_link_domain: &str,
    ) -> Result<LinksRedisItem, RedirectError> {
        match self
            .redis_client
            .get(
                RedisRedirectKeyPrefix::Internal
                    .get_redis_key_for_url(short_link_domain, short_code),
            )
            .await
        {
            Ok(item) => match serde_json::from_str(&item) {
                Ok(parsed_item) => Ok(parsed_item),
                Err(_) => Err(RedirectError::InvalidOperation(
                    "Failed to parse item".into(),
                )),
            },
            Err(error) => match error {
                CustomRedisError::NotFound => {
                    self.fetch_redirect_item_from_database(short_code, short_link_domain)
                        .await
                }
                error => Err(error.into()),
            },
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
    use crate::utils::test_utils::{
        insert_new_link_in_pg, insert_new_team_in_pg, random_string, setup_pg_client,
    };

    use super::*;
    use crate::utils::generator::generate_base62_string;
    use anyhow::Result;
    use common_redis::MockRedisClient;

    use std::sync::Arc;

    const PHOG_GG_DOMAIN: &str = "phog.gg";

    #[tokio::test]
    async fn test_should_redirect_external_url() {
        let mut redis_client = MockRedisClient::new();
        let key = "p2dsws3";
        let short_link_domain = "example.com";

        let item = LinksRedisItem {
            url: "https://example.com".to_string(),
            team_id: Some(257),
        };
        redis_client.get_ret(
            &RedisRedirectKeyPrefix::External.get_redis_key_for_url(short_link_domain, key),
            Ok(serde_json::to_string(&item).unwrap()),
        );

        let service =
            ExternalRedirectService::new(Arc::new(redis_client), PHOG_GG_DOMAIN.to_string());
        let result = service.redirect_url(key, short_link_domain).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), item);
    }

    #[tokio::test]
    async fn test_should_redirect_external_url_with_no_team_id() {
        let mut redis_client = MockRedisClient::new();
        let key = "p2dsws3";
        let origin_domain = "example.com";

        let item = LinksRedisItem {
            url: "https://example.com".to_string(),
            team_id: None,
        };
        redis_client.get_ret(
            &RedisRedirectKeyPrefix::External.get_redis_key_for_url(origin_domain, key),
            Ok(serde_json::to_string(&item).unwrap()),
        );

        let service =
            ExternalRedirectService::new(Arc::new(redis_client), PHOG_GG_DOMAIN.to_string());
        let result = service.redirect_url(key, origin_domain).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), item);
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

        let service =
            ExternalRedirectService::new(Arc::new(redis_client), PHOG_GG_DOMAIN.to_string());
        let result = service.redirect_url(key, short_link_domain).await;
        if !matches!(result, Err(RedirectError::LinkNotFound)) {
            panic!("Expected LinkNotFound error");
        }
    }

    #[tokio::test]
    async fn test_should_redirect_internal_url_if_in_redis() {
        let mut redis_client = MockRedisClient::new();
        let db_client = setup_pg_client(None).await;
        let key = "p2dsws3";
        let short_link_domain = "example.com";

        let item = LinksRedisItem {
            url: "https://example.com".to_string(),
            team_id: Some(257),
        };
        let ret = Ok(serde_json::to_string(&item).unwrap());
        redis_client.get_ret(
            &RedisRedirectKeyPrefix::Internal.get_redis_key_for_url(short_link_domain, key),
            ret,
        );
        let service = InternalRedirectService::new(db_client, Arc::new(redis_client));
        let result = service.redirect_url(key, short_link_domain).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), item);
    }

    #[tokio::test]
    async fn test_should_store_external_url() {
        let mut redis_client = MockRedisClient::new();
        let short_link_domain = "https://example.com";
        let short_code = generate_base62_string();
        let key =
            RedisRedirectKeyPrefix::External.get_redis_key_for_url(PHOG_GG_DOMAIN, &short_code);

        // Should succeed
        redis_client.set_nx_ex_ret(&key, Ok(true));

        let service =
            ExternalRedirectService::new(Arc::new(redis_client), PHOG_GG_DOMAIN.to_string());
        let result = service.store_url(short_link_domain, &short_code).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), short_code);
    }

    #[tokio::test]
    async fn test_should_redirect_internal_url_if_in_database() -> Result<()> {
        let redis_client = MockRedisClient::new();
        let db_client = setup_pg_client(None).await;
        let key = &random_string("", 6);
        let short_link_domain = "example.com";
        let redirect_url = "https://example.com".to_string();

        let team = insert_new_team_in_pg(db_client.clone(), None).await?;
        insert_new_link_in_pg(
            db_client.clone(),
            short_link_domain,
            key,
            &redirect_url,
            team.id,
        )
        .await?;

        let service = InternalRedirectService::new(db_client, Arc::new(redis_client));
        let result = service.redirect_url(key, short_link_domain).await;
        assert!(result.is_ok());
        assert_eq!(
            result.unwrap(),
            LinksRedisItem {
                url: redirect_url,
                team_id: Some(team.id),
            }
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

        redis_client.get_ret(&key, Err(CustomRedisError::NotFound));
        redis_client.set_nx_ex_ret(&key, Err(CustomRedisError::NotFound));

        let service =
            ExternalRedirectService::new(Arc::new(redis_client), PHOG_GG_DOMAIN.to_string());
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

        let service =
            ExternalRedirectService::new(Arc::new(redis_client), PHOG_GG_DOMAIN.to_string());
        let result = service.store_url(redirect_url, &short_string).await;

        assert!(result.is_err());
        assert!(matches!(result, Err(RedirectError::InvalidOperation(_))));
    }
}
