//! Config sanitization for public-facing responses.
//!
//! Matches Python's `sanitize_config_for_public_cdn` behavior:
//! - Removes `siteAppsJS` (raw JS only needed for array.js bundle, not JSON API)
//! - Removes `sessionRecording.domains` (internal field, not needed by SDK)
//! - Sets `sessionRecording` to `false` if request origin not in permitted domains

use axum::http::HeaderMap;
use serde_json::{json, Value};

const AUTHORIZED_MOBILE_CLIENTS: &[&str] = &[
    "posthog-android",
    "posthog-ios",
    "posthog-react-native",
    "posthog-flutter",
];

/// Sanitize cached config before returning to clients.
pub fn sanitize_config_for_client(cached_config: &mut Value, headers: &HeaderMap) {
    if let Some(obj) = cached_config.as_object_mut() {
        obj.remove("siteAppsJS");
    }

    let session_recording = match cached_config.get_mut("sessionRecording") {
        Some(sr) => sr,
        None => return,
    };

    let obj = match session_recording.as_object_mut() {
        Some(o) => o,
        None => return,
    };

    let domains = obj.remove("domains");

    if let Some(domains_value) = domains {
        if let Some(domains_array) = domains_value.as_array() {
            let domain_strings: Vec<String> = domains_array
                .iter()
                .filter_map(|d| d.as_str().map(String::from))
                .collect();

            // Empty domains list means always permitted
            if !domain_strings.is_empty() && !on_permitted_domain(&domain_strings, headers) {
                *session_recording = json!(false);
            }
        }
    }
}

/// Checks if the request originates from a permitted recording domain.
///
/// Returns true if:
/// - Origin or Referer hostname matches one of the allowed domains (supports wildcards)
/// - User-Agent indicates an authorized mobile client (android, ios, react-native, flutter)
pub fn on_permitted_domain(recording_domains: &[String], headers: &HeaderMap) -> bool {
    let origin = headers.get("Origin").and_then(|v| v.to_str().ok());
    let referer = headers.get("Referer").and_then(|v| v.to_str().ok());
    let user_agent = headers.get("User-Agent").and_then(|v| v.to_str().ok());

    let origin_hostname = parse_domain(origin);
    let referer_hostname = parse_domain(referer);

    // Pre-parse the allowed domain list once per request (not once per hostname check)
    let permitted_domains: Vec<String> = recording_domains
        .iter()
        .filter_map(|url| parse_domain(Some(url)))
        .collect();

    let is_authorized_web_client = hostname_matches(&permitted_domains, origin_hostname.as_deref())
        || hostname_matches(&permitted_domains, referer_hostname.as_deref());

    let is_authorized_mobile_client =
        user_agent.is_some_and(|ua| AUTHORIZED_MOBILE_CLIENTS.iter().any(|&kw| ua.contains(kw)));

    is_authorized_web_client || is_authorized_mobile_client
}

fn parse_domain(url: Option<&str>) -> Option<String> {
    url.and_then(|u| {
        // url::Url::parse rejects `*` in hostnames (WHATWG spec), but Django's
        // urlparse accepts it. Replace `*` with a placeholder before parsing,
        // then restore it — this lets wildcard domains like `https://*.example.com`
        // parse correctly.
        let sanitized = u.replace('*', "_wildcard_");
        if let Ok(parsed) = url::Url::parse(&sanitized) {
            parsed.host_str().map(|h| h.replace("_wildcard_", "*"))
        } else {
            None
        }
    })
}

/// Strip `www.` prefix for domain comparison, matching Django's `_strip_www`.
fn strip_www(domain: &str) -> &str {
    domain.strip_prefix("www.").unwrap_or(domain)
}

/// Global cache for compiled wildcard regexes.
///
/// Bounded by the number of unique non-prefix wildcard patterns across all team
/// configs — tiny in practice (most teams don't use patterns like `app-*.example.com`).
static REGEX_CACHE: std::sync::LazyLock<
    std::sync::Mutex<std::collections::HashMap<String, regex::Regex>>,
