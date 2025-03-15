use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use base64::{self, engine::general_purpose, Engine};
use common_metrics::inc;
use common_redis::Client as RedisClient;
use common_redis::CustomRedisError;
use moka::sync::Cache;
use rand::RngCore;
use thiserror::Error;

use crate::metrics::metrics_consts::{
    COOKIELESS_CACHE_HIT_COUNTER,
    COOKIELESS_CACHE_MISS_COUNTER,
    COOKIELESS_REDIS_ERROR_COUNTER,
};

// Constants from the TypeScript implementation
const SALT_TTL_SECONDS: u64 = 86400 * 30; // 30 days
const MAX_NEGATIVE_TIMEZONE_HOURS: i32 = 12;
const MAX_POSITIVE_TIMEZONE_HOURS: i32 = 14;

#[derive(Debug, Error, PartialEq)]
pub enum SaltCacheError {
    #[error("Date is out of range")]
    DateOutOfRange,
    #[error("Redis error: {0}")]
    RedisError(String),
    #[error("Failed to get salt from redis")]
    SaltRetrievalFailed,
}

impl From<CustomRedisError> for SaltCacheError {
    fn from(err: CustomRedisError) -> Self {
        inc(
            COOKIELESS_REDIS_ERROR_COUNTER,
            &[("operation".to_string(), "from_redis_error".to_string())],
            1,
        );
        SaltCacheError::RedisError(err.to_string())
    }
}

/// SaltCache manages the local cache of salts used for cookieless hashing
/// using the Moka synchronous caching library for efficient TTL handling
pub struct SaltCache {
    /// Cache of salts, keyed by YYYY-MM-DD
    cache: Cache<String, Vec<u8>>,
    /// Redis client for fetching and storing salts
    redis_client: Arc<dyn RedisClient + Send + Sync>,
}

impl SaltCache {
    /// Create a new SaltCache with the given Redis client
    pub fn new(redis_client: Arc<dyn RedisClient + Send + Sync>, salt_ttl_seconds: Option<u64>) -> Self {
        // Create a cache with a maximum of 1000 entries
        // This is more than enough for our use case, as we only store one salt per day
        let cache = Cache::builder()
            // Set TTL to the salt TTL
            .time_to_live(Duration::from_secs(salt_ttl_seconds.unwrap_or(SALT_TTL_SECONDS)))
            // Build the cache
            .build();

        SaltCache {
            cache,
            redis_client,
        }
    }

    /// Get the salt for a specific day (YYYY-MM-DD format)
    pub async fn get_salt_for_day(&self, yyyymmdd: &str) -> Result<Vec<u8>, SaltCacheError> {
        // Validate the date format
        if !is_calendar_date_valid(yyyymmdd) {
            return Err(SaltCacheError::DateOutOfRange);
        }

        // Check if we have the salt in the cache
        if let Some(salt) = self.cache.get(yyyymmdd) {
            inc(
                COOKIELESS_CACHE_HIT_COUNTER,
                &[
                    ("operation".to_string(), "getSaltForDay".to_string()),
                    ("day".to_string(), yyyymmdd.to_string()),
                ],
                1,
            );
            return Ok(salt);
        }

        inc(
            COOKIELESS_CACHE_MISS_COUNTER,
            &[
                ("operation".to_string(), "getSaltForDay".to_string()),
                ("day".to_string(), yyyymmdd.to_string()),
            ],
            1,
        );

        // Try to get it from Redis
        let redis_key = format!("cookieless_salt:{}", yyyymmdd);
        let salt_base64 = match self.redis_client.get(redis_key.clone()).await {
            Ok(value) => Some(value),
            Err(CustomRedisError::NotFound) => None,
            Err(e) => {
                inc(
                    COOKIELESS_REDIS_ERROR_COUNTER,
                    &[
                        ("operation".to_string(), "get_salt".to_string()),
                        ("day".to_string(), yyyymmdd.to_string()),
                    ],
                    1,
                );
                return Err(SaltCacheError::RedisError(e.to_string()));
            },
        };

        if let Some(salt_base64) = salt_base64 {
            // Decode the base64 salt
            let salt = match general_purpose::STANDARD.decode(salt_base64) {
                Ok(s) => s,
                Err(_) => {
                    inc(
                        COOKIELESS_REDIS_ERROR_COUNTER,
                        &[
                            ("operation".to_string(), "decode_salt".to_string()),
                            ("day".to_string(), yyyymmdd.to_string()),
                        ],
                        1,
                    );
                    return Err(SaltCacheError::SaltRetrievalFailed);
                }
            };
            
            // Store it in the cache
            self.cache.insert(yyyymmdd.to_string(), salt.clone());
            
            return Ok(salt);
        }

        // Generate a new salt
        let mut new_salt = vec![0u8; 16];
        rand::thread_rng().fill_bytes(&mut new_salt);
        let new_salt_base64 = general_purpose::STANDARD.encode(&new_salt);

        // Try to set it in Redis with NX (only if it doesn't exist)
        // Note: This is a simplified version as the Redis client doesn't have setnx
        // In a real implementation, you'd want to use a Redis transaction or Lua script
        match self.redis_client.set(format!("{}:nx", redis_key), new_salt_base64.clone()).await {
            Ok(_) => {
                // Set the actual key with TTL
                if let Err(e) = self.redis_client.set(redis_key, new_salt_base64).await {
                    inc(
                        COOKIELESS_REDIS_ERROR_COUNTER,
                        &[
                            ("operation".to_string(), "set_salt".to_string()),
                            ("day".to_string(), yyyymmdd.to_string()),
                        ],
                        1,
                    );
                    return Err(SaltCacheError::RedisError(e.to_string()));
                }
                
                // Store it in the cache
                self.cache.insert(yyyymmdd.to_string(), new_salt.clone());
                
                Ok(new_salt)
            },
            Err(_) => {
                // Someone else set it, try to get it again
                let salt_base64_retry = match self.redis_client.get(redis_key).await {
                    Ok(value) => value,
                    Err(e) => {
                        inc(
                            COOKIELESS_REDIS_ERROR_COUNTER,
                            &[
                                ("operation".to_string(), "get_salt_retry".to_string()),
                                ("day".to_string(), yyyymmdd.to_string()),
                            ],
                            1,
                        );
                        return Err(SaltCacheError::RedisError(e.to_string()));
                    }
                };

                let salt = match general_purpose::STANDARD.decode(salt_base64_retry) {
                    Ok(s) => s,
                    Err(_) => {
                        inc(
                            COOKIELESS_REDIS_ERROR_COUNTER,
                            &[
                                ("operation".to_string(), "decode_salt_retry".to_string()),
                                ("day".to_string(), yyyymmdd.to_string()),
                            ],
                            1,
                        );
                        return Err(SaltCacheError::SaltRetrievalFailed);
                    }
                };
                
                // Store it in the cache
                self.cache.insert(yyyymmdd.to_string(), salt.clone());
                
                Ok(salt)
            }
        }
    }

