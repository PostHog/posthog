use chrono::{DateTime, Utc};
use sha2::{Sha256, Digest};
use std::collections::HashMap;

use crate::sentry::{
    SentryEvent, SentryException, SentryStackFrame, SentryStacktrace
};
use crate::posthog::{
    PostHogEvent, PostHogException, PostHogProperties, PostHogStackFrame,
    PostHogStacktrace, PostHogMechanism
};

pub fn convert_sentry_to_posthog(
    sentry_event: SentryEvent,
    api_key: String,
    distinct_id: Option<String>,
) -> PostHogEvent {
    let distinct_id = distinct_id.unwrap_or_else(|| {
        // Use user ID if available, otherwise use a combination of event data
        if let Some(user) = &sentry_event.user {
            if let Some(id) = &user.id {
                return id.clone();
            }
            if let Some(email) = &user.email {
                return email.clone();
            }
        }
        // Fallback to event_id
        sentry_event.event_id.clone()
    });

    let exception_list = extract_exceptions(&sentry_event);
    let exception_level = convert_sentry_level(&sentry_event.level);
    let exception_fingerprint = generate_fingerprint(&exception_list, &sentry_event);

    let timestamp = sentry_event.timestamp.map(|ts| {
        let dt = DateTime::<Utc>::from_timestamp(ts as i64, 0)
            .unwrap_or_else(|| Utc::now());
        dt.to_rfc3339()
    });

    let mut properties = PostHogProperties {
        distinct_id,
        exception_list,
        exception_level,
        exception_fingerprint: Some(exception_fingerprint),
        exception_person_url: None,
        exception_dom_exception_code: None,
        current_url: extract_current_url(&sentry_event),
        os: extract_os_info(&sentry_event),
        browser: extract_browser_info(&sentry_event),
        device: extract_device_info(&sentry_event),
        lib: sentry_event.sdk.as_ref().and_then(|sdk| sdk.name.clone()),
        lib_version: sentry_event.sdk.as_ref().and_then(|sdk| sdk.version.clone()),
        sentry_event_id: Some(sentry_event.event_id.clone()),
        sentry_release: sentry_event.release.clone(),
        sentry_environment: sentry_event.environment.clone(),
        sentry_platform: sentry_event.platform.clone(),
        sentry_tags: sentry_event.tags.clone(),
        extra: HashMap::new(),
    };

    // Add extra data
    if let Some(extra) = sentry_event.extra {
        for (key, value) in extra {
            properties.extra.insert(format!("sentry_extra_{}", key), value);
        }
    }

    // Add transaction if present
    if let Some(transaction) = sentry_event.transaction {
        properties.extra.insert("sentry_transaction".to_string(), serde_json::Value::String(transaction));
    }

    // Add logger if present
    if let Some(logger) = sentry_event.logger {
        properties.extra.insert("sentry_logger".to_string(), serde_json::Value::String(logger));
    }

    PostHogEvent {
        api_key,
        event: "$exception".to_string(),
        properties,
        timestamp,
    }
}

fn extract_exceptions(sentry_event: &SentryEvent) -> Vec<PostHogException> {
    let mut exceptions = Vec::new();

    if let Some(exception_container) = &sentry_event.exception {
        if let Some(values) = &exception_container.values {
            for sentry_exc in values {
                exceptions.push(convert_exception(sentry_exc));
            }
        }
    }

    // If no exceptions but has a message, create synthetic exception
    if exceptions.is_empty() && sentry_event.message.is_some() {
        exceptions.push(PostHogException {
            exception_type: Some("Error".to_string()),
            value: sentry_event.message.clone(),
            module: None,
            thread_id: None,
            mechanism: Some(PostHogMechanism {
                handled: Some(true),
                mechanism_type: Some("generic".to_string()),
                source: None,
                synthetic: Some(true),
            }),
            stacktrace: None,
        });
    }

    exceptions
}

