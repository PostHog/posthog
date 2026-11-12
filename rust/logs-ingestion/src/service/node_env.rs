use std::collections::HashMap;

use crate::js::{JsObject, JsString, JsValue};
use crate::metric_rules::js_parse_float;
use crate::property_filter::coerce::js_parse_int;

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

/// The default's type picks the parse.
pub fn override_with_env(defaults: &[(&str, JsValue)], env: &Env) -> JsObject {
    let mut out = JsObject::new();
    for (key, default) in defaults {
        let value = match env.get(*key) {
            None => default.clone(),
            Some(raw) => match default {
                // `indexOf('.')` is 0 only for a leading dot, which takes `parseInt`.
                JsValue::Number(_) if raw.starts_with('.') => {
                    JsValue::Number(js_parse_int(raw, None))
                }
                JsValue::Number(_) => JsValue::Number(js_parse_float(&JsString::from(raw.clone()))),
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
        let o = override_with_env(&defaults, &env(&[("N", ".5")]));
        assert!(matches!(o.get("N"), Some(JsValue::Number(n)) if n.is_nan()));
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
