use axum::{extract::State, http::HeaderMap};
use bytes::Bytes;
use serde::Serialize;
use serde_json::Value;
use std::{collections::HashMap, fmt, net::IpAddr, sync::Arc};
use uuid::Uuid;

use crate::{
    api::types::FlagsQueryParams, cohorts::cohort_cache_manager::CohortCacheManager,
    flags::flag_models::FeatureFlagList, router,
};

pub struct RequestContext {
    /// Shared state holding services (DB, Redis, GeoIP, etc.)
    pub state: State<router::State>,

    /// Client IP
    pub ip: IpAddr,

    /// HTTP headers
    pub headers: HeaderMap,

    /// Query params (contains compression, library version, etc.)
    pub meta: FlagsQueryParams,

    /// Raw request body
    pub body: Bytes,

    /// Request ID
    pub request_id: Uuid,
}

/// Represents the various property overrides that can be passed around
/// (person, group, groups, and optional hash key).
#[derive(Debug, Clone)]
pub struct RequestPropertyOverrides {
    pub person_properties: Option<HashMap<String, Value>>,
    pub group_properties: Option<HashMap<String, HashMap<String, Value>>>,
    pub groups: Option<HashMap<String, Value>>,
    pub hash_key: Option<String>,
}

/// Represents all context required for evaluating a set of feature flags.
pub struct FeatureFlagEvaluationContext {
    pub team_id: i32,
    pub distinct_id: String,
    pub device_id: Option<String>,
    pub feature_flags: FeatureFlagList,
    pub persons_reader: Arc<dyn common_database::Client + Send + Sync>,
    pub persons_writer: Arc<dyn common_database::Client + Send + Sync>,
    pub non_persons_reader: Arc<dyn common_database::Client + Send + Sync>,
    pub non_persons_writer: Arc<dyn common_database::Client + Send + Sync>,
    pub cohort_cache: Arc<CohortCacheManager>,
    pub person_property_overrides: Option<HashMap<String, Value>>,
    pub group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    pub groups: Option<HashMap<String, Value>>,
    pub hash_key_override: Option<String>,
    /// Contains explicitly requested flag keys and their dependencies. If empty, all flags will be evaluated.
    pub flag_keys: Option<Vec<String>>,
    /// When true, skip hash key override lookups for flags that don't need them
    /// (e.g., 100% rollout with no multivariate variants).
    pub optimize_experience_continuity_lookups: bool,
}

/// SDK type classification based on user-agent parsing
/// Used for billing breakdown and usage analytics
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum Library {
    /// posthog-js (web browsers)
    PosthogJs,
    /// posthog-node SDK (server-side Node.js)
    PosthogNode,
    /// posthog-python SDK
    PosthogPython,
    /// posthog-php SDK
    PosthogPhp,
    /// posthog-ruby SDK
    PosthogRuby,
    /// posthog-go SDK
    PosthogGo,
    /// posthog-java SDK
    PosthogJava,
    /// posthog-android SDK
    PosthogAndroid,
    /// posthog-ios SDK
    PosthogIos,
    /// posthog-react-native SDK
    PosthogReactNative,
    /// posthog-flutter SDK
    PosthogFlutter,
    /// Unknown or unrecognized SDK
    Other,
}

impl fmt::Display for Library {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Library::PosthogJs => write!(f, "posthog-js"),
            Library::PosthogNode => write!(f, "posthog-node"),
            Library::PosthogPython => write!(f, "posthog-python"),
            Library::PosthogPhp => write!(f, "posthog-php"),
            Library::PosthogRuby => write!(f, "posthog-ruby"),
            Library::PosthogGo => write!(f, "posthog-go"),
            Library::PosthogJava => write!(f, "posthog-java"),
            Library::PosthogAndroid => write!(f, "posthog-android"),
            Library::PosthogIos => write!(f, "posthog-ios"),
            Library::PosthogReactNative => write!(f, "posthog-react-native"),
            Library::PosthogFlutter => write!(f, "posthog-flutter"),
            Library::Other => write!(f, "other"),
        }
    }
}