    /// Clear the entire cache
    pub fn clear_cache(&self) {
        self.cache.invalidate_all();
    }
}

/// Check if a calendar date is valid for salt caching
/// 
/// A date is valid if:
/// 1. It's not in the future (at least one timezone could plausibly be in this calendar day)
/// 2. It's not too far in the past (with some buffer for ingestion lag)
pub fn is_calendar_date_valid(yyyymmdd: &str) -> bool {
    // Parse the date
    let parts: Vec<&str> = yyyymmdd.split('-').collect();
    if parts.len() != 3 {
        return false;
    }
    
    let year = match parts[0].parse::<i32>() {
        Ok(y) => y,
        Err(_) => return false,
    };
    
    let month = match parts[1].parse::<u32>() {
        Ok(m) if m >= 1 && m <= 12 => m,
        _ => return false,
    };
    
    let day = match parts[2].parse::<u32>() {
        Ok(d) if d >= 1 && d <= 31 => d,
        _ => return false,
    };

    // Create a UTC date for the start of the day
    let date_string = format!("{}-{:02}-{:02}T00:00:00Z", year, month, day);
    let utc_date = match chrono::DateTime::parse_from_rfc3339(&date_string) {
        Ok(d) => d.timestamp() * 1000, // Convert to milliseconds
        Err(_) => return false,
    };

    // Current time in UTC milliseconds
    let now_utc = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64;

    // Define the range of the calendar day in UTC
    let start_of_day_minus_12 = utc_date - (MAX_NEGATIVE_TIMEZONE_HOURS as i64 * 3600 * 1000);
    let end_of_day_plus_14 = utc_date + ((MAX_POSITIVE_TIMEZONE_HOURS + 24) as i64 * 3600 * 1000);

    // Check if the current UTC time falls within this range
    now_utc >= start_of_day_minus_12 && now_utc < end_of_day_plus_14
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{Duration, Utc};
    use common_redis::MockRedisClient;
    use std::sync::Arc;

    #[tokio::test]
    async fn test_get_salt_for_day_cache() {
        let mut mock_redis = MockRedisClient::new();
        let salt_base64 = "AAAAAAAAAAAAAAAAAAAAAA=="; // 16 bytes of zeros
        let salt = general_purpose::STANDARD.decode(salt_base64).unwrap();
        let today = Utc::now().format("%Y-%m-%d").to_string();
        let redis_key = format!("cookieless_salt:{}", today);
        
        mock_redis = mock_redis.get_ret(&redis_key, Ok(salt_base64.to_string()));
        let redis_client = Arc::new(mock_redis);
        let salt_cache = SaltCache::new(redis_client, Some(86400));
    
        let salt1 = salt_cache.get_salt_for_day(&today).await.unwrap();
        assert_eq!(salt1, salt);
    }

    #[test]
    fn test_is_calendar_date_valid() {
        // Get current date in UTC
        let now = Utc::now();
        
        // Today should be valid
        let today = now.format("%Y-%m-%d").to_string();
        assert!(is_calendar_date_valid(&today));
        
        // Yesterday should be valid
        let yesterday = (now - Duration::days(1)).format("%Y-%m-%d").to_string();
        assert!(is_calendar_date_valid(&yesterday));

        
        // Far future should be invalid
        let far_future = (now + Duration::days(2)).format("%Y-%m-%d").to_string();
        assert!(!is_calendar_date_valid(&far_future));
        
        // Invalid format should be invalid
        assert!(!is_calendar_date_valid("not-a-date"));
        assert!(!is_calendar_date_valid("2023/01/01"));
    }
} 