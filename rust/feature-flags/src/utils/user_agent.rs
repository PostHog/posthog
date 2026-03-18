//! User-Agent parsing utilities for PostHog SDKs.
//!
//! Provides a unified way to extract SDK information from User-Agent headers,
//! including SDK name, version, and runtime environment detection.

/// Parsed information from a User-Agent header.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UserAgentInfo {
    /// The SDK name if this is a PostHog SDK (e.g., "posthog-python", "posthog-js").
    /// For browser requests without SDK header, this is None.
    /// Uses static str since SDK names are from a known set.
    pub sdk_name: Option<&'static str>,
    /// The SDK version if this is a PostHog SDK.
    pub sdk_version: Option<String>,
    /// Whether this appears to be a browser request.
    pub is_browser: bool,
    /// The runtime environment: client-side, server-side, or unknown.
    pub runtime: RuntimeType,
}

/// The runtime environment for flag evaluation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeType {
    /// Browser or mobile client-side execution.
    Client,
    /// Server-side execution.
    Server,
    /// Unable to determine runtime.
    Unknown,
}

impl UserAgentInfo {
    /// Parse a User-Agent header string into structured information.
    pub fn parse(user_agent: Option<&str>) -> Self {
        let Some(ua) = user_agent else {
            return Self::unknown();
        };

        if ua.is_empty() {
            return Self::unknown();
        }

        // Try to parse as PostHog SDK first
        if let Some(rest) = ua.strip_prefix("posthog-") {
            return Self::parse_posthog_sdk(rest);
        }

        // Check for browser patterns
        if Self::is_browser_user_agent(ua) {
            return Self {
                sdk_name: None,
                sdk_version: None,
                is_browser: true,
                runtime: RuntimeType::Client,
            };
        }

        // Check for common HTTP clients (server-side indicators)
        if ua.contains("python-requests/") || ua.contains("curl/") {
            return Self {
                sdk_name: None,
                sdk_version: None,
                is_browser: false,
                runtime: RuntimeType::Server,
            };
        }

        Self::unknown()
    }

    /// Parse a PostHog SDK User-Agent (after stripping "posthog-" prefix).
    fn parse_posthog_sdk(rest: &str) -> Self {
        // Pattern: <sdk-name>/<version> [optional extra info]
        let Some(slash_idx) = rest.find('/') else {
            return Self::unknown();
        };

        let name = &rest[..slash_idx];
        let version_part = &rest[slash_idx + 1..];
        // Take only the version part (stop at space or end)
        let version = version_part
            .split_whitespace()
            .next()
            .unwrap_or(version_part);

        if name.is_empty() || version.is_empty() {
            return Self::unknown();
        }

        // Match SDK name to static str and determine runtime in one step
        let (sdk_name, runtime) = match name {
            // Server-side SDKs
            "python" => ("posthog-python", RuntimeType::Server),
            "ruby" => ("posthog-ruby", RuntimeType::Server),
            "php" => ("posthog-php", RuntimeType::Server),
            "java" => ("posthog-java", RuntimeType::Server),
            "go" => ("posthog-go", RuntimeType::Server),
            "node" => ("posthog-node", RuntimeType::Server),
            "dotnet" => ("posthog-dotnet", RuntimeType::Server),
            "elixir" => ("posthog-elixir", RuntimeType::Server),
            // Deprecated: posthog-server users are migrating to posthog-java
            "server" => ("posthog-server", RuntimeType::Server),
            // Client-side SDKs (mobile and browser)
            "js" => ("posthog-js", RuntimeType::Client),
            "android" => ("posthog-android", RuntimeType::Client),
            "ios" => ("posthog-ios", RuntimeType::Client),
            "react-native" => ("posthog-react-native", RuntimeType::Client),
            "flutter" => ("posthog-flutter", RuntimeType::Client),
            // Unknown SDK - don't set sdk_name for unrecognized SDKs
            _ => return Self::unknown(),
        };

        Self {
            sdk_name: Some(sdk_name),
            sdk_version: Some(version.to_string()),
            is_browser: false,
            runtime,
        }
    }

    /// Check if the User-Agent indicates a browser.
    fn is_browser_user_agent(ua: &str) -> bool {
        ua.contains("Mozilla/")
            || ua.contains("Chrome/")
            || ua.contains("Safari/")
            || ua.contains("Firefox/")
            || ua.contains("Edge/")
    }

    fn unknown() -> Self {
        Self {
            sdk_name: None,
            sdk_version: None,
            is_browser: false,
            runtime: RuntimeType::Unknown,
        }
    }