> = std::sync::LazyLock::new(|| std::sync::Mutex::new(std::collections::HashMap::new()));

/// Check `hostname` against pre-parsed permitted domains.
fn hostname_matches(permitted_domains: &[String], hostname: Option<&str>) -> bool {
    let hostname = match hostname {
        Some(h) => h,
        None => return false,
    };
    let hostname_stripped = strip_www(hostname);

    for permitted_domain in permitted_domains {
        if let Some(suffix) = permitted_domain.strip_prefix("*.") {
            // Fast path: `*.example.com` → check if hostname ends with `.example.com`
            // and has at least one character before the dot (bare `example.com` shouldn't match)
            let dot_suffix = format!(".{suffix}");
            if hostname.ends_with(&dot_suffix) || hostname_stripped.ends_with(&dot_suffix) {
                return true;
            }
        } else if permitted_domain.contains('*') {
            // Rare: non-prefix wildcards like `app-*.example.com` — fall back to regex.
            // Regex is cached to avoid re-compilation per request.
            let pattern = format!("^{}$", regex::escape(permitted_domain).replace("\\*", ".*"));
            let cache = REGEX_CACHE.lock().unwrap_or_else(|e| e.into_inner());
            // We can't hold the lock across the match check, but cloning a compiled
            // Regex is cheap (Arc internally). Look up or insert, then drop the lock.
            let re = cache.get(&pattern).cloned();
            drop(cache);

            let re = match re {
                Some(r) => r,
                None => {
                    let compiled = match regex::Regex::new(&pattern) {
                        Ok(r) => r,
                        Err(_) => continue,
                    };
                    let mut cache = REGEX_CACHE.lock().unwrap_or_else(|e| e.into_inner());
                    cache.entry(pattern).or_insert(compiled).clone()
                }
            };
            if re.is_match(hostname) || re.is_match(hostname_stripped) {
                return true;
            }
        } else if strip_www(permitted_domain) == hostname_stripped {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_removes_site_apps_js() {
        let mut config = json!({
            "siteApps": [{"id": 1}],
            "siteAppsJS": ["function() {}"],
            "heatmaps": true
        });

        sanitize_config_for_client(&mut config, &HeaderMap::new());

        assert!(config.get("siteAppsJS").is_none());
        assert!(config.get("siteApps").is_some());
        assert_eq!(config.get("heatmaps"), Some(&json!(true)));
    }

    #[test]
    fn test_strips_session_recording_domains() {
        let mut config = json!({
            "sessionRecording": {
                "endpoint": "/s/",
                "domains": ["https://example.com"]
            }
        });

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://example.com".parse().unwrap());

        sanitize_config_for_client(&mut config, &headers);

        let sr = config.get("sessionRecording").unwrap();
        assert!(sr.is_object());
        assert!(sr.get("domains").is_none());
        assert_eq!(sr.get("endpoint"), Some(&json!("/s/")));
    }

    #[test]
    fn test_disables_recording_for_wrong_domain() {
        let mut config = json!({
            "sessionRecording": {
                "endpoint": "/s/",
                "domains": ["https://allowed.com"]
            }
        });

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://evil.com".parse().unwrap());

        sanitize_config_for_client(&mut config, &headers);

        assert_eq!(config.get("sessionRecording"), Some(&json!(false)));
    }

    #[test]
    fn test_empty_domains_allows_all() {
        let mut config = json!({
            "sessionRecording": {
                "endpoint": "/s/",
                "domains": []
            }
        });

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://any-site.com".parse().unwrap());

        sanitize_config_for_client(&mut config, &headers);

        let sr = config.get("sessionRecording").unwrap();
        assert!(sr.is_object());
    }

    #[test]
    fn test_no_session_recording_field_is_noop() {
        let mut config = json!({"heatmaps": true});

        sanitize_config_for_client(&mut config, &HeaderMap::new());

        assert_eq!(config, json!({"heatmaps": true}));
    }

    #[test]
    fn test_session_recording_false_passes_through() {
        let mut config = json!({"sessionRecording": false});

        sanitize_config_for_client(&mut config, &HeaderMap::new());

        assert_eq!(config.get("sessionRecording"), Some(&json!(false)));
    }

    #[test]
    fn test_on_permitted_domain_with_origin() {
        let domains = vec!["https://app.example.com".to_string()];

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://app.example.com".parse().unwrap());
        assert!(on_permitted_domain(&domains, &headers));

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://wrong.example.com".parse().unwrap());
        assert!(!on_permitted_domain(&domains, &headers));
    }

    #[test]
    fn test_on_permitted_domain_with_referer() {
        let domains = vec!["https://app.example.com".to_string()];

        let mut headers = HeaderMap::new();
        headers.insert(
            "Referer",
            "https://app.example.com/some/path".parse().unwrap(),
        );
        assert!(on_permitted_domain(&domains, &headers));
    }

    #[test]
    fn test_on_permitted_domain_with_wildcards() {
        let domains = vec!["https://*.example.com".to_string()];

        // Subdomain matches (fast path: suffix check)
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://app.example.com".parse().unwrap());
        assert!(on_permitted_domain(&domains, &headers));

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://test.example.com".parse().unwrap());
        assert!(on_permitted_domain(&domains, &headers));

        // Deep subdomain matches
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://deep.nested.example.com".parse().unwrap());
        assert!(on_permitted_domain(&domains, &headers));

        // Bare domain without subdomain should NOT match wildcard
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://example.com".parse().unwrap());
        assert!(!on_permitted_domain(&domains, &headers));

        // Wrong domain should NOT match
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://app.evil.com".parse().unwrap());
        assert!(!on_permitted_domain(&domains, &headers));

        // Suffix injection: `notexample.com` should NOT match `*.example.com`
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://notexample.com".parse().unwrap());
        assert!(!on_permitted_domain(&domains, &headers));
    }

    #[test]
    fn test_on_permitted_domain_non_prefix_wildcard() {
        // Rare pattern like `app-*.example.com` — falls back to regex
        let domains = vec!["https://app-*.example.com".to_string()];

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://app-staging.example.com".parse().unwrap());
        assert!(on_permitted_domain(&domains, &headers));

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://app-prod.example.com".parse().unwrap());
        assert!(on_permitted_domain(&domains, &headers));

        // Should NOT match without the prefix
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://other.example.com".parse().unwrap());
        assert!(!on_permitted_domain(&domains, &headers));
    }

    #[test]
    fn test_on_permitted_domain_wildcard_with_www() {
        let domains = vec!["https://*.example.com".to_string()];

        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://www.example.com".parse().unwrap());
        assert!(on_permitted_domain(&domains, &headers));
    }

    #[test]
    fn test_on_permitted_domain_mobile_user_agent() {
        let domains = vec!["https://web-only.com".to_string()];

        for ua in [
            "posthog-android/3.0.0",
            "posthog-ios/2.0.0",
            "posthog-react-native/1.0.0",
            "posthog-flutter/1.0.0",
        ] {
            let mut headers = HeaderMap::new();
            headers.insert("User-Agent", ua.parse().unwrap());
            assert!(
                on_permitted_domain(&domains, &headers),
                "Expected mobile UA '{ua}' to be permitted"
            );
        }
    }

    #[test]
    fn test_on_permitted_domain_no_headers() {
        let domains = vec!["https://example.com".to_string()];
        let headers = HeaderMap::new();
        assert!(!on_permitted_domain(&domains, &headers));
    }

    #[test]
    fn test_on_permitted_domain_www_equivalence() {
        // Allowed domain without www, request with www
        let domains = vec!["https://example.com".to_string()];
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://www.example.com".parse().unwrap());
        assert!(on_permitted_domain(&domains, &headers));

        // Allowed domain with www, request without www
        let domains = vec!["https://www.example.com".to_string()];
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://example.com".parse().unwrap());
        assert!(on_permitted_domain(&domains, &headers));
    }
}
