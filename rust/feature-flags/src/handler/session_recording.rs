use crate::{
    api::types::{SessionRecordingConfig, SessionRecordingField},
    config::{Config, TeamIdCollection},
    team::team_models::Team,
};
use axum::http::HeaderMap;
use regex;
use serde_json::{json, Value};

const AUTHORIZED_MOBILE_CLIENTS: &[&str] = &[
    "posthog-android",
    "posthog-ios",
    "posthog-react-native",
    "posthog-flutter",
];

// Hard-coded values set for the session recording beta, still haven't come up with more sensible
// defaults so these are what they are for now.
const SAMPLE_RATE_FULL: &str = "1.00";
const CANVAS_FPS_DEFAULT: u8 = 3;
const CANVAS_QUALITY_DEFAULT: &str = "0.4";

pub fn session_recording_config_response(
    team: &Team,
    headers: &HeaderMap,
    config: &Config,
) -> Option<SessionRecordingField> {
    if !team.session_recording_opt_in || session_recording_domain_not_allowed(team, headers) {
        return Some(SessionRecordingField::Disabled(false));
    }

    let capture_console_logs = team.capture_console_log_opt_in.unwrap_or(false);
    let sample_rate = team.session_recording_sample_rate.as_ref().and_then(|sr| {
        let sr_str = sr.to_string();
        if sr_str == SAMPLE_RATE_FULL {
            None
        } else {
            Some(sr_str)
        }
    });
    let minimum_duration = team.session_recording_minimum_duration_milliseconds;

    let linked_flag = get_linked_flag_value(
        team.session_recording_linked_flag
            .clone()
            .map(|mut v| v.take()),
    );

    let rrweb_script_config = if !config.session_replay_rrweb_script.is_empty() {
        let is_team_allowed = match &config.session_replay_rrweb_script_allowed_teams {
            TeamIdCollection::All => true,
            TeamIdCollection::None => false,
            TeamIdCollection::TeamIds(ids) => ids.contains(&team.id),
        };

        if is_team_allowed {
            Some(serde_json::json!({
                "script": config.session_replay_rrweb_script
            }))
        } else {
            None
        }
    } else {
        None
    };

    // session_replay_config logic - only include canvas fields if record_canvas is configured
    let (record_canvas, canvas_fps, canvas_quality) = if let Some(cfg) = &team.session_replay_config
    {
        if let Some(record_canvas) = cfg.get("record_canvas") {
            let record_canvas_bool = record_canvas.as_bool().unwrap_or(false);
            let fps = if record_canvas_bool {
                Some(CANVAS_FPS_DEFAULT)
            } else {
                None
            };
            let quality = if record_canvas_bool {
                Some(CANVAS_QUALITY_DEFAULT.to_string())
            } else {
                None
            };
            (Some(record_canvas_bool), fps, quality)
        } else {
            (None, None, None)
        }
    } else {
        (None, None, None)
    };

    let config = SessionRecordingConfig {
        endpoint: Some("/s/".to_string()),
        console_log_recording_enabled: Some(capture_console_logs),
        recorder_version: Some("v2".to_string()),
        sample_rate,
        minimum_duration_milliseconds: minimum_duration,
        linked_flag,
        network_payload_capture: team
            .session_recording_network_payload_capture_config
            .as_ref()
            .map(|j| j.0.clone()),
        masking: team
            .session_recording_masking_config
            .as_ref()
            .map(|j| j.0.clone()),
        url_triggers: team
            .session_recording_url_trigger_config
            .as_ref()
            .map(|vec| Value::Array(vec.iter().map(|j| j.0.clone()).collect())),
        url_blocklist: team
            .session_recording_url_blocklist_config
            .as_ref()
            .map(|vec| Value::Array(vec.iter().map(|j| j.0.clone()).collect())),
        event_triggers: team
            .session_recording_event_trigger_config
            .as_ref()
            .map(|vec| {
                Value::Array(
                    vec.iter()
                        .filter_map(|s| s.as_ref().map(|s| Value::String(s.clone())))
                        .collect(),
                )
            }),
        trigger_match_type: team
            .session_recording_trigger_match_type_config
            .as_ref()
            .map(|s| Value::String(s.clone())),
        script_config: rrweb_script_config,
        record_canvas,
        canvas_fps,
        canvas_quality,
    };

    Some(SessionRecordingField::Config(Box::new(config)))
}

fn session_recording_domain_not_allowed(team: &Team, headers: &HeaderMap) -> bool {
    matches!(&team.recording_domains, Some(domains) if !domains.is_empty() && !on_permitted_recording_domain(domains, headers))
}

fn hostname_in_allowed_url_list(allowed: &[String], hostname: Option<&str>) -> bool {
    let hostname = match hostname {
        Some(h) => h,
        None => return false,
    };

    let permitted_domains: Vec<String> = allowed
        .iter()
        .filter_map(|url| parse_domain(Some(url)))
        .collect();

    for permitted_domain in permitted_domains {
        if permitted_domain.contains('*') {
            // crude wildcard: treat '*' as regex '.*'
            let pattern = format!(
                "^{}$",
                regex::escape(&permitted_domain).replace("\\*", ".*")
            );
            if regex::Regex::new(&pattern).is_ok_and(|re| re.is_match(hostname)) {
                return true;
            }
        } else if permitted_domain == hostname {
            return true;
        }
    }
    false
}

fn get_linked_flag_value(linked_flag_config: Option<Value>) -> Option<Value> {
    match &linked_flag_config {
        Some(cfg) => {
            let key = cfg.get("key");
            let variant = cfg.get("variant");
            match (key, variant) {
                (Some(Value::String(k)), Some(Value::String(v))) => {
                    Some(json!({"flag": k, "variant": v}))
                }
                (Some(Value::String(k)), None | Some(Value::Null)) => {
                    Some(Value::String(k.clone()))
                }
                _ => None,
            }
        }
        None => None,
    }
}