    /// Get a low-cardinality client type label suitable for metrics.
    /// Returns values like "posthog-python", "browser", or "other".
    pub fn client_type_label(&self) -> &'static str {
        if let Some(name) = self.sdk_name {
            return name;
        }
        if self.is_browser {
            return "browser";
        }
        "other"
    }

    /// Get a low-cardinality client type label suitable for metrics.
    /// This version parses the raw user-agent and handles additional patterns
    /// like curl and python-requests that aren't PostHog SDKs.
    pub fn client_type_label_from_raw(user_agent: Option<&str>) -> &'static str {
        let Some(ua) = user_agent else {
            return "unknown";
        };

        if ua.is_empty() {
            return "unknown";
        }

        // Check for common HTTP clients first (not PostHog SDKs)
        if ua.contains("curl/") {
            return "curl";
        }
        if ua.contains("python-requests/") {
            return "python-requests";
        }

        // Delegate to client_type_label for SDKs, browsers, and other
        Self::parse(Some(ua)).client_type_label()
    }

    /// Get the library name for canonical logging.
    /// Returns the SDK name for PostHog SDKs, "web" for browsers, or None.
    pub fn lib_for_logging(&self) -> Option<&'static str> {
        self.sdk_name.or(self.is_browser.then_some("web"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case(
        "posthog-python/3.0.0",
        Some("posthog-python"),
        Some("3.0.0"),
        RuntimeType::Server
    )]
    #[case(
        "posthog-node/1.2.3",
        Some("posthog-node"),
        Some("1.2.3"),
        RuntimeType::Server
    )]
    #[case(
        "posthog-ruby/2.0.0",
        Some("posthog-ruby"),
        Some("2.0.0"),
        RuntimeType::Server
    )]
    #[case(
        "posthog-go/1.0.0",
        Some("posthog-go"),
        Some("1.0.0"),
        RuntimeType::Server
    )]
    #[case(
        "posthog-php/3.1.0",
        Some("posthog-php"),
        Some("3.1.0"),
        RuntimeType::Server
    )]
    #[case(
        "posthog-java/1.1.0",
        Some("posthog-java"),
        Some("1.1.0"),
        RuntimeType::Server
    )]
    #[case(
        "posthog-dotnet/1.0.0",
        Some("posthog-dotnet"),
        Some("1.0.0"),
        RuntimeType::Server
    )]
    #[case(
        "posthog-elixir/0.2.0",
        Some("posthog-elixir"),
        Some("0.2.0"),
        RuntimeType::Server
    )]
    #[case(
        "posthog-server/1.0.0",
        Some("posthog-server"),
        Some("1.0.0"),
        RuntimeType::Server
    )]
    #[case(
        "posthog-server/3.2.1 (Android SDK)",
        Some("posthog-server"),
        Some("3.2.1"),
        RuntimeType::Server
    )]
    #[case(
        "posthog-js/1.88.0",
        Some("posthog-js"),
        Some("1.88.0"),
        RuntimeType::Client
    )]
    #[case(
        "posthog-android/3.0.0",
        Some("posthog-android"),
        Some("3.0.0"),
        RuntimeType::Client
    )]
    #[case(
        "posthog-ios/3.0.0",
        Some("posthog-ios"),
        Some("3.0.0"),
        RuntimeType::Client
    )]
    #[case(
        "posthog-react-native/2.5.0",
        Some("posthog-react-native"),
        Some("2.5.0"),
        RuntimeType::Client
    )]
    #[case(
        "posthog-flutter/4.0.0",
        Some("posthog-flutter"),
        Some("4.0.0"),
        RuntimeType::Client
    )]
    #[case(
        "posthog-python/3.0.0 (Linux; Python 3.11)",
        Some("posthog-python"),
        Some("3.0.0"),
        RuntimeType::Server
    )]
    fn test_parse_posthog_sdks(
        #[case] ua: &str,
        #[case] expected_name: Option<&str>,
        #[case] expected_version: Option<&str>,
        #[case] expected_runtime: RuntimeType,
    ) {
        let info = UserAgentInfo::parse(Some(ua));
        assert_eq!(info.sdk_name, expected_name);
        assert_eq!(info.sdk_version.as_deref(), expected_version);
        assert_eq!(info.runtime, expected_runtime);
        assert!(!info.is_browser);
    }

    #[rstest]
    #[case("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")]
    #[case("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")]
    #[case("Mozilla/5.0 (X11; Linux x86_64) Firefox/89.0")]
    #[case("Chrome/120.0.0.0 Safari/537.36")]
    fn test_parse_browser_user_agents(#[case] ua: &str) {
        let info = UserAgentInfo::parse(Some(ua));
        assert!(info.is_browser);
        assert!(info.sdk_name.is_none());
        assert!(info.sdk_version.is_none());
        assert_eq!(info.runtime, RuntimeType::Client);
    }

    #[rstest]
    #[case("curl/7.68.0", RuntimeType::Server)]
    #[case("python-requests/2.28.0", RuntimeType::Server)]
    fn test_parse_http_clients(#[case] ua: &str, #[case] expected_runtime: RuntimeType) {
        let info = UserAgentInfo::parse(Some(ua));
        assert!(!info.is_browser);
        assert!(info.sdk_name.is_none());
        assert_eq!(info.runtime, expected_runtime);
    }

    #[rstest]
    #[case("posthog-python", None, None)] // No slash
    #[case("posthog-python/", None, None)] // Empty version
    #[case("posthog-/1.0.0", None, None)] // Empty SDK name
    #[case("", None, None)] // Empty string
    fn test_parse_edge_cases(
        #[case] ua: &str,
        #[case] expected_name: Option<&str>,
        #[case] expected_version: Option<&str>,
    ) {
        let info = UserAgentInfo::parse(Some(ua));
        assert_eq!(info.sdk_name, expected_name);
        assert_eq!(info.sdk_version.as_deref(), expected_version);
    }

    #[test]
    fn test_parse_none() {
        let info = UserAgentInfo::parse(None);
        assert!(info.sdk_name.is_none());
        assert!(info.sdk_version.is_none());
        assert!(!info.is_browser);
        assert_eq!(info.runtime, RuntimeType::Unknown);
    }

    #[rstest]
    #[case(Some("posthog-js/1.88.0"), "posthog-js")]
    #[case(Some("posthog-android/3.1.0"), "posthog-android")]
    #[case(Some("posthog-ios/3.0.0"), "posthog-ios")]
    #[case(Some("posthog-react-native/2.5.0"), "posthog-react-native")]
    #[case(Some("posthog-flutter/4.0.0"), "posthog-flutter")]
    #[case(Some("posthog-python/1.4.0"), "posthog-python")]
    #[case(Some("posthog-ruby/2.0.0"), "posthog-ruby")]
    #[case(Some("posthog-php/3.0.0"), "posthog-php")]
    #[case(Some("posthog-java/1.0.0"), "posthog-java")]
    #[case(Some("posthog-go/0.1.0"), "posthog-go")]
    #[case(Some("posthog-node/2.2.0"), "posthog-node")]
    #[case(Some("posthog-dotnet/1.0.0"), "posthog-dotnet")]
    #[case(Some("posthog-elixir/0.2.0"), "posthog-elixir")]
    #[case(Some("posthog-server/1.0.0"), "posthog-server")]
    #[case(
        Some("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
        "browser"
    )]
    #[case(
        Some("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/91.0.4472.124"),
        "browser"
    )]
    #[case(Some("Mozilla/5.0 (X11; Linux x86_64) Firefox/89.0"), "browser")]
    #[case(Some("curl/7.68.0"), "curl")]
    #[case(Some("python-requests/2.28.0"), "python-requests")]
    #[case(Some("custom-client/1.0"), "other")]
    #[case(Some(""), "unknown")]
    #[case(None, "unknown")]
    fn test_client_type_label(#[case] user_agent: Option<&str>, #[case] expected: &str) {
        assert_eq!(
            UserAgentInfo::client_type_label_from_raw(user_agent),
            expected
        );
    }

    #[rstest]
    #[case("posthog-python/3.0.0", Some("posthog-python"))]
    #[case("posthog-node/1.2.3", Some("posthog-node"))]
    #[case("posthog-android/3.0.0", Some("posthog-android"))]
    #[case("posthog-server/1.0.0", Some("posthog-server"))]
    #[case("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", Some("web"))]
    #[case("Chrome/120.0.0.0 Safari/537.36", Some("web"))]
    #[case("curl/7.68.0", None)]
    #[case("python-requests/2.28.0", None)]
    #[case("custom-client/1.0", None)]
    fn test_lib_for_logging(#[case] ua: &str, #[case] expected: Option<&str>) {
        let info = UserAgentInfo::parse(Some(ua));
        assert_eq!(info.lib_for_logging(), expected);
    }
}