impl Library {
    /// Detect SDK type from HTTP headers, primarily the User-Agent
    ///
    /// This function analyzes the User-Agent header to determine which PostHog SDK
    /// or client type is making the request. It's used for billing breakdown and
    /// usage analytics.
    ///
    /// # Examples
    ///
    /// ```
    /// use axum::http::HeaderMap;
    /// use feature_flags::handler::types::Library;
    ///
    /// let mut headers = HeaderMap::new();
    /// headers.insert("user-agent", "posthog-node/3.1.0".parse().unwrap());
    /// assert_eq!(Library::from_headers(&headers), Library::PosthogNode);
    /// ```
    pub fn from_headers(headers: &HeaderMap) -> Self {
        // Extract user-agent header
        let user_agent = headers
            .get("user-agent")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("");

        // Server SDKs - check these first as they have most specific patterns
        if user_agent.starts_with("posthog-node/") {
            return Library::PosthogNode;
        }
        if user_agent.starts_with("posthog-python/") {
            return Library::PosthogPython;
        }
        if user_agent.starts_with("posthog-php/") {
            return Library::PosthogPhp;
        }
        if user_agent.starts_with("posthog-ruby/") {
            return Library::PosthogRuby;
        }
        if user_agent.starts_with("posthog-go/") {
            return Library::PosthogGo;
        }
        if user_agent.starts_with("posthog-java/") {
            return Library::PosthogJava;
        }

        // Mobile SDKs
        if user_agent.starts_with("posthog-android/") {
            return Library::PosthogAndroid;
        }
        if user_agent.starts_with("posthog-ios/") {
            return Library::PosthogIos;
        }
        if user_agent.starts_with("posthog-react-native/") {
            return Library::PosthogReactNative;
        }
        if user_agent.starts_with("posthog-flutter/") {
            return Library::PosthogFlutter;
        }

        // If it's an unrecognized posthog-* SDK, return Other
        // This prevents custom SDKs like "posthog-custom/1.0 Chrome/..." from being
        // misclassified as browsers
        if user_agent.starts_with("posthog-") {
            return Library::Other;
        }

        // Web browsers - check for browser signatures (posthog-js)
        // Only apply if we haven't matched a PostHog SDK above
        if user_agent.contains("Mozilla/")
            || user_agent.contains("Chrome/")
            || user_agent.contains("Safari/")
            || user_agent.contains("Firefox/")
            || user_agent.contains("Edge/")
        {
            return Library::PosthogJs;
        }

        // Additional browser detection from headers
        // Only use sec-fetch-* headers as they are browser-only and cannot be spoofed
        // (origin/referer can be set by server SDKs, proxies, etc.)
        if headers.get("sec-fetch-mode").is_some() || headers.get("sec-fetch-site").is_some() {
            return Library::PosthogJs;
        }

        // Default to Other for unrecognized SDKs
        Library::Other
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderMap;

    fn make_headers_with_user_agent(ua: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert("user-agent", ua.parse().unwrap());
        headers
    }

    #[test]
    fn test_sdk_type_server_node() {
        let headers = make_headers_with_user_agent("posthog-node/3.1.0");
        assert_eq!(Library::from_headers(&headers), Library::PosthogNode);
    }

    #[test]
    fn test_sdk_type_server_python() {
        let headers = make_headers_with_user_agent("posthog-python/2.5.0");
        assert_eq!(Library::from_headers(&headers), Library::PosthogPython);
    }

    #[test]
    fn test_sdk_type_server_php() {
        let headers = make_headers_with_user_agent("posthog-php/3.0.0");
        assert_eq!(Library::from_headers(&headers), Library::PosthogPhp);
    }

    #[test]
    fn test_sdk_type_server_ruby() {
        let headers = make_headers_with_user_agent("posthog-ruby/2.3.0");
        assert_eq!(Library::from_headers(&headers), Library::PosthogRuby);
    }

    #[test]
    fn test_sdk_type_server_go() {
        let headers = make_headers_with_user_agent("posthog-go/1.0.0");
        assert_eq!(Library::from_headers(&headers), Library::PosthogGo);
    }

    #[test]
    fn test_sdk_type_server_java() {
        let headers = make_headers_with_user_agent("posthog-java/1.2.0");
        assert_eq!(Library::from_headers(&headers), Library::PosthogJava);
    }

    #[test]
    fn test_sdk_type_mobile_android() {
        let headers = make_headers_with_user_agent("posthog-android/3.0.0");
        assert_eq!(Library::from_headers(&headers), Library::PosthogAndroid);
    }

    #[test]
    fn test_sdk_type_mobile_ios() {
        let headers = make_headers_with_user_agent("posthog-ios/3.1.0");
        assert_eq!(Library::from_headers(&headers), Library::PosthogIos);
    }

    #[test]
    fn test_sdk_type_mobile_react_native() {
        let headers = make_headers_with_user_agent("posthog-react-native/2.0.0");
        assert_eq!(Library::from_headers(&headers), Library::PosthogReactNative);
    }

    #[test]
    fn test_sdk_type_mobile_flutter() {
        let headers = make_headers_with_user_agent("posthog-flutter/2.0.0");
        assert_eq!(Library::from_headers(&headers), Library::PosthogFlutter);
    }

    #[test]
    fn test_sdk_type_web_chrome() {
        let headers = make_headers_with_user_agent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        );
        assert_eq!(Library::from_headers(&headers), Library::PosthogJs);
    }