fn parse_domain(url: Option<&str>) -> Option<String> {
    url.and_then(|u| {
        // Try to parse as URL. If it starts with http:// or https://, this will work
        if let Ok(parsed) = url::Url::parse(u) {
            parsed.host_str().map(|h| h.to_string())
        } else {
            // If parsing fails (e.g., bare domain without protocol), return None to match Python
            None
        }
    })
}

fn on_permitted_recording_domain(recording_domains: &[String], headers: &HeaderMap) -> bool {
    let origin = headers.get("Origin").and_then(|v| v.to_str().ok());
    let referer = headers.get("Referer").and_then(|v| v.to_str().ok());
    let user_agent = headers.get("User-Agent").and_then(|v| v.to_str().ok());

    // Parse the domain from the Origin and Referer headers
    let origin_hostname = parse_domain(origin);
    let referer_hostname = parse_domain(referer);

    let is_authorized_web_client =
        hostname_in_allowed_url_list(recording_domains, origin_hostname.as_deref())
            || hostname_in_allowed_url_list(recording_domains, referer_hostname.as_deref());

    let is_authorized_mobile_client =
        user_agent.is_some_and(|ua| AUTHORIZED_MOBILE_CLIENTS.iter().any(|&kw| ua.contains(kw)));

    is_authorized_web_client || is_authorized_mobile_client
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_get_linked_flag_value_with_null_variant() {
        let config = json!({
            "id": 105969,
            "key": "record_sessions",
            "variant": null
        });

        let result = get_linked_flag_value(Some(config));

        assert_eq!(result, Some(Value::String("record_sessions".to_string())));
    }

    #[test]
    fn test_session_recording_domain_allowed_with_empty_domains() {
        use axum::http::HeaderMap;

        let team = Team {
            recording_domains: Some(vec![]),
            ..Team::default()
        };

        let headers = HeaderMap::new();

        // Empty domains list should allow recording (return false)
        assert!(!session_recording_domain_not_allowed(&team, &headers));
    }

    #[test]
    fn test_parse_domain() {
        // Test with full URLs - should extract hostname
        assert_eq!(
            parse_domain(Some("https://app.example.com")),
            Some("app.example.com".to_string())
        );
        assert_eq!(
            parse_domain(Some("https://app.example.com/")),
            Some("app.example.com".to_string())
        );
        assert_eq!(
            parse_domain(Some("http://localhost:3000")),
            Some("localhost".to_string())
        );
        assert_eq!(
            parse_domain(Some("https://app.example.com/path")),
            Some("app.example.com".to_string())
        );

        // Test with bare domains
        assert_eq!(parse_domain(Some("app.example.com")), None);
        assert_eq!(parse_domain(Some("example.com")), None);

        // Test with wildcard domains
        assert_eq!(
            parse_domain(Some("https://*.example.com")),
            Some("*.example.com".to_string())
        );
        assert_eq!(parse_domain(Some("*.example.com")), None);

        // Test with empty string and None
        assert_eq!(parse_domain(Some("")), None);
        assert_eq!(parse_domain(None), None);
    }

    #[test]
    fn test_on_permitted_recording_domain_with_origin() {
        use axum::http::HeaderMap;

        let recording_domains = vec!["https://app.example.com/".to_string()];

        // Test with Origin header (without trailing slash)
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://app.example.com".parse().unwrap());
        assert!(on_permitted_recording_domain(&recording_domains, &headers));

        // Test with Origin header (with trailing slash)
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://app.example.com/".parse().unwrap());
        assert!(on_permitted_recording_domain(&recording_domains, &headers));

        // Test with correct domain with path
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://app.example.com/path".parse().unwrap());
        assert!(on_permitted_recording_domain(&recording_domains, &headers));

        // Test with wrong domain
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://wrong.example.com".parse().unwrap());
        assert!(!on_permitted_recording_domain(&recording_domains, &headers));
    }

    #[test]
    fn test_on_permitted_recording_domain_with_referer() {
        use axum::http::HeaderMap;

        let recording_domains = vec!["https://app.example.com".to_string()];

        // Test with Referer header
        let mut headers = HeaderMap::new();
        headers.insert(
            "Referer",
            "https://app.example.com/some/path".parse().unwrap(),
        );
        assert!(on_permitted_recording_domain(&recording_domains, &headers));

        // Test with wrong domain
        let mut headers = HeaderMap::new();
        headers.insert("Referer", "https://wrong.example.com/path".parse().unwrap());
        assert!(!on_permitted_recording_domain(&recording_domains, &headers));
    }

    #[test]
    fn test_on_permitted_recording_domain_with_wildcards() {
        use axum::http::HeaderMap;

        let recording_domains = vec!["https://*.example.com".to_string()];

        // Test with matching subdomain
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://app.example.com".parse().unwrap());
        assert!(on_permitted_recording_domain(&recording_domains, &headers));

        // Test with different subdomain
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://test.example.com".parse().unwrap());
        assert!(on_permitted_recording_domain(&recording_domains, &headers));

        // Test with no subdomain - should NOT match
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://example.com".parse().unwrap());
        assert!(!on_permitted_recording_domain(&recording_domains, &headers));

        // Test with wrong domain
        let mut headers = HeaderMap::new();
        headers.insert("Origin", "https://app.wrong.com".parse().unwrap());
        assert!(!on_permitted_recording_domain(&recording_domains, &headers));
    }
}
