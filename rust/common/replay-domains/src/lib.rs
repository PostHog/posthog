//! Authorized domain matching for session replay.
//!
//! A team can list authorized domains for session replay. When the list is not empty,
//! replay is only configured for requests whose `Origin` or `Referer` is on the list.
//! `/flags` and `/config` are served by different processes, so this crate keeps the
//! one matcher both of them use: two copies drifted before, and a team then got
//! replay from one endpoint and not the other.

mod reason;

pub use reason::{SessionRecordingDisabledReason, SESSION_RECORDING_DISABLED_REASON_KEY};

use http::HeaderMap;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};

const AUTHORIZED_MOBILE_AND_DESKTOP_CLIENTS: &[&str] = &[
    "posthog-android",
    "posthog-ios",
    "posthog-react-native",
    "posthog-flutter",
    "posthog-unity",
];

/// Apply the authorized domain check to a cached config, and report why session
/// recording is off when it is off.
///
/// Removes the internal `domains` field, and sets `sessionRecording` to `false` for a
/// request that is not on the team's list.
pub fn sanitize_session_recording(
    config: &mut Value,
    headers: &HeaderMap,
) -> Option<SessionRecordingDisabledReason> {
    let session_recording = config.get_mut("sessionRecording")?;

    let obj = match session_recording.as_object_mut() {
        Some(o) => o,
        // Python already turned recording off for this team
        None => {
            return match session_recording.as_bool() {
                Some(false) => Some(SessionRecordingDisabledReason::NotEnabled),
                _ => None,
            }
        }
    };

    let domains: Vec<String> = match obj.remove("domains") {
        Some(Value::Array(domains)) => domains
            .iter()
            .filter_map(|d| d.as_str().map(String::from))
            .collect(),
        _ => Vec::new(),
    };

    // Empty domains list means always permitted
    if domains.is_empty() || on_permitted_domain(&domains, headers) {
        return None;
    }

    *session_recording = json!(false);
    Some(SessionRecordingDisabledReason::DomainNotAllowed)
}

/// Name on the response which of the causes turned `sessionRecording` off, so that
/// whoever asks why a recording is missing can read it there.
pub fn set_session_recording_disabled_reason(
    config: &mut Value,
    reason: SessionRecordingDisabledReason,
) {
    config[SESSION_RECORDING_DISABLED_REASON_KEY] = json!(reason.as_str());
}

/// Checks if the request originates from a permitted recording domain.
///
/// Returns true if:
/// - Origin or Referer hostname matches one of the allowed domains (supports wildcards)
/// - User-Agent indicates an authorized mobile or desktop client
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

    let is_authorized_mobile_or_desktop_client = user_agent.is_some_and(|ua| {
        AUTHORIZED_MOBILE_AND_DESKTOP_CLIENTS
            .iter()
            .any(|&kw| ua.contains(kw))
    });

    is_authorized_web_client || is_authorized_mobile_or_desktop_client
}

