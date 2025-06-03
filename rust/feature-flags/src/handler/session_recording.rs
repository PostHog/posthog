use crate::{
    api::types::{SessionRecordingConfig, SessionRecordingField},
    team::team_models::Team,
};
use regex;
use serde_json::{json, Value};

use super::types::RequestContext;

pub fn session_recording_config_response(
    team: &Team,
    request_context: &RequestContext,
) -> Option<SessionRecordingField> {
    if !team.session_recording_opt_in || session_recording_domain_not_allowed(team, request_context)
    {
        return Some(SessionRecordingField::Disabled(false));
    }

    let capture_console_logs = team.capture_console_log_opt_in.unwrap_or(false);
    let sample_rate = team.session_recording_sample_rate.as_ref().and_then(|sr| {
        let sr_str = sr.to_string();
        if sr_str == "1.00" {
            None
        } else {
            Some(sr_str)
        }
    });
    let minimum_duration = team.session_recording_minimum_duration_milliseconds;

    // linked_flag logic
    let linked_flag = match &team.session_recording_linked_flag {
        Some(cfg) => {
            let key = cfg.get("key");
            let variant = cfg.get("variant");
            match (key, variant) {
                (Some(k), Some(v)) => Some(json!({"flag": k, "variant": v})),
                (Some(k), None) => Some(k.clone()),
                _ => None,
            }
        }
        None => None,
    };

    // rrweb_script_config logic (stub, you may want to wire this up to settings)
    let rrweb_script_config = None::<serde_json::Value>;

    // session_replay_config logic
    let (record_canvas, canvas_fps, canvas_quality) = if let Some(cfg) = &team.session_replay_config
    {
        if let Some(record_canvas) = cfg.get("record_canvas") {
            let record_canvas_bool = record_canvas.as_bool().unwrap_or(false);
            let fps = if record_canvas_bool { Some(3) } else { None };
            let quality = if record_canvas_bool {
                Some("0.4".to_string())
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
            .map(|vec| Value::Array(vec.iter().map(|s| Value::String(s.clone())).collect())),
        trigger_match_type: team
            .session_recording_trigger_match_type_config
            .as_ref()
            .map(|s| Value::String(s.clone())),
        script_config: rrweb_script_config,
        record_canvas,
        canvas_fps,
        canvas_quality,
    };

    Some(SessionRecordingField::Config(config))
}

fn session_recording_domain_not_allowed(team: &Team, request_context: &RequestContext) -> bool {
    match &team.recording_domains {
        Some(domains) if !on_permitted_recording_domain(domains, request_context) => true,
        _ => false,
    }
}

fn hostname_in_allowed_url_list(allowed: &Vec<String>, hostname: Option<&str>) -> bool {
    let hostname = match hostname {
        Some(h) => h,
        None => return false,
    };
    for domain in allowed {
        if domain.contains('*') {
            // crude wildcard: treat '*' as regex '.*'
            let pattern = format!("^{}$", regex::escape(domain).replace("\\*", ".*"));
            if regex::Regex::new(&pattern).unwrap().is_match(hostname) {
                return true;
            }
        } else if domain == hostname {
            return true;
        }
    }
    false
}

fn on_permitted_recording_domain(
    recording_domains: &Vec<String>,
    request_context: &RequestContext,
) -> bool {
    let origin = request_context
        .headers
        .get("Origin")
        .and_then(|v| v.to_str().ok());
    let referer = request_context
        .headers
        .get("Referer")
        .and_then(|v| v.to_str().ok());
    let user_agent = request_context
        .headers
        .get("User-Agent")
        .and_then(|v| v.to_str().ok());

    let is_authorized_web_client =
        hostname_in_allowed_url_list(recording_domains, origin.as_deref())
            || hostname_in_allowed_url_list(recording_domains, referer.as_deref());

    let is_authorized_mobile_client = user_agent.map_or(false, |ua| {
        [
            "posthog-android",
            "posthog-ios",
            "posthog-react-native",
            "posthog-flutter",
        ]
        .iter()
        .any(|kw| ua.contains(kw))
    });

    is_authorized_web_client || is_authorized_mobile_client
}