    #[test]
    fn test_sdk_type_web_firefox() {
        let headers = make_headers_with_user_agent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
        );
        assert_eq!(Library::from_headers(&headers), Library::PosthogJs);
    }

    #[test]
    fn test_sdk_type_web_safari() {
        let headers = make_headers_with_user_agent(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15"
        );
        assert_eq!(Library::from_headers(&headers), Library::PosthogJs);
    }

    #[test]
    fn test_sdk_type_web_edge() {
        let headers = make_headers_with_user_agent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.59"
        );
        assert_eq!(Library::from_headers(&headers), Library::PosthogJs);
    }

    #[test]
    fn test_sdk_type_other_with_origin_header_only() {
        // origin/referer headers alone don't indicate browser (can be set by servers)
        let mut headers = HeaderMap::new();
        headers.insert("user-agent", "some-custom-client".parse().unwrap());
        headers.insert("origin", "https://example.com".parse().unwrap());
        assert_eq!(Library::from_headers(&headers), Library::Other);
    }

    #[test]
    fn test_sdk_type_other_with_referer_header_only() {
        // origin/referer headers alone don't indicate browser (can be set by servers)
        let mut headers = HeaderMap::new();
        headers.insert("user-agent", "some-custom-client".parse().unwrap());
        headers.insert("referer", "https://example.com/page".parse().unwrap());
        assert_eq!(Library::from_headers(&headers), Library::Other);
    }

    #[test]
    fn test_sdk_type_web_with_sec_fetch_headers() {
        let mut headers = HeaderMap::new();
        headers.insert("user-agent", "some-custom-client".parse().unwrap());
        headers.insert("sec-fetch-mode", "navigate".parse().unwrap());
        assert_eq!(Library::from_headers(&headers), Library::PosthogJs);
    }

    #[test]
    fn test_sdk_type_other_missing_user_agent() {
        let headers = HeaderMap::new();
        assert_eq!(Library::from_headers(&headers), Library::Other);
    }

    #[test]
    fn test_sdk_type_other_empty_user_agent() {
        let headers = make_headers_with_user_agent("");
        assert_eq!(Library::from_headers(&headers), Library::Other);
    }

    #[test]
    fn test_sdk_type_other_unrecognized() {
        let headers = make_headers_with_user_agent("some-random-client/1.0");
        assert_eq!(Library::from_headers(&headers), Library::Other);
    }

    #[test]
    fn test_sdk_type_other_unrecognized_posthog_sdk_with_browser_strings() {
        // Test that unknown posthog-* SDKs aren't misclassified as browsers
        // even if they contain browser user-agent strings
        let headers = make_headers_with_user_agent("posthog-custom/1.0 Chrome/91.0 Safari/537.36");
        assert_eq!(Library::from_headers(&headers), Library::Other);
    }

    #[test]
    fn test_sdk_type_display() {
        assert_eq!(Library::PosthogJs.to_string(), "posthog-js");
        assert_eq!(Library::PosthogNode.to_string(), "posthog-node");
        assert_eq!(Library::PosthogPython.to_string(), "posthog-python");
        assert_eq!(Library::PosthogAndroid.to_string(), "posthog-android");
        assert_eq!(Library::Other.to_string(), "other");
    }

    #[test]
    fn test_sdk_type_performance() {
        // Test that parsing 1000 different user-agents is fast
        use std::time::Instant;

        let test_cases = vec![
            "posthog-node/3.1.0",
            "posthog-python/2.5.0",
            "posthog-php/3.0.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "posthog-android/3.0.0",
            "some-random-client/1.0",
        ];

        let start = Instant::now();
        for _ in 0..1000 {
            for ua in &test_cases {
                let headers = make_headers_with_user_agent(ua);
                let _ = Library::from_headers(&headers);
            }
        }
        let duration = start.elapsed();

        // Should process 6000 user-agents in less than 100ms
        assert!(
            duration.as_millis() < 100,
            "SDK type detection took too long: {duration:?}"
        );
    }

    #[test]
    fn test_sdk_type_serialization() {
        // Test that the enum serializes correctly to JSON
        assert_eq!(
            serde_json::to_string(&Library::PosthogNode).unwrap(),
            "\"posthog-node\""
        );
        assert_eq!(
            serde_json::to_string(&Library::PosthogJs).unwrap(),
            "\"posthog-js\""
        );
        assert_eq!(
            serde_json::to_string(&Library::PosthogAndroid).unwrap(),
            "\"posthog-android\""
        );
    }
}
