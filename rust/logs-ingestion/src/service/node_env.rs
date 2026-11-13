use std::collections::HashMap;

use crate::js::{JsObject, JsString, JsValue};
use crate::metric_rules::js_parse_float;
use crate::property_filter::coerce::js_trim;

pub type Env = HashMap<String, String>;

pub fn process_env() -> Env {
    std::env::vars().collect()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NodeEnv {
    Development,
    Production,
    Test,
}

pub fn string_to_boolean(value: &str) -> bool {
    matches!(
        value.to_lowercase().as_str(),
        "y" | "yes" | "t" | "true" | "on" | "1"
    )
}

pub fn determine_node_env(env: &Env) -> NodeEnv {
    if let Some(raw) = env.get("NODE_ENV").filter(|v| !v.is_empty()) {
        let raw = raw.to_lowercase();
        if raw.starts_with("test") {
            return NodeEnv::Test;
        }
        if raw.starts_with("dev") {
            return NodeEnv::Development;
        }
    }
    if env.get("DEBUG").is_some_and(|v| string_to_boolean(v)) {
        return NodeEnv::Development;
    }
    NodeEnv::Production
}

pub fn kafka_topic(env: &Env, name: &str) -> String {
    let prefix = env.get("KAFKA_PREFIX").map(String::as_str).unwrap_or("");
    let suffix = if determine_node_env(env) == NodeEnv::Test {
        "_test"
    } else {
        ""
    };
    format!("{prefix}{name}{suffix}")
}

/// `parseNumberFromEnv`: trim, drop one pair of matching quotes, then `parseFloat`. `None` keeps the default.
fn parse_number_from_env(raw: &str) -> Option<f64> {
    let trimmed = js_trim(raw);
    let mut chars = trimmed.chars();
    let quoted = match (chars.next(), chars.next_back()) {
        // `.` does not match a line terminator, so a quoted value that spans lines keeps its quotes.
        (Some(open @ ('"' | '\'')), Some(close)) if open == close => Some(chars.as_str())
            .filter(|inner| !inner.contains(['\n', '\r', '\u{2028}', '\u{2029}'])),
        _ => None,
    };
    let unquoted = js_trim(quoted.unwrap_or(trimmed));
    if unquoted.is_empty() {
        // `parseFloat('')` is NaN too. Node spells this case out for a value that was only quotes.
        return None;
    }
    let value = js_parse_float(&JsString::from(unquoted.to_string()));
    (!value.is_nan()).then_some(value)
}

/// The default's type picks the parse.
pub fn override_with_env(defaults: &[(&str, JsValue)], env: &Env) -> JsObject {
    let mut out = JsObject::new();
    for (key, default) in defaults {
        let value = match env.get(*key) {
            None => default.clone(),
            Some(raw) => match default {
                JsValue::Number(_) => match parse_number_from_env(raw) {
                    Some(number) => JsValue::Number(number),
                    None => {
                        tracing::error!(
                            key,
                            "Ignoring {key}: its env value is not a number, keeping the default"
                        );
                        default.clone()
                    }
                },
                JsValue::Bool(_) => JsValue::Bool(string_to_boolean(raw)),
                _ => JsValue::string(raw),
            },
        };
        out.insert_str(key, value);
    }
    out
}

/// Empty values are skipped. `skip` lists Node `defaultConfig` keys that the prefix also matches.
pub fn rdkafka_from_env(env: &Env, prefix: &str, skip: &[&str]) -> Vec<(String, String)> {
    let mut out: Vec<(String, String)> = env
        .iter()
        .filter(|(k, v)| k.starts_with(prefix) && !v.is_empty() && !skip.contains(&k.as_str()))
        .map(|(k, v)| {
            let key = k[prefix.len()..].to_lowercase().replace('_', ".");
            let value = match v.to_lowercase().as_str() {
                "true" => "true".to_string(),
                "false" => "false".to_string(),
                _ => v.clone(),
            };
            (key, value)
        })
        .collect();
    out.sort();
    out
}

pub fn get_string(config: &JsObject, key: &str) -> String {
    match config.get(key) {
        Some(JsValue::String(s)) => s.to_utf8_lossy().into_owned(),
        Some(JsValue::Number(n)) => crate::js::number_to_string(*n),
        Some(JsValue::Bool(b)) => b.to_string(),
        _ => String::new(),
    }
}

pub fn get_number(config: &JsObject, key: &str) -> f64 {
    match config.get(key) {
        Some(JsValue::Number(n)) => *n,
        _ => f64::NAN,
    }
}

pub fn get_bool(config: &JsObject, key: &str) -> bool {
    matches!(config.get(key), Some(JsValue::Bool(true)))
}

/// The `getDefaultCommonConfig` keys that `buildPosthogDatabaseUrl` reads besides `DATABASE_URL`.
pub fn posthog_database_defaults() -> Vec<(&'static str, JsValue)> {
    vec![
        ("POSTHOG_DB_NAME", JsValue::Null),
        ("POSTHOG_DB_USER", JsValue::string("postgres")),
        ("POSTHOG_DB_PASSWORD", JsValue::string("")),
        ("POSTHOG_POSTGRES_HOST", JsValue::string("localhost")),
        ("POSTHOG_POSTGRES_PORT", JsValue::Number(5432.0)),
    ]
}

/// `encodeURIComponent` for a well-formed string.
fn encode_uri_component(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || b"-_.!~*'()".contains(&byte) {
            out.push(byte as char);
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    out
}

/// `buildPosthogDatabaseUrl` as `overrideWithEnv` applies it. Empty when neither `DATABASE_URL` nor `POSTHOG_DB_NAME` is set.
pub fn posthog_database_url(config: &JsObject) -> String {
    let url = get_string(config, "DATABASE_URL");
    let name = get_string(config, "POSTHOG_DB_NAME");
    if !url.is_empty() || name.is_empty() {
        return url;
    }
    format!(
        "postgres://{}:{}@{}:{}/{name}",
        encode_uri_component(&get_string(config, "POSTHOG_DB_USER")),
        encode_uri_component(&get_string(config, "POSTHOG_DB_PASSWORD")),
        get_string(config, "POSTHOG_POSTGRES_HOST"),
        get_string(config, "POSTHOG_POSTGRES_PORT"),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env(pairs: &[(&str, &str)]) -> Env {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn env_overrides_parse_like_override_config_with_env() {
        let defaults = [
            ("N", JsValue::Number(1.0)),
            ("B", JsValue::Bool(false)),
            ("S", JsValue::string("x")),
            ("D", JsValue::Number(2.0)),
        ];
        let o = override_with_env(&defaults, &env(&[("N", "12.5kb"), ("B", "on"), ("S", "")]));
        assert_eq!(o.get("N"), Some(&JsValue::Number(12.5)));
        assert_eq!(o.get("B"), Some(&JsValue::Bool(true)));
        assert_eq!(o.get("S"), Some(&JsValue::string("")));
        assert_eq!(o.get("D"), Some(&JsValue::Number(2.0)));
        for (raw, expected) in [
            (".5", 0.5),
            (" \"500\" ", 500.0),
            ("'7'", 7.0),
            // An unparsable value keeps the default.
            ("", 1.0),
            ("abc", 1.0),
            ("\"\"", 1.0),
            ("\"5'", 1.0),
        ] {
            let o = override_with_env(&defaults, &env(&[("N", raw)]));
            assert_eq!(o.get("N"), Some(&JsValue::Number(expected)), "{raw:?}");
        }
    }

    #[test]
    fn database_url_falls_back_to_the_posthog_db_options() {
        let mut defaults = posthog_database_defaults();
        defaults.push(("DATABASE_URL", JsValue::string("")));
        let url = |pairs: &[(&str, &str)]| {
            posthog_database_url(&override_with_env(&defaults, &env(pairs)))
        };
        assert_eq!(url(&[]), "");
        assert_eq!(
            url(&[
                ("POSTHOG_DB_NAME", "posthog"),
                ("POSTHOG_DB_PASSWORD", "p@ss/w:rd!")
            ]),
            "postgres://postgres:p%40ss%2Fw%3Ard!@localhost:5432/posthog"
        );
        assert_eq!(
            url(&[
                ("POSTHOG_DB_NAME", "posthog"),
                ("DATABASE_URL", "postgres://set")
            ]),
            "postgres://set"
        );
    }

    #[test]
    fn topic_names_follow_prefix_and_test_suffix() {
        assert_eq!(kafka_topic(&env(&[]), "clickhouse_logs"), "clickhouse_logs");
        assert_eq!(
            kafka_topic(&env(&[("NODE_ENV", "test"), ("KAFKA_PREFIX", "p_")]), "x"),
            "p_x_test"
        );
        assert_eq!(
            determine_node_env(&env(&[("DEBUG", "1")])),
            NodeEnv::Development
        );
    }
}
