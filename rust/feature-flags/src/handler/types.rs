use axum::{extract::State, http::HeaderMap};
use bytes::Bytes;
use serde::Serialize;
use serde_json::Value;
use std::{collections::HashMap, fmt, net::IpAddr, sync::Arc};
use uuid::Uuid;

use crate::{
    api::types::FlagsQueryParams, cohorts::cohort_cache_manager::CohortCacheManager,
    flags::flag_models::FeatureFlagList, router, utils::user_agent::UserAgentInfo,
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

/// SDK type classification based on user-agent parsing.
/// Used for billing breakdown and usage analytics.
///
/// This enum leverages [`UserAgentInfo`] for SDK detection to avoid code
/// duplication, adding sec-fetch header detection for browser identification.
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
    /// posthog-dotnet SDK
    PosthogDotnet,
    /// posthog-elixir SDK
    PosthogElixir,
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

impl Library {
    /// Returns the canonical string representation of this library.
    ///
    /// This is the single source of truth for SDK name strings, used by both
    /// `Display` and `from_sdk_name()` to ensure consistency.
    pub const fn as_str(&self) -> &'static str {
        match self {
            Library::PosthogJs => "posthog-js",
            Library::PosthogNode => "posthog-node",
            Library::PosthogPython => "posthog-python",
            Library::PosthogPhp => "posthog-php",
            Library::PosthogRuby => "posthog-ruby",
            Library::PosthogGo => "posthog-go",
            Library::PosthogJava => "posthog-java",
            Library::PosthogDotnet => "posthog-dotnet",
            Library::PosthogElixir => "posthog-elixir",
            Library::PosthogAndroid => "posthog-android",
            Library::PosthogIos => "posthog-ios",
            Library::PosthogReactNative => "posthog-react-native",
            Library::PosthogFlutter => "posthog-flutter",
            Library::Other => "other",
        }
    }

    /// All known library variants (excluding Other).
    ///
    /// Used by tests to verify that all SDK names from UserAgentInfo are recognized.
    pub const ALL_KNOWN: &'static [Library] = &[
        Library::PosthogJs,
        Library::PosthogNode,
        Library::PosthogPython,
        Library::PosthogPhp,
        Library::PosthogRuby,
        Library::PosthogGo,
        Library::PosthogJava,
        Library::PosthogDotnet,
        Library::PosthogElixir,
        Library::PosthogAndroid,
        Library::PosthogIos,
        Library::PosthogReactNative,
        Library::PosthogFlutter,
    ];
}

impl fmt::Display for Library {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

impl Library {
    /// Detect SDK type from HTTP headers, primarily the User-Agent.
    ///
    /// This function uses [`UserAgentInfo`] for SDK detection, with additional
    /// browser detection via sec-fetch headers (which cannot be spoofed by
    /// server-side code).
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
        let user_agent = headers.get("user-agent").and_then(|v| v.to_str().ok());

        // Use UserAgentInfo for SDK detection (avoids duplicating parsing logic)
        let ua_info = UserAgentInfo::parse(user_agent);

        // Map SDK name to Library enum variant
        if let Some(sdk_name) = ua_info.sdk_name {
            return Self::from_sdk_name(sdk_name);
        }

        // UserAgentInfo detected a browser via user-agent patterns
        if ua_info.is_browser {
            return Library::PosthogJs;
        }

        // Check for unrecognized posthog-* SDKs (must come before sec-fetch check)
        // This prevents custom SDKs like "posthog-custom/1.0" from being
        // misclassified as browsers
        if user_agent.is_some_and(|ua| ua.starts_with("posthog-")) {
            return Library::Other;
        }

        // Additional browser detection via sec-fetch headers
        // These headers are browser-only and cannot be spoofed by server-side code
        if headers.get("sec-fetch-mode").is_some() || headers.get("sec-fetch-site").is_some() {
            return Library::PosthogJs;
        }

        Library::Other
    }