fn convert_exception(sentry_exc: &SentryException) -> PostHogException {
    PostHogException {
        exception_type: sentry_exc.exception_type.clone(),
        value: sentry_exc.value.clone(),
        module: sentry_exc.module.clone(),
        thread_id: sentry_exc.thread_id,
        mechanism: sentry_exc.mechanism.as_ref().map(|mech| PostHogMechanism {
            handled: mech.handled,
            mechanism_type: Some(mech.mechanism_type.clone()),
            source: mech.source.clone(),
            synthetic: mech.synthetic,
        }),
        stacktrace: sentry_exc.stacktrace.as_ref().map(convert_stacktrace),
    }
}

fn convert_stacktrace(sentry_stacktrace: &SentryStacktrace) -> PostHogStacktrace {
    PostHogStacktrace {
        frames: sentry_stacktrace.frames
            .as_ref()
            .map(|frames| frames.iter().map(convert_stack_frame).collect())
            .unwrap_or_default(),
        stacktrace_type: "raw".to_string(),
    }
}

fn convert_stack_frame(sentry_frame: &SentryStackFrame) -> PostHogStackFrame {
    PostHogStackFrame {
        platform: sentry_frame.platform.clone().unwrap_or_else(|| "custom".to_string()),
        filename: sentry_frame.filename.clone(),
        function: sentry_frame.function.clone().or_else(|| sentry_frame.raw_function.clone()),
        module: sentry_frame.module.clone(),
        lineno: sentry_frame.lineno,
        colno: sentry_frame.colno,
        abs_path: sentry_frame.abs_path.clone(),
        context_line: sentry_frame.context_line.clone(),
        pre_context: sentry_frame.pre_context.clone(),
        post_context: sentry_frame.post_context.clone(),
        in_app: sentry_frame.in_app,
        instruction_addr: sentry_frame.instruction_addr.clone(),
        addr_mode: sentry_frame.addr_mode.clone(),
        vars: sentry_frame.vars.clone(),
        chunk_id: None,
    }
}

fn convert_sentry_level(level: &Option<String>) -> Option<String> {
    level.as_ref().map(|l| match l.to_lowercase().as_str() {
        "fatal" | "critical" => "fatal",
        "error" => "error",
        "warning" | "warn" => "warning",
        "info" | "log" => "info",
        "debug" => "debug",
        _ => "info",
    }.to_string())
}

fn generate_fingerprint(exceptions: &[PostHogException], sentry_event: &SentryEvent) -> String {
    let mut hasher = Sha256::new();

    // Hash exception types and values
    for exc in exceptions {
        if let Some(exc_type) = &exc.exception_type {
            hasher.update(exc_type.as_bytes());
        }
        if let Some(value) = &exc.value {
            hasher.update(value.as_bytes());
        }
    }

    // Include platform
    if let Some(platform) = &sentry_event.platform {
        hasher.update(platform.as_bytes());
    }

    // Include release if available
    if let Some(release) = &sentry_event.release {
        hasher.update(release.as_bytes());
    }

    hex::encode(hasher.finalize())
}

fn extract_current_url(sentry_event: &SentryEvent) -> Option<String> {
    sentry_event.request.as_ref().and_then(|req| req.url.clone())
}

fn extract_os_info(sentry_event: &SentryEvent) -> Option<String> {
    sentry_event.contexts.as_ref()
        .and_then(|ctx| ctx.os.as_ref())
        .and_then(|os| {
            match (&os.name, &os.version) {
                (Some(name), Some(version)) => Some(format!("{} {}", name, version)),
                (Some(name), None) => Some(name.clone()),
                _ => None,
            }
        })
}

fn extract_browser_info(sentry_event: &SentryEvent) -> Option<String> {
    sentry_event.contexts.as_ref()
        .and_then(|ctx| ctx.browser.as_ref())
        .and_then(|browser| {
            browser.get("name")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        })
}

fn extract_device_info(sentry_event: &SentryEvent) -> Option<String> {
    sentry_event.contexts.as_ref()
        .and_then(|ctx| ctx.device.as_ref())
        .and_then(|device| {
            device.get("model")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        })
}