fn parse_domain(url: Option<&str>) -> Option<String> {
    url.and_then(|u| {
        // url::Url::parse rejects `*` in hostnames (WHATWG spec), but Django's
        // urlparse accepts it. Replace `*` with a placeholder before parsing,
        // then restore it — this lets wildcard domains like `https://*.example.com`
        // parse correctly.
        if !u.contains('*') {
            return url::Url::parse(u)
                .ok()
                .and_then(|parsed| parsed.host_str().map(String::from));
        }
        let sanitized = u.replace('*', "_wildcard_");
        url::Url::parse(&sanitized)
            .ok()
            .and_then(|parsed| parsed.host_str().map(|h| h.replace("_wildcard_", "*")))
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
static REGEX_CACHE: LazyLock<Mutex<HashMap<String, regex::Regex>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// Check `hostname` against pre-parsed permitted domains.
fn hostname_matches(permitted_domains: &[String], hostname: Option<&str>) -> bool {
    let hostname = match hostname {
        Some(h) => h,
        None => return false,
    };
    let hostname_stripped = strip_www(hostname);

    for permitted_domain in permitted_domains {
        if let Some(suffix) = permitted_domain.strip_prefix("*.") {
            // A bare `example.com` must not match `*.example.com`, so the dot is part of
            // what the hostname has to end with
            if hostname.ends_with(&format!(".{suffix}")) {
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

    fn headers_with(name: &'static str, value: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(name, value.parse().unwrap());
        headers
    }

    #[test]
    fn test_parse_domain() {
        assert_eq!(
            parse_domain(Some("https://app.example.com")),
            Some("app.example.com".to_string())
        );
        assert_eq!(
            parse_domain(Some("https://app.example.com/path")),
            Some("app.example.com".to_string())
        );
        assert_eq!(
            parse_domain(Some("http://localhost:3000")),
            Some("localhost".to_string())
        );
        assert_eq!(
            parse_domain(Some("https://*.example.com")),
            Some("*.example.com".to_string())
        );

        // Bare domains and empty values carry no scheme, so they do not parse
        assert_eq!(parse_domain(Some("app.example.com")), None);
        assert_eq!(parse_domain(Some("")), None);
        assert_eq!(parse_domain(None), None);
    }

    #[test]
    fn test_on_permitted_domain_with_origin() {
        let domains = vec!["https://app.example.com".to_string()];

        assert!(on_permitted_domain(
            &domains,
            &headers_with("Origin", "https://app.example.com")
        ));
        assert!(on_permitted_domain(
            &domains,
            &headers_with("Origin", "https://app.example.com/")
        ));
        assert!(!on_permitted_domain(
            &domains,
            &headers_with("Origin", "https://wrong.example.com")
        ));
    }

    #[test]
    fn test_on_permitted_domain_with_referer() {
        let domains = vec!["https://app.example.com".to_string()];

        assert!(on_permitted_domain(
            &domains,
            &headers_with("Referer", "https://app.example.com/some/path")
        ));
        assert!(!on_permitted_domain(
            &domains,
            &headers_with("Referer", "https://wrong.example.com/path")
        ));
    }

    #[test]
    fn test_on_permitted_domain_ignores_www_prefix() {
        let domains = vec!["https://example.com".to_string()];

        assert!(on_permitted_domain(
            &domains,
            &headers_with("Origin", "https://www.example.com")
        ));
    }

    #[test]
    fn test_on_permitted_domain_with_wildcards() {
        let domains = vec!["https://*.example.com".to_string()];

        for origin in [
            "https://app.example.com",
            "https://test.example.com",
            "https://deep.nested.example.com",
            "https://www.example.com",
        ] {
            assert!(
                on_permitted_domain(&domains, &headers_with("Origin", origin)),
                "{origin} should match a wildcard domain"
            );
        }

        for origin in [
            // A bare domain has no subdomain to match
            "https://example.com",
            "https://app.evil.com",
            // Suffix injection
            "https://notexample.com",
        ] {
            assert!(
                !on_permitted_domain(&domains, &headers_with("Origin", origin)),
                "{origin} should not match a wildcard domain"
            );
        }
    }

    #[test]
    fn test_on_permitted_domain_non_prefix_wildcard() {
        let domains = vec!["https://app-*.example.com".to_string()];

        assert!(on_permitted_domain(
            &domains,
            &headers_with("Origin", "https://app-staging.example.com")
        ));
        assert!(!on_permitted_domain(
            &domains,
            &headers_with("Origin", "https://other.example.com")
        ));
    }

    #[test]
    fn test_on_permitted_domain_mobile_and_desktop_user_agent() {
        let domains = vec!["https://web-only.com".to_string()];

        for ua in [
            "posthog-android/3.0.0",
            "posthog-ios/2.0.0",
            "posthog-react-native/1.0.0",
            "posthog-flutter/1.0.0",
            "posthog-unity/1.0.0",
        ] {
            assert!(
                on_permitted_domain(&domains, &headers_with("User-Agent", ua)),
                "{ua} should be an authorized client"
            );
        }

        assert!(!on_permitted_domain(
            &domains,
            &headers_with("User-Agent", "Mozilla/5.0")
        ));
    }

    #[test]
    fn test_on_permitted_domain_without_headers() {
        let domains = vec!["https://app.example.com".to_string()];

        assert!(!on_permitted_domain(&domains, &HeaderMap::new()));
    }
}