    /// Convert SDK name string to Library enum variant.
    ///
    /// Uses `as_str()` as the source of truth to ensure consistency between
    /// parsing and serialization.
    fn from_sdk_name(sdk_name: &str) -> Self {
        // Check all known variants using as_str() as the source of truth
        for lib in Self::ALL_KNOWN {
            if lib.as_str() == sdk_name {
                return *lib;
            }
        }
        Library::Other
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderMap;
    use rstest::rstest;

    fn make_headers_with_user_agent(ua: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert("user-agent", ua.parse().unwrap());
        headers
    }

    #[rstest]
    // Server-side SDKs
    #[case("posthog-node/3.1.0", Library::PosthogNode)]
    #[case("posthog-python/2.5.0", Library::PosthogPython)]
    #[case("posthog-php/3.0.0", Library::PosthogPhp)]
    #[case("posthog-ruby/2.3.0", Library::PosthogRuby)]
    #[case("posthog-go/1.0.0", Library::PosthogGo)]
    #[case("posthog-java/1.2.0", Library::PosthogJava)]
    #[case("posthog-dotnet/1.0.0", Library::PosthogDotnet)]
    #[case("posthog-elixir/0.2.0", Library::PosthogElixir)]
    // Client-side SDKs
    #[case("posthog-js/1.88.0", Library::PosthogJs)]
    #[case("posthog-android/3.0.0", Library::PosthogAndroid)]
    #[case("posthog-ios/3.1.0", Library::PosthogIos)]
    #[case("posthog-react-native/2.0.0", Library::PosthogReactNative)]
    #[case("posthog-flutter/2.0.0", Library::PosthogFlutter)]
    // Browser user-agents (detected as posthog-js)
    #[case("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36", Library::PosthogJs)]
    #[case(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
        Library::PosthogJs
    )]
    #[case("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15", Library::PosthogJs)]
    // Unrecognized posthog SDKs → Other (not misclassified as browsers)
    #[case("posthog-custom/1.0 Chrome/91.0 Safari/537.36", Library::Other)]
    // Unknown clients → Other
    #[case("some-random-client/1.0", Library::Other)]
    #[case("curl/7.68.0", Library::Other)]
    #[case("python-requests/2.28.0", Library::Other)]
    fn test_library_from_user_agent(#[case] user_agent: &str, #[case] expected: Library) {
        let headers = make_headers_with_user_agent(user_agent);
        assert_eq!(Library::from_headers(&headers), expected);
    }

    #[test]
    fn test_library_other_with_origin_header_only() {
        // origin/referer headers alone don't indicate browser (can be set by servers)
        let mut headers = HeaderMap::new();
        headers.insert("user-agent", "some-custom-client".parse().unwrap());
        headers.insert("origin", "https://example.com".parse().unwrap());
        assert_eq!(Library::from_headers(&headers), Library::Other);
    }

    #[test]
    fn test_library_other_with_referer_header_only() {
        // origin/referer headers alone don't indicate browser (can be set by servers)
        let mut headers = HeaderMap::new();
        headers.insert("user-agent", "some-custom-client".parse().unwrap());
        headers.insert("referer", "https://example.com/page".parse().unwrap());
        assert_eq!(Library::from_headers(&headers), Library::Other);
    }

    #[test]
    fn test_library_browser_with_sec_fetch_mode_header() {
        // sec-fetch-mode header indicates browser
        let mut headers = HeaderMap::new();
        headers.insert("user-agent", "some-custom-client".parse().unwrap());
        headers.insert("sec-fetch-mode", "navigate".parse().unwrap());
        assert_eq!(Library::from_headers(&headers), Library::PosthogJs);
    }

    #[test]
    fn test_library_browser_with_sec_fetch_site_header() {
        // sec-fetch-site header also indicates browser
        let mut headers = HeaderMap::new();
        headers.insert("user-agent", "some-custom-client".parse().unwrap());
        headers.insert("sec-fetch-site", "same-origin".parse().unwrap());
        assert_eq!(Library::from_headers(&headers), Library::PosthogJs);
    }

    #[test]
    fn test_library_other_missing_user_agent() {
        let headers = HeaderMap::new();
        assert_eq!(Library::from_headers(&headers), Library::Other);
    }

    #[test]
    fn test_library_other_empty_user_agent() {
        let headers = make_headers_with_user_agent("");
        assert_eq!(Library::from_headers(&headers), Library::Other);
    }

    #[rstest]
    #[case(Library::PosthogJs, "posthog-js")]
    #[case(Library::PosthogNode, "posthog-node")]
    #[case(Library::PosthogPython, "posthog-python")]
    #[case(Library::PosthogPhp, "posthog-php")]
    #[case(Library::PosthogRuby, "posthog-ruby")]
    #[case(Library::PosthogGo, "posthog-go")]
    #[case(Library::PosthogJava, "posthog-java")]
    #[case(Library::PosthogDotnet, "posthog-dotnet")]
    #[case(Library::PosthogElixir, "posthog-elixir")]
    #[case(Library::PosthogAndroid, "posthog-android")]
    #[case(Library::PosthogIos, "posthog-ios")]
    #[case(Library::PosthogReactNative, "posthog-react-native")]
    #[case(Library::PosthogFlutter, "posthog-flutter")]
    #[case(Library::Other, "other")]
    fn test_library_display(#[case] library: Library, #[case] expected: &str) {
        assert_eq!(library.to_string(), expected);
    }

    #[rstest]
    #[case(Library::PosthogJs, "\"posthog-js\"")]
    #[case(Library::PosthogNode, "\"posthog-node\"")]
    #[case(Library::PosthogPython, "\"posthog-python\"")]
    #[case(Library::PosthogPhp, "\"posthog-php\"")]
    #[case(Library::PosthogRuby, "\"posthog-ruby\"")]
    #[case(Library::PosthogGo, "\"posthog-go\"")]
    #[case(Library::PosthogJava, "\"posthog-java\"")]
    #[case(Library::PosthogDotnet, "\"posthog-dotnet\"")]
    #[case(Library::PosthogElixir, "\"posthog-elixir\"")]
    #[case(Library::PosthogAndroid, "\"posthog-android\"")]
    #[case(Library::PosthogIos, "\"posthog-ios\"")]
    #[case(Library::PosthogReactNative, "\"posthog-react-native\"")]
    #[case(Library::PosthogFlutter, "\"posthog-flutter\"")]
    #[case(Library::Other, "\"other\"")]
    fn test_library_serialization(#[case] library: Library, #[case] expected_json: &str) {
        assert_eq!(serde_json::to_string(&library).unwrap(), expected_json);
    }

    #[test]
    fn test_from_sdk_name_roundtrip() {
        // Verify that from_sdk_name correctly recognizes all SDK names from as_str()
        for lib in Library::ALL_KNOWN {
            let sdk_name = lib.as_str();
            let parsed = Library::from_sdk_name(sdk_name);
            assert_eq!(
                parsed, *lib,
                "from_sdk_name({sdk_name}) should return {lib:?}"
            );
        }
    }

    #[test]
    fn test_from_sdk_name_unknown_returns_other() {
        assert_eq!(Library::from_sdk_name("unknown-sdk"), Library::Other);
        assert_eq!(Library::from_sdk_name("posthog-custom"), Library::Other);
        assert_eq!(Library::from_sdk_name(""), Library::Other);
    }
}
