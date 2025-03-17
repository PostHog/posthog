use std::str::FromStr;
use std::sync::Arc;

use base64::{engine::general_purpose, Engine};
use chrono::{DateTime, Utc};
use public_suffix::{EffectiveTLDProvider, DEFAULT_PROVIDER};
use thiserror::Error;
use url::Url;

use crate::constants::{
    COOKIELESS_DISTINCT_ID_PREFIX, IDENTIFIES_TTL_SECONDS, SALT_TTL_SECONDS, SESSION_INACTIVITY_MS,
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

    #[error("Invalid identify count: {0}")]
    InvalidIdentifyCount(String),

    #[error("Redis error: {0}")]
    RedisError(String),
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
    /// Redis client for direct access
    redis_client: Arc<dyn RedisClient + Send + Sync>,
}

impl CookielessManager {
    /// Create a new CookielessManager
    pub fn new(config: CookielessConfig, redis_client: Arc<dyn RedisClient + Send + Sync>) -> Self {
        let salt_cache = SaltCache::new(redis_client.clone(), Some(config.salt_ttl_seconds));

        Self {
            config,
            salt_cache,
            redis_client,
        }
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
            return Err(CookielessManagerError::MissingProperty(
                "user_agent".to_string(),
            ));
        }

        // Get the team timezone or use UTC as fallback
        let team_time_zone = event_data.team_time_zone.unwrap_or(TIMEZONE_FALLBACK);

        // First, compute the hash with n=0 to get the base hash
        let hash_params = HashParams {
            timestamp_ms: event_data.timestamp_ms,
            event_time_zone: event_data.event_time_zone,
            team_time_zone,
            team_id: event_data.team_id,
            ip: event_data.ip,
            host: event_data.host,
            user_agent: event_data.user_agent,
            n: 0,
            hash_extra: event_data.hash_extra.unwrap_or(""),
        };

        // Compute the base hash
        let base_hash = self.do_hash_for_day(hash_params.clone()).await?;

        // If we're in stateless mode, use the base hash directly
        if self.config.force_stateless_mode {
            return Ok(Self::hash_to_distinct_id(&base_hash));
        }

        // Get the number of identify events for this hash
        let n = self
            .get_identify_count(&base_hash, event_data.team_id)
            .await?;

        // If n is 0, we can use the base hash
        if n == 0 {
            return Ok(Self::hash_to_distinct_id(&base_hash));
        }

        // Otherwise, recompute the hash with the correct n value
        let hash_params_with_n = HashParams { n, ..hash_params };

        // Compute the final hash
        let final_hash = self.do_hash_for_day(hash_params_with_n).await?;

        // Convert the hash to a distinct ID
        Ok(Self::hash_to_distinct_id(&final_hash))
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
            COOKIELESS_DISTINCT_ID_PREFIX,
            general_purpose::STANDARD.encode(hash).trim_end_matches('=')
        )
    }

    /// Get the number of identify events for a specific hash
    /// This is used to ensure that a user that logs in and out doesn't collide with themselves
    pub async fn get_identify_count(
        &self,
        hash: &[u8],
        team_id: u64,
    ) -> Result<u64, CookielessManagerError> {
        // If we're in stateless mode, always return 0
        if self.config.force_stateless_mode {
            return Ok(0);
        }

        // Get the Redis key for the identify count
        let redis_key = get_redis_identifies_key(hash, team_id);

        // Try to get the count from Redis
        match self.redis_client.get(redis_key).await {
            Ok(count_str) => {
                // Parse the count string to a u64
                count_str
                    .parse::<u64>()
                    .map_err(|e| CookielessManagerError::InvalidIdentifyCount(e.to_string()))
            }
            Err(common_redis::CustomRedisError::NotFound) => {
                // If the key doesn't exist, the count is 0
                Ok(0)
            }
            Err(e) => {
                // If there's a Redis error, propagate it
                Err(CookielessManagerError::RedisError(e.to_string()))
            }
        }
    }
}

