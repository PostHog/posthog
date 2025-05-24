use crate::redirect::redirect_service::RedirectError;
use crate::redirect::redis_utils::RedisRedirectKeyPrefix;
use async_trait::async_trait;
use common_redis::{Client as RedisClient, CustomRedisError};
use metrics::counter;
use moka::future::Cache;
use std::sync::Arc;
use std::time::Duration;

const DEFAULT_CACHE_TTL_SECONDS: u64 = 60 * 60 * 24; // 24 hours

// Assuming average key length (domain + short_code) is ~17 characters
// Assuming average URL value length is ~150 characters
const AVERAGE_ENTRY_WEIGHT: u64 = 17 + 150; // 167
const TARGET_ITEM_COUNT: u64 = 10_000;
const LOCAL_CACHE_MAX_WEIGHT: u64 = TARGET_ITEM_COUNT * AVERAGE_ENTRY_WEIGHT; // 1,670,000

const CACHE_HITS_TOTAL: &str = "cache_hits_total";
const CACHE_MISSES_TOTAL: &str = "cache_misses_total";
const CACHE_EVICTIONS_TOTAL: &str = "cache_evictions_total";

#[async_trait]
pub trait RedirectCacheManager {
    async fn get_cached_url(
        &self,
        short_code: &str,
        short_link_domain: &str,
    ) -> Result<String, RedirectError>;
    async fn cache_url(
        &self,
        short_code: &str,
        short_link_domain: &str,
        redirect_url: String,
        ttl_seconds: Option<u64>,
    ) -> Result<(), RedirectError>;
}

pub struct RedisRedirectCacheManager {
    redis_client: Arc<dyn RedisClient + Send + Sync>,
    prefix: RedisRedirectKeyPrefix,
    local_cache: Cache<String, String>,
}

impl RedisRedirectCacheManager {
    pub fn new(
        redis_client: Arc<dyn RedisClient + Send + Sync>,
        prefix: RedisRedirectKeyPrefix,
    ) -> Self {
        let link_src = prefix.to_string();
        let local_cache: Cache<String, String> = Cache::builder()
            .name(&format!("redirect_cache_{}", prefix))
            .max_capacity(LOCAL_CACHE_MAX_WEIGHT)
            // Adds the length of the key and value to the weight, adding another
            // dimension to the cache eviction policy, so that links that are longer
            // will have a higher weight and therefore will be more likely to be evicted,
            // in order to maximize the number of links that can be cached.
            .weigher(|key: &String, value: &String| -> u32 {
                (key.len() + value.len()).try_into().unwrap_or(u32::MAX)
            })
            .time_to_live(Duration::from_secs(DEFAULT_CACHE_TTL_SECONDS))
            .eviction_listener(move |_key, _value, cause| {
                counter!(
                    CACHE_EVICTIONS_TOTAL,
                    &[
                        ("link_src", link_src.clone()),
                        ("cache_type", "local".to_string()),
                        ("reason", format!("{:?}", cause)),
                    ]
                )
                .increment(1);
            })
            .build();

        Self {
            redis_client,
            prefix,
            local_cache,
        }
    }

    fn get_cache_key(&self, short_code: &str, short_link_domain: &str) -> String {
        format!("{}:{}", short_link_domain, short_code)
    }
}

