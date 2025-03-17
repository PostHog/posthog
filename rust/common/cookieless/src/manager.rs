use std::str::FromStr;
use std::sync::Arc;

use base64::{engine::general_purpose, Engine};
use chrono::{DateTime, Utc};
use public_suffix::{EffectiveTLDProvider, DEFAULT_PROVIDER};
use thiserror::Error;
use url::Url;

use crate::constants::{
    COOKIELESS_SENTINEL_VALUE, IDENTIFIES_TTL_SECONDS, SALT_TTL_SECONDS, SESSION_INACTIVITY_MS,
    SESSION_TTL_SECONDS, TIMEZONE_FALLBACK,
};
use crate::hash::{do_hash, HashError};
use crate::salt_cache::{SaltCache, SaltCacheError};
use common_redis::Client as RedisClient;

#[derive(Debug, Error)]
pub enum CookielessManagerError {
    #[error("Salt cache error: {0}")]
    SaltCacheError(#[from] SaltCacheError),

    #[error("Hash error: {0}")]
    HashError(#[from] HashError),

    #[error("Invalid URL: {0}")]
    UrlParseError(#[from] url::ParseError),

    #[error("Cookieless mode is disabled")]
    Disabled,

    #[error("Missing required property: {0}")]
    MissingProperty(String),

    #[error("Invalid timestamp: {0}")]
    InvalidTimestamp(String),

    #[error("Chrono error: {0}")]
    ChronoError(#[from] chrono::ParseError),

    #[error("Timezone error: {0}")]
    TimezoneError(String),
}

/// Configuration for the CookielessManager
#[derive(Debug, Clone)]
pub struct CookielessConfig {
    /// Whether cookieless mode is disabled
    pub disabled: bool,
    /// Whether to force stateless mode
    pub force_stateless_mode: bool,
    /// TTL for identifies (in seconds)
    pub identifies_ttl_seconds: u64,
    /// TTL for sessions (in seconds)
    pub session_ttl_seconds: u64,
    /// TTL for salts (in seconds)
    pub salt_ttl_seconds: u64,
    /// Session inactivity timeout (in milliseconds)
    pub session_inactivity_ms: u64,
}

impl Default for CookielessConfig {
    fn default() -> Self {
        Self {
            disabled: false,
            force_stateless_mode: false,
            identifies_ttl_seconds: IDENTIFIES_TTL_SECONDS,
            session_ttl_seconds: SESSION_TTL_SECONDS,
            salt_ttl_seconds: SALT_TTL_SECONDS,
            session_inactivity_ms: SESSION_INACTIVITY_MS,
        }
    }
}

/// Parameters for computing a hash
#[derive(Debug, Clone)]
pub struct HashParams<'a> {
    /// Timestamp in milliseconds
    pub timestamp_ms: u64,
    /// Event timezone
    pub event_time_zone: Option<&'a str>,
    /// Team timezone
    pub team_time_zone: &'a str,
    /// Team ID
    pub team_id: u64,
    /// IP address
    pub ip: &'a str,
    /// Host
    pub host: &'a str,
    /// User agent
    pub user_agent: &'a str,
    /// Counter value
    pub n: u64,
    /// Additional data to include in the hash
    pub hash_extra: &'a str,
}

/// Data for an event to be processed by the cookieless manager
#[derive(Debug, Clone)]
pub struct EventData<'a> {
    /// IP address
    pub ip: &'a str,
    /// Timestamp in milliseconds
    pub timestamp_ms: u64,
    /// Host
    pub host: &'a str,
    /// User agent
    pub user_agent: &'a str,
    /// Event timezone (optional)
    pub event_time_zone: Option<&'a str>,
    /// Additional data to include in the hash (optional)
    pub hash_extra: Option<&'a str>,
    /// Team ID
    pub team_id: u64,
    /// Team timezone (optional)
    pub team_time_zone: Option<&'a str>,
}

/// Manager for cookieless tracking
pub struct CookielessManager {
    /// Configuration for the manager
    pub config: CookielessConfig,
    /// Salt cache for retrieving and storing salts
    salt_cache: SaltCache,
}

impl CookielessManager {
    /// Create a new CookielessManager
    pub fn new(config: CookielessConfig, redis_client: Arc<dyn RedisClient + Send + Sync>) -> Self {
        let salt_cache = SaltCache::new(redis_client, Some(config.salt_ttl_seconds));

        Self { config, salt_cache }
    }

    /// Get the salt for a specific day (YYYY-MM-DD format)
    pub async fn get_salt_for_day(
        &self,
        yyyymmdd: &str,
    ) -> Result<Vec<u8>, CookielessManagerError> {
        Ok(self.salt_cache.get_salt_for_day(yyyymmdd).await?)
    }

    /// Clear the salt cache
    pub fn clear_cache(&self) {
        self.salt_cache.clear_cache();
    }

    /// Compute a cookieless distinct ID for an event
    pub async fn compute_cookieless_distinct_id(
        &self,
        event_data: EventData<'_>,
    ) -> Result<String, CookielessManagerError> {
        // If cookieless mode is disabled, return an error
        if self.config.disabled {
            return Err(CookielessManagerError::Disabled);
        }

        // Validate required fields
        if event_data.ip.is_empty() {
            return Err(CookielessManagerError::MissingProperty("ip".to_string()));
        }
        if event_data.host.is_empty() {
            return Err(CookielessManagerError::MissingProperty("host".to_string()));
        }
        if event_data.user_agent.is_empty() {
            return Err(CookielessManagerError::MissingProperty("user_agent".to_string()));
        }

        // Get the team timezone or use UTC as fallback
        let team_time_zone = event_data.team_time_zone.unwrap_or(TIMEZONE_FALLBACK);

        // Create hash parameters
        let hash_params = HashParams {
            timestamp_ms: event_data.timestamp_ms,
            event_time_zone: event_data.event_time_zone,
            team_time_zone,
            team_id: event_data.team_id,
            ip: event_data.ip,
            host: event_data.host,
            user_agent: event_data.user_agent,
            n: 0, // For now, we don't support identify events, so n is always 0
            hash_extra: event_data.hash_extra.unwrap_or(""),
        };

        // Compute the hash
        let hash = self.do_hash_for_day(hash_params).await?;

        // Convert the hash to a distinct ID
        Ok(Self::hash_to_distinct_id(&hash))
    }

    /// Compute a hash for a specific day
    pub async fn do_hash_for_day(
        &self,
        params: HashParams<'_>,
    ) -> Result<Vec<u8>, CookielessManagerError> {
        let yyyymmdd = to_yyyy_mm_dd_in_timezone_safe(
            params.timestamp_ms,
            params.event_time_zone,
            params.team_time_zone,
        )?;
        let salt = self.get_salt_for_day(&yyyymmdd).await?;

        // Extract the root domain from the host
        let root_domain = extract_root_domain(params.host)?;

        // Compute the hash
        Ok(do_hash(
            &salt,
            params.team_id,
            params.ip,
            &root_domain,
            params.user_agent,
            params.n,
            params.hash_extra,
        )?)
    }

    /// Convert a hash to a distinct ID
    pub fn hash_to_distinct_id(hash: &[u8]) -> String {
        format!(
            "{}_{}",
            COOKIELESS_SENTINEL_VALUE,
            general_purpose::STANDARD.encode(hash)
        )
    }
}

/// Extract the root domain from a host
fn extract_root_domain(host: &str) -> Result<String, CookielessManagerError> {
    // If the host contains a protocol, extract just the host part
    let host_str = if host.contains("://") {
        // Parse the URL to extract just the host
        let url = Url::parse(host)?;
        url.host_str().unwrap_or(host).to_string()
    } else {
        host.to_string()
    };

    // Use the public-suffix list to extract the root domain (eTLD+1)
    match DEFAULT_PROVIDER.effective_tld_plus_one(&host_str) {
        Ok(domain) => Ok(domain.to_string()),
        Err(_) => {
            // If we can't parse the domain, just return the host
            Ok(host_str)
        }
    }
}

/// Convert a timestamp to YYYY-MM-DD format in the specified timezone
fn to_yyyy_mm_dd_in_timezone_safe(
    timestamp_ms: u64,
    event_time_zone: Option<&str>,
    team_time_zone: &str,
) -> Result<String, CookielessManagerError> {
    // Use the event timezone if provided, otherwise fall back to the team timezone
    let timezone_str = event_time_zone.unwrap_or(team_time_zone);

    // Parse the timezone
    let timezone = match chrono_tz::Tz::from_str(timezone_str) {
        Ok(tz) => tz,
        Err(_) => match chrono_tz::Tz::from_str(TIMEZONE_FALLBACK) {
            Ok(tz) => tz,
            Err(e) => return Err(CookielessManagerError::TimezoneError(e.to_string())),
        },
    };

    // Convert the timestamp to a DateTime
    let timestamp_seconds = (timestamp_ms / 1000) as i64;
    let datetime = match DateTime::<Utc>::from_timestamp(timestamp_seconds, 0) {
        Some(dt) => dt,
        None => {
            return Err(CookielessManagerError::InvalidTimestamp(format!(
                "Invalid timestamp: {timestamp_ms}"
            )))
        }
    };

    // Convert to the target timezone
    let datetime_in_timezone = datetime.with_timezone(&timezone);

    // Format as YYYY-MM-DD
    Ok(datetime_in_timezone.format("%Y-%m-%d").to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;

    #[test]
    fn test_to_yyyy_mm_dd_in_timezone_safe() {
        // UTC date
        let date = DateTime::parse_from_rfc3339("2024-12-31T10:00:00Z")
            .unwrap()
            .timestamp_millis() as u64;
        let result = to_yyyy_mm_dd_in_timezone_safe(date, Some("Europe/London"), "UTC").unwrap();
        assert_eq!(result, "2024-12-31");

        // Handle single digit months and days
        let date = DateTime::parse_from_rfc3339("2025-01-01T10:00:00Z")
            .unwrap()
            .timestamp_millis() as u64;
        let result = to_yyyy_mm_dd_in_timezone_safe(date, Some("Europe/London"), "UTC").unwrap();
        assert_eq!(result, "2025-01-01");

        // Handle nonsense timezone
        let date = DateTime::parse_from_rfc3339("2025-01-01T10:00:00Z")
            .unwrap()
            .timestamp_millis() as u64;
        let result = to_yyyy_mm_dd_in_timezone_safe(date, Some("Not/A/Timezone"), "UTC").unwrap();
        assert_eq!(result, "2025-01-01");

        // Handle positive timezone
        let date = DateTime::parse_from_rfc3339("2025-01-01T20:30:01Z")
            .unwrap()
            .timestamp_millis() as u64;
        let result = to_yyyy_mm_dd_in_timezone_safe(date, Some("Asia/Tehran"), "UTC").unwrap();
        assert_eq!(result, "2025-01-02");

        // Handle large positive timezone
        let date = DateTime::parse_from_rfc3339("2025-01-01T12:00:00Z")
            .unwrap()
            .timestamp_millis() as u64;
        let result =
            to_yyyy_mm_dd_in_timezone_safe(date, Some("Pacific/Tongatapu"), "UTC").unwrap();
        assert_eq!(result, "2025-01-02");

        // Handle negative timezone
        let date = DateTime::parse_from_rfc3339("2025-01-01T02:59:00Z")
            .unwrap()
            .timestamp_millis() as u64;
        let result =
            to_yyyy_mm_dd_in_timezone_safe(date, Some("America/Sao_Paulo"), "UTC").unwrap();
        assert_eq!(result, "2024-12-31");

        // Handle large negative timezone
        let date = DateTime::parse_from_rfc3339("2025-01-01T10:59:00Z")
            .unwrap()
            .timestamp_millis() as u64;
        let result = to_yyyy_mm_dd_in_timezone_safe(date, Some("Pacific/Midway"), "UTC").unwrap();
        assert_eq!(result, "2024-12-31");
    }

    #[test]
    fn test_extract_root_domain() {
        // Simple domain
        let result = extract_root_domain("example.com").unwrap();
        assert_eq!(result, "example.com");

        // Domain with subdomain
        let result = extract_root_domain("sub.example.com").unwrap();
        assert_eq!(result, "example.com");

        // Domain with protocol
        let result = extract_root_domain("http://example.com").unwrap();
        assert_eq!(result, "example.com");

        // Domain with protocol and path
        let result = extract_root_domain("http://example.com/path").unwrap();
        assert_eq!(result, "example.com");

        // Domain with protocol, subdomain, and path
        let result = extract_root_domain("https://sub.example.com/path").unwrap();
        assert_eq!(result, "example.com");

        // Domain with multiple subdomains
        let result = extract_root_domain("a.b.c.example.com").unwrap();
        assert_eq!(result, "example.com");

        // Domain with a known public suffix
        let result = extract_root_domain("example.co.uk").unwrap();
        assert_eq!(result, "example.co.uk");

        // Subdomain with a known public suffix
        let result = extract_root_domain("sub.example.co.uk").unwrap();
        assert_eq!(result, "example.co.uk");
    }

    #[test]
    fn test_hash_to_distinct_id() {
        let hash = vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16];
        let distinct_id = CookielessManager::hash_to_distinct_id(&hash);
        assert_eq!(distinct_id, "$posthog_cookieless_AQIDBAUGBwgJCgsMDQ4PEA==");
    }

    #[tokio::test]
    async fn test_compute_cookieless_distinct_id() {
        // Create a mock Redis client
        let mut mock_redis = MockRedisClient::new();
        let salt_base64 = "AAAAAAAAAAAAAAAAAAAAAA=="; // 16 bytes of zeros
        let today = Utc::now().format("%Y-%m-%d").to_string();
        let redis_key = format!("cookieless_salt:{}", today);
        mock_redis = mock_redis.get_ret(&redis_key, Ok(salt_base64.to_string()));
        let redis_client = Arc::new(mock_redis);

        // Create a CookielessManager
        let config = CookielessConfig::default();
        let manager = CookielessManager::new(config, redis_client);

        // Create an event
        let event_data = EventData {
            ip: "127.0.0.1",
            timestamp_ms: Utc::now().timestamp_millis() as u64,
            host: "example.com",
            user_agent: "Mozilla/5.0",
            event_time_zone: None,
            hash_extra: None,
            team_id: 1,
            team_time_zone: Some("UTC"),
        };

        // Process the event
        let result = manager.compute_cookieless_distinct_id(event_data).await.unwrap();

        // Check that we got a distinct ID
        assert!(result.starts_with(COOKIELESS_SENTINEL_VALUE));
    }

    #[tokio::test]
    async fn test_compute_cookieless_distinct_id_with_hash_extra() {
        // Create a mock Redis client
        let mut mock_redis = MockRedisClient::new();
        let salt_base64 = "AAAAAAAAAAAAAAAAAAAAAA=="; // 16 bytes of zeros
        let today = Utc::now().format("%Y-%m-%d").to_string();
        let redis_key = format!("cookieless_salt:{}", today);
        mock_redis = mock_redis.get_ret(&redis_key, Ok(salt_base64.to_string()));
        let redis_client = Arc::new(mock_redis);

        // Create a CookielessManager
        let config = CookielessConfig::default();
        let manager = CookielessManager::new(config, redis_client.clone());

        // Create an event with hash_extra
        let event_data1 = EventData {
            ip: "127.0.0.1",
            timestamp_ms: Utc::now().timestamp_millis() as u64,
            host: "example.com",
            user_agent: "Mozilla/5.0",
            event_time_zone: None,
            hash_extra: Some("extra1"),
            team_id: 1,
            team_time_zone: Some("UTC"),
        };

        // Create another event with different hash_extra
        let event_data2 = EventData {
            ip: "127.0.0.1",
            timestamp_ms: Utc::now().timestamp_millis() as u64,
            host: "example.com",
            user_agent: "Mozilla/5.0",
            event_time_zone: None,
            hash_extra: Some("extra2"),
            team_id: 1,
            team_time_zone: Some("UTC"),
        };

        // Process the events
        let result1 = manager.compute_cookieless_distinct_id(event_data1).await.unwrap();
        let result2 = manager.compute_cookieless_distinct_id(event_data2).await.unwrap();

        // Check that we got different distinct IDs
        assert_ne!(result1, result2);
    }

    #[tokio::test]
    async fn test_compute_cookieless_distinct_id_disabled() {
        // Create a mock Redis client
        let redis_client = Arc::new(MockRedisClient::new());

        // Create a CookielessManager with disabled config
        let config = CookielessConfig {
            disabled: true,
            ..CookielessConfig::default()
        };
        let manager = CookielessManager::new(config, redis_client);

        // Create an event
        let event_data = EventData {
            ip: "127.0.0.1",
            timestamp_ms: Utc::now().timestamp_millis() as u64,
            host: "example.com",
            user_agent: "Mozilla/5.0",
            event_time_zone: None,
            hash_extra: None,
            team_id: 1,
            team_time_zone: Some("UTC"),
        };

        // Process the event
        let result = manager.compute_cookieless_distinct_id(event_data).await;

        // Check that we got a Disabled error
        assert!(matches!(result, Err(CookielessManagerError::Disabled)));
    }

    #[tokio::test]
    async fn test_compute_cookieless_distinct_id_missing_fields() {
        // Create a mock Redis client
        let redis_client = Arc::new(MockRedisClient::new());

        // Create a CookielessManager
        let config = CookielessConfig::default();
        let manager = CookielessManager::new(config, redis_client);

        // Test missing IP
        let event_data = EventData {
            ip: "",
            timestamp_ms: Utc::now().timestamp_millis() as u64,
            host: "example.com",
            user_agent: "Mozilla/5.0",
            event_time_zone: None,
            hash_extra: None,
            team_id: 1,
            team_time_zone: Some("UTC"),
        };
        let result = manager.compute_cookieless_distinct_id(event_data).await;
        assert!(matches!(
            result,
            Err(CookielessManagerError::MissingProperty(s)) if s == "ip"
        ));

        // Test missing host
        let event_data = EventData {
            ip: "127.0.0.1",
            timestamp_ms: Utc::now().timestamp_millis() as u64,
            host: "",
            user_agent: "Mozilla/5.0",
            event_time_zone: None,
            hash_extra: None,
            team_id: 1,
            team_time_zone: Some("UTC"),
        };
        let result = manager.compute_cookieless_distinct_id(event_data).await;
        assert!(matches!(
            result,
            Err(CookielessManagerError::MissingProperty(s)) if s == "host"
        ));

        // Test missing user agent
        let event_data = EventData {
            ip: "127.0.0.1",
            timestamp_ms: Utc::now().timestamp_millis() as u64,
            host: "example.com",
            user_agent: "",
            event_time_zone: None,
            hash_extra: None,
            team_id: 1,
            team_time_zone: Some("UTC"),
        };
        let result = manager.compute_cookieless_distinct_id(event_data).await;
        assert!(matches!(
            result,
            Err(CookielessManagerError::MissingProperty(s)) if s == "user_agent"
        ));
    }
}