/// Extract the root domain from a host string
///
/// This function handles various formats including:
/// - URLs with protocols (e.g., https://example.com)
/// - Hosts with ports (e.g., example.com:8000)
/// - Subdomains (e.g., sub.example.com)
/// - IPv4 and IPv6 addresses
///
/// It returns the root domain (eTLD+1) for valid domains, or the original host for
/// special cases like IP addresses, localhost, etc.
/// The port is preserved if present in the original host.
pub fn extract_root_domain(host: &str) -> Result<String, CookielessManagerError> {
    use std::net::IpAddr;

    // If the host is empty, return it as is
    if host.is_empty() {
        return Ok(host.to_string());
    }

    // Check if it's an IPv6 address
    if let Ok(ip_addr) = host.parse::<IpAddr>() {
        if let IpAddr::V6(ipv6) = ip_addr {
            // Return the normalized form of the IPv6 address in brackets
            return Ok(format!("[{}]", ipv6));
        }
    }

    // Split host and port for special handling of IP addresses
    let (hostname, port) = if let Some((h, p)) = host.split_once(':') {
        (h, Some(p))
    } else {
        (host, None)
    };

    // Check if the hostname is an IP address
    if hostname.parse::<IpAddr>().is_ok() {
        return match port {
            Some(p) => Ok(format!("{}:{}", hostname, p)),
            None => Ok(hostname.to_string()),
        };
    }

    // Add a fake protocol if none exists
    let input = if !host.contains("://") {
        format!("http://{}", host)
    } else {
        host.to_string()
    };

    // Parse the URL to extract hostname and port
    let url = match Url::parse(&input) {
        Ok(url) => url,
        Err(_) => return Ok(host.to_string()),
    };

    let hostname = url.host_str().unwrap_or(host).to_string();
    let port = url.port().map(|p| p.to_string());

    // Use the public-suffix list to extract the root domain (eTLD+1)
    let domain = match DEFAULT_PROVIDER.effective_tld_plus_one(&hostname) {
        Ok(domain) => domain.to_string(),
        Err(_) => hostname,
    };

    // Add the port back if it exists
    match port {
        Some(p) => Ok(format!("{}:{}", domain, p)),
        None => Ok(domain),
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

/// Get the Redis key for identify counts
#[must_use]
pub fn get_redis_identifies_key(hash: &[u8], team_id: u64) -> String {
    // cklsi = cookieless identifies
    format!(
        "cklsi:{}:{}",
        team_id,
        general_purpose::STANDARD.encode(hash).trim_end_matches('=')
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use common_redis::MockRedisClient;
    use serde_json::Value;
    use std::fs;

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
        // Read the test cases from the JSON file
        let test_cases_json = fs::read_to_string("src/test_cases.json")
            .expect("Failed to read test_cases.json file. Make sure you're running the test from the correct directory.");
        let test_cases: Value = serde_json::from_str(&test_cases_json)
            .expect("Failed to parse test_cases.json as valid JSON");

        // Test extract_root_domain function
        if let Some(extract_root_domain_tests) = test_cases.get("extract_root_domain_tests") {
            for test_case in extract_root_domain_tests.as_array().unwrap() {
                let host = test_case["host"].as_str().unwrap();
                let expected_root_domain = test_case["expected_root_domain"].as_str().unwrap();

                let result = extract_root_domain(host).unwrap();
                assert_eq!(result, expected_root_domain, "Failed for host: {}", host);
            }
        } else {
            panic!("extract_root_domain_tests not found in test_cases.json");
        }

        // Additional test cases for edge cases not covered in the shared test cases
        let result = extract_root_domain("not a url").unwrap();
        assert_eq!(result, "not a url");
    }

    #[test]
    fn test_hash_to_distinct_id() {
        let hash = vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16];
        let distinct_id = CookielessManager::hash_to_distinct_id(&hash);
        assert_eq!(distinct_id, "cookieless_AQIDBAUGBwgJCgsMDQ4PEA");
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
        let result = manager
            .compute_cookieless_distinct_id(event_data)
            .await
            .unwrap();

        // Check that we got a distinct ID
        assert!(result.starts_with(COOKIELESS_DISTINCT_ID_PREFIX));
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
        let result1 = manager
            .compute_cookieless_distinct_id(event_data1)
            .await
            .unwrap();
        let result2 = manager
            .compute_cookieless_distinct_id(event_data2)
            .await
            .unwrap();

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

    #[tokio::test]
    async fn test_get_identify_count() {
        // Create a mock Redis client
        let mut mock_redis = MockRedisClient::new();
        let hash = vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16];
        let team_id = 1;
        let redis_key = get_redis_identifies_key(&hash, team_id);

        // Set up the mock to return a count of 3
        mock_redis = mock_redis.get_ret(&redis_key, Ok("3".to_string()));
        let redis_client = Arc::new(mock_redis);

        // Create a CookielessManager
        let config = CookielessConfig::default();
        let manager = CookielessManager::new(config, redis_client);

        // Get the identify count
        let count = manager.get_identify_count(&hash, team_id).await.unwrap();
        assert_eq!(count, 3);
    }

    #[tokio::test]
    async fn test_get_identify_count_not_found() {
        // Create a mock Redis client
        let mut mock_redis = MockRedisClient::new();
        let hash = vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16];
        let team_id = 1;
        let redis_key = get_redis_identifies_key(&hash, team_id);

        // Set up the mock to return NotFound
        mock_redis = mock_redis.get_ret(&redis_key, Err(common_redis::CustomRedisError::NotFound));
        let redis_client = Arc::new(mock_redis);

        // Create a CookielessManager
        let config = CookielessConfig::default();
        let manager = CookielessManager::new(config, redis_client);

        // Get the identify count
        let count = manager.get_identify_count(&hash, team_id).await.unwrap();
        assert_eq!(count, 0);
    }

    #[tokio::test]
    async fn test_get_identify_count_stateless_mode() {
        // Create a mock Redis client
        let redis_client = Arc::new(MockRedisClient::new());

        // Create a CookielessManager with force_stateless_mode=true
        let config = CookielessConfig {
            force_stateless_mode: true,
            ..CookielessConfig::default()
        };
        let manager = CookielessManager::new(config, redis_client);

        // Get the identify count
        let hash = vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16];
        let count = manager.get_identify_count(&hash, 1).await.unwrap();
        assert_eq!(count, 0);
    }

    #[tokio::test]
    async fn test_compute_cookieless_distinct_id_with_identifies() {
        // Create a mock Redis client
        let mut mock_redis = MockRedisClient::new();
        let salt_base64 = "AAAAAAAAAAAAAAAAAAAAAA=="; // 16 bytes of zeros
        let today = Utc::now().format("%Y-%m-%d").to_string();
        let redis_key = format!("cookieless_salt:{}", today);
        mock_redis = mock_redis.get_ret(&redis_key, Ok(salt_base64.to_string()));

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

        // Compute the base hash
        let config = CookielessConfig::default();
        let temp_manager = CookielessManager::new(config.clone(), Arc::new(mock_redis.clone()));
        let hash_params = HashParams {
            timestamp_ms: event_data.timestamp_ms,
            event_time_zone: event_data.event_time_zone,
            team_time_zone: event_data.team_time_zone.unwrap_or(TIMEZONE_FALLBACK),
            team_id: event_data.team_id,
            ip: event_data.ip,
            host: event_data.host,
            user_agent: event_data.user_agent,
            n: 0,
            hash_extra: event_data.hash_extra.unwrap_or(""),
        };
        let base_hash = temp_manager
            .do_hash_for_day(hash_params.clone())
            .await
            .unwrap();

        // Get the Redis key for the identify count
        let identifies_key = get_redis_identifies_key(&base_hash, event_data.team_id);

        // Set up the mock to return a count of 2
        mock_redis = mock_redis.get_ret(&identifies_key, Ok("2".to_string()));
        let redis_client = Arc::new(mock_redis);

        // Create a CookielessManager
        let manager = CookielessManager::new(config, redis_client);

        // Process the event
        let result = manager
            .compute_cookieless_distinct_id(event_data)
            .await
            .unwrap();

        // Check that we got a distinct ID
        assert!(result.starts_with(COOKIELESS_DISTINCT_ID_PREFIX));

        // Compute what the result should be with n=2
        let hash_params_with_n = HashParams {
            n: 2,
            ..hash_params
        };
        let expected_hash = temp_manager
            .do_hash_for_day(hash_params_with_n)
            .await
            .unwrap();
        let expected_distinct_id = CookielessManager::hash_to_distinct_id(&expected_hash);

        // Check that the result matches the expected distinct ID
        assert_eq!(result, expected_distinct_id);
    }

    #[tokio::test]
    async fn test_compute_cookieless_distinct_id_stateless_mode() {
        // Create a mock Redis client
        let mut mock_redis = MockRedisClient::new();
        let salt_base64 = "AAAAAAAAAAAAAAAAAAAAAA=="; // 16 bytes of zeros
        let today = Utc::now().format("%Y-%m-%d").to_string();
        let redis_key = format!("cookieless_salt:{}", today);
        mock_redis = mock_redis.get_ret(&redis_key, Ok(salt_base64.to_string()));
        let redis_client = Arc::new(mock_redis);

        // Create a CookielessManager with force_stateless_mode=true
        let config = CookielessConfig {
            force_stateless_mode: true,
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
        let result = manager
            .compute_cookieless_distinct_id(event_data)
            .await
            .unwrap();

        // Check that we got a distinct ID
        assert!(result.starts_with(COOKIELESS_DISTINCT_ID_PREFIX));
    }

    #[test]
    fn test_key_generation_functions() {
        // Read the test cases from the JSON file
        let test_cases_json = fs::read_to_string("src/test_cases.json")
            .expect("Failed to read test_cases.json file. Make sure you're running the test from the correct directory.");
        let test_cases: Value = serde_json::from_str(&test_cases_json)
            .expect("Failed to parse test_cases.json as valid JSON");

        // Test hash_to_distinct_id function
        if let Some(distinct_id_tests) = test_cases.get("hash_to_distinct_id_tests") {
            for test_case in distinct_id_tests.as_array().unwrap() {
                let hash_base64 = test_case["hash"].as_str().unwrap();
                let hash = general_purpose::STANDARD.decode(hash_base64).unwrap();
                let expected_distinct_id = test_case["expected_distinct_id"].as_str().unwrap();

                let distinct_id = CookielessManager::hash_to_distinct_id(&hash);
                assert_eq!(distinct_id, expected_distinct_id);
            }
        }

        // Test get_redis_identifies_key function
        if let Some(identifies_key_tests) = test_cases.get("redis_identifies_key_tests") {
            for test_case in identifies_key_tests.as_array().unwrap() {
                let hash_base64 = test_case["hash"].as_str().unwrap();
                let hash = general_purpose::STANDARD.decode(hash_base64).unwrap();
                let team_id = test_case["team_id"].as_u64().unwrap();
                let expected_identifies_key =
                    test_case["expected_identifies_key"].as_str().unwrap();

                let identifies_key = get_redis_identifies_key(&hash, team_id);
                assert_eq!(identifies_key, expected_identifies_key);
            }
        }

        // Test hash_to_distinct_id function
        if let Some(distinct_id_tests) = test_cases.get("hash_to_distinct_id_tests") {
            for test_case in distinct_id_tests
                .as_array()
                .expect("hash_to_distinct_id_tests should be an array")
            {
                let hash_base64 = test_case["hash"].as_str().expect("hash should be a string");
                let hash = general_purpose::STANDARD
                    .decode(hash_base64)
                    .expect("hash should be valid base64");
                let expected_distinct_id = test_case["expected_distinct_id"]
                    .as_str()
                    .expect("expected_distinct_id should be a string");

                let distinct_id = CookielessManager::hash_to_distinct_id(&hash);
                assert_eq!(distinct_id, expected_distinct_id);
            }
        } else {
            panic!("hash_to_distinct_id_tests not found in test_cases.json");
        }

        // Test get_redis_identifies_key function
        if let Some(identifies_key_tests) = test_cases.get("redis_identifies_key_tests") {
            for test_case in identifies_key_tests
                .as_array()
                .expect("redis_identifies_key_tests should be an array")
            {
                let hash_base64 = test_case["hash"].as_str().expect("hash should be a string");
                let hash = general_purpose::STANDARD
                    .decode(hash_base64)
                    .expect("hash should be valid base64");
                let team_id = test_case["team_id"]
                    .as_u64()
                    .expect("team_id should be a non-negative integer");
                let expected_identifies_key = test_case["expected_identifies_key"]
                    .as_str()
                    .expect("expected_identifies_key should be a string");

                let identifies_key = get_redis_identifies_key(&hash, team_id);
                assert_eq!(identifies_key, expected_identifies_key);
            }
        } else {
            panic!("redis_identifies_key_tests not found in test_cases.json");
        }
    }
}