#[async_trait]
impl RedirectCacheManager for RedisRedirectCacheManager {
    async fn get_cached_url(
        &self,
        short_code: &str,
        short_link_domain: &str,
    ) -> Result<String, RedirectError> {
        let cache_key = self.get_cache_key(short_code, short_link_domain);

        // Try local cache first
        if let Some(url) = self.local_cache.get(&cache_key).await {
            counter!(
                CACHE_HITS_TOTAL,
                &[
                    ("link_src", self.prefix.to_string()),
                    ("cache_type", "local".to_string()),
                ]
            )
            .increment(1);
            tracing::debug!("Local cache hit for key: {}", cache_key);
            return Ok(url);
        }

        counter!(
            CACHE_MISSES_TOTAL,
            &[
                ("link_src", self.prefix.to_string()),
                ("cache_type", "local".to_string()),
            ]
        )
        .increment(1);

        // If not in local cache, try Redis
        let redis_key = self
            .prefix
            .get_redis_key_for_url(short_link_domain, short_code);
        match self.redis_client.get(redis_key).await {
            Ok(url) => {
                // Store in local cache for future requests
                self.local_cache.insert(cache_key, url.clone()).await;
                Ok(url)
            }
            Err(CustomRedisError::NotFound) => Err(RedirectError::LinkNotFound),
            Err(e) => Err(RedirectError::RedisError(e)),
        }
    }

    async fn cache_url(
        &self,
        short_code: &str,
        short_link_domain: &str,
        redirect_url: String,
        ttl_seconds: Option<u64>,
    ) -> Result<(), RedirectError> {
        let cache_key = self.get_cache_key(short_code, short_link_domain);
        let redis_key = self
            .prefix
            .get_redis_key_for_url(short_link_domain, short_code);
        let ttl = ttl_seconds.unwrap_or(DEFAULT_CACHE_TTL_SECONDS);

        // Cache in Redis
        match self
            .redis_client
            .set_nx_ex(redis_key, redirect_url.clone(), ttl)
            .await
        {
            Ok(true) => {
                // Cache locally
                self.local_cache.insert(cache_key, redirect_url).await;
                Ok(())
            }
            Ok(false) => Err(RedirectError::InvalidOperation(
                "URL already exists".to_string(),
            )),
            Err(e) => Err(RedirectError::from(e)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;

    #[tokio::test]
    async fn test_get_cached_url_local_cache() {
        let mock_redis = MockRedisClient::new();
        // With common_redis::MockRedisClient, if get is called without a prior get_ret for the key, it will panic.
        // So, not calling get_ret here effectively means we expect redis_client.get not to be called with an unexpected key.
        let cache_manager =
            RedisRedirectCacheManager::new(Arc::new(mock_redis), RedisRedirectKeyPrefix::Internal);

        // Populate local cache
        cache_manager
            .local_cache
            .insert(
                "phog.gg:abc123".to_string(),
                "https://example.com".to_string(),
            )
            .await;

        let result = cache_manager.get_cached_url("abc123", "phog.gg").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), "https://example.com");
    }

    #[tokio::test]
    async fn test_get_cached_url_redis() {
        let mut mock_redis = MockRedisClient::new();
        let expected_key =
            RedisRedirectKeyPrefix::Internal.get_redis_key_for_url("phog.gg", "abc123");
        mock_redis.get_ret(&expected_key, Ok("https://example.com".to_string()));

        let cache_manager =
            RedisRedirectCacheManager::new(Arc::new(mock_redis), RedisRedirectKeyPrefix::Internal);

        let result = cache_manager.get_cached_url("abc123", "phog.gg").await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), "https://example.com");

        // Verify it was stored in local cache
        let local_result = cache_manager.local_cache.get("phog.gg:abc123").await;
        assert_eq!(local_result.unwrap(), "https://example.com");
    }

    #[tokio::test]
    async fn test_cache_url() {
        let mut mock_redis = MockRedisClient::new();
        let expected_redis_key =
            RedisRedirectKeyPrefix::Internal.get_redis_key_for_url("phog.gg", "abc123");
        mock_redis.set_nx_ex_ret(&expected_redis_key, Ok(true));

        let cache_manager =
            RedisRedirectCacheManager::new(Arc::new(mock_redis), RedisRedirectKeyPrefix::Internal);

        let result = cache_manager
            .cache_url("abc123", "phog.gg", "https://example.com".to_string(), None)
            .await;

        assert!(result.is_ok());

        // Verify it was stored in local cache
        let local_result = cache_manager.local_cache.get("phog.gg:abc123").await;
        assert_eq!(local_result.unwrap(), "https://example.com");
    }
}
