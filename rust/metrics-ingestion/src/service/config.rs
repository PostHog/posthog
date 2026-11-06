//! Node settings keep their Node name, default and parse. `METRICS_RUST_SHADOW_MODE` is the only setting Node does not have.

use std::time::Duration;

use ingestion_framework::DLQ_OUTPUT;
use logs_ingestion::js::{JsObject, JsValue};
use logs_ingestion::pipeline::app_metrics::APP_METRICS_OUTPUT;
use logs_ingestion::service::config::{
    ConsumerLoopConfig, OutputRoute, RedisTarget, RunMode, UsageConfig, PRODUCER_KEYS,
    SHADOW_GROUP_SUFFIX, SHADOW_TOPIC_SUFFIX, WARPSTREAM_INGESTION_PRODUCER,
};
use logs_ingestion::service::node_env::{
    determine_node_env, get_bool, get_number, get_string, kafka_topic, override_with_env,
    rdkafka_from_env, Env, NodeEnv,
};

use crate::pipeline::{MetricsLimiterConfig, METRICS_OUTPUT};

pub const WARPSTREAM_METRICS_PRODUCER: &str = "WARPSTREAM_METRICS_PRODUCER";
pub const NODE_GROUP_ID: &str = "ingestion-metrics";
pub const PLUGIN_SERVER_MODE: &str = "ingestion-metrics";
pub const SHADOW_MODE_KEY: &str = "METRICS_RUST_SHADOW_MODE";
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(60);

#[derive(Debug, Clone)]
pub struct ServiceConfig {
    pub mode: RunMode,
    pub node_env: NodeEnv,
    pub node: JsObject,
    pub limiter: MetricsLimiterConfig,
    pub group_id: String,
    pub input_topic: String,
    pub routes: Vec<OutputRoute>,
    pub kafka_consumer: Vec<(String, String)>,
    pub producers: Vec<(String, Vec<(String, String)>)>,
    pub kafka_client_rack: Option<String>,
    pub consumer_loop: ConsumerLoopConfig,
    pub database_reader_url: String,
    /// `None` in shadow mode, which opens no write pool.
    pub database_writer_url: Option<String>,
    pub pool_size: u32,
    pub posthog_redis: RedisTarget,
    pub metrics_redis: RedisTarget,
    pub usage: UsageConfig,
    pub http_port: u16,
    pub shutdown_timeout: Duration,
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum ConfigError {
    #[error("PLUGIN_SERVER_MODE must be {PLUGIN_SERVER_MODE}, got {0:?}")]
    ServerMode(String),
    #[error("{SHADOW_MODE_KEY} must be true or false, got {0:?}")]
    ShadowMode(String),
    #[error("{0}")]
    Invalid(String),
}

fn s(v: &str) -> JsValue {
    JsValue::string(v)
}

fn n(v: f64) -> JsValue {
    JsValue::Number(v)
}

fn b(v: bool) -> JsValue {
    JsValue::Bool(v)
}

/// `getDefaultMetricsIngestionConsumerConfig`, the outputs and producer configs, and the `defaultConfig` keys the server reads.
fn node_defaults(env: &Env) -> Vec<(String, JsValue)> {
    let node_env = determine_node_env(env);
    let prod = node_env == NodeEnv::Production;
    let topic = |name: &str| s(&kafka_topic(env, name));
    let d: Vec<(&str, JsValue)> = vec![
        ("METRICS_INGESTION_CONSUMER_GROUP_ID", s(NODE_GROUP_ID)),
        (
            "METRICS_INGESTION_CONSUMER_CONSUME_TOPIC",
            topic("metrics_ingestion"),
        ),
        (
            "METRICS_INGESTION_CONSUMER_DLQ_TOPIC",
            topic("metrics_ingestion_dlq"),
        ),
        (
            "METRICS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC",
            topic("clickhouse_metrics"),
        ),
        ("METRICS_REDIS_HOST", s("127.0.0.1")),
        ("METRICS_REDIS_PORT", n(6379.0)),
        ("METRICS_REDIS_PASSWORD", s("")),
        ("METRICS_REDIS_TLS", b(prod)),
        (
            "METRICS_LIMITER_ENABLED_TEAMS",
            s(if prod { "" } else { "*" }),
        ),
        ("METRICS_LIMITER_DISABLED_FOR_TEAMS", s("")),
        ("METRICS_LIMITER_BUCKET_SIZE_KB", n(10000.0)),
        ("METRICS_LIMITER_REFILL_RATE_KB_PER_SECOND", n(1000.0)),
        ("METRICS_LIMITER_TTL_SECONDS", n(86400.0)),
        ("METRICS_LIMITER_TEAM_BUCKET_SIZE_KB", s("")),
        ("METRICS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND", s("")),
        ("REDIS_URL", s("redis://127.0.0.1")),
        (
            "METRICS_INGESTION_OUTPUT_APP_METRICS_TOPIC",
            topic("clickhouse_app_metrics2"),
        ),
        (
            "METRICS_INGESTION_OUTPUT_APP_METRICS_PRODUCER",
            s(WARPSTREAM_INGESTION_PRODUCER),
        ),
        (
            "METRICS_INGESTION_OUTPUT_METRICS_PRODUCER",
            s(WARPSTREAM_METRICS_PRODUCER),
        ),
        (
            "METRICS_INGESTION_OUTPUT_DLQ_PRODUCER",
            s(WARPSTREAM_METRICS_PRODUCER),
        ),
        (
            "DATABASE_URL",
            s(match node_env {
                NodeEnv::Test => "postgres://posthog:posthog@localhost:5432/test_posthog",
                NodeEnv::Development => "postgres://posthog:posthog@localhost:5432/posthog",
                NodeEnv::Production => "",
            }),
        ),
        ("DATABASE_READONLY_URL", s("")),
        ("POSTGRES_CONNECTION_POOL_SIZE", n(10.0)),
        ("POSTHOG_REDIS_HOST", s("")),
        ("POSTHOG_REDIS_PORT", n(6379.0)),
        ("POSTHOG_REDIS_PASSWORD", s("")),
        (
            "USAGE_INGESTION_ADDR",
            s(if node_env == NodeEnv::Development {
                "localhost:7143"
            } else {
                ""
            }),
        ),
        ("USAGE_INGESTION_TLS", b(false)),
        ("USAGE_INGESTION_TIMEOUT_MS", n(5000.0)),
        ("USAGE_INGESTION_MAX_BATCH_SIZE", n(500.0)),
        ("USAGE_INGESTION_REPORT_TEAMS", s("")),
        ("CONSUMER_BATCH_SIZE", n(500.0)),
        ("CONSUMER_MAX_BACKGROUND_TASKS", n(1.0)),
        ("CONSUMER_BACKGROUND_TASK_TIMEOUT_MS", n(60000.0)),
        ("HTTP_SERVER_PORT", n(6738.0)),
        ("KAFKA_CLIENT_RACK", s("")),
    ];
    let mut d: Vec<(String, JsValue)> = d.into_iter().map(|(k, v)| (k.to_string(), v)).collect();
    for prefix in [
        "KAFKA_WARPSTREAM_METRICS_PRODUCER_",
        "KAFKA_WARPSTREAM_INGESTION_PRODUCER_",
    ] {
        for (_, suffix) in PRODUCER_KEYS {
            d.push((format!("{prefix}{suffix}"), s("")));
        }
    }
    d
}

fn positive(config: &JsObject, key: &str) -> Result<f64, ConfigError> {
    let v = get_number(config, key);
    if v.is_finite() && v > 0.0 {
        Ok(v)
    } else {
        Err(ConfigError::Invalid(format!(
            "{key} must be a positive number"
        )))
    }
}

/// Unset or empty means shadow, so a copied Node deployment cannot start as primary by accident.
pub fn run_mode(env: &Env) -> Result<RunMode, ConfigError> {
    let raw = env.get(SHADOW_MODE_KEY).map(|v| v.trim()).unwrap_or("");
    match raw.to_lowercase().as_str() {
        "" | "y" | "yes" | "t" | "true" | "on" | "1" => Ok(RunMode::Shadow),
        "n" | "no" | "f" | "false" | "off" | "0" => Ok(RunMode::Primary),
        _ => Err(ConfigError::ShadowMode(raw.to_string())),
    }
}

impl ServiceConfig {
    pub fn from_env(env: &Env) -> Result<Self, ConfigError> {
        match env.get("PLUGIN_SERVER_MODE").map(String::as_str) {
            Some(PLUGIN_SERVER_MODE) => {}
            other => return Err(ConfigError::ServerMode(other.unwrap_or("").to_string())),
        }
        let mode = run_mode(env)?;
        let node_env = determine_node_env(env);
        let defaults = node_defaults(env);
        let defaults: Vec<(&str, JsValue)> = defaults
            .iter()
            .map(|(k, v)| (k.as_str(), v.clone()))
            .collect();
        let node = override_with_env(&defaults, env);
        let route = |output: &'static str, topic_key: &str, producer_key: &str| OutputRoute {
            output,
            topic: get_string(&node, topic_key),
            producer: get_string(&node, producer_key),
        };
        let production_routes = vec![
            route(
                METRICS_OUTPUT,
                "METRICS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC",
                "METRICS_INGESTION_OUTPUT_METRICS_PRODUCER",
            ),
            route(
                DLQ_OUTPUT,
                "METRICS_INGESTION_CONSUMER_DLQ_TOPIC",
                "METRICS_INGESTION_OUTPUT_DLQ_PRODUCER",
            ),
            route(
                APP_METRICS_OUTPUT,
                "METRICS_INGESTION_OUTPUT_APP_METRICS_TOPIC",
                "METRICS_INGESTION_OUTPUT_APP_METRICS_PRODUCER",
            ),
        ];
        let node_group = get_string(&node, "METRICS_INGESTION_CONSUMER_GROUP_ID");
        let (group_id, routes) = match mode {
            RunMode::Primary => (node_group, production_routes),
            RunMode::Shadow => (
                format!("{node_group}{SHADOW_GROUP_SUFFIX}"),
                production_routes
                    .into_iter()
                    .map(|r| OutputRoute {
                        topic: format!("{}{SHADOW_TOPIC_SUFFIX}", r.topic),
                        ..r
                    })
                    .collect(),
            ),
        };
        for route in &routes {
            if route.producer != WARPSTREAM_METRICS_PRODUCER
                && route.producer != WARPSTREAM_INGESTION_PRODUCER
            {
                return Err(ConfigError::Invalid(format!(
                    "unknown producer {:?} for output {}",
                    route.producer, route.output
                )));
            }
        }
        let producers = [
            (
                WARPSTREAM_METRICS_PRODUCER,
                "KAFKA_WARPSTREAM_METRICS_PRODUCER_",
            ),
            (
                WARPSTREAM_INGESTION_PRODUCER,
                "KAFKA_WARPSTREAM_INGESTION_PRODUCER_",
            ),
        ]
        .into_iter()
        .map(|(name, prefix)| {
            let values = PRODUCER_KEYS
                .iter()
                .filter_map(|(rdkafka, suffix)| {
                    let v = get_string(&node, &format!("{prefix}{suffix}"));
                    (!v.is_empty()).then(|| (rdkafka.to_string(), v))
                })
                .collect();
            (name.to_string(), values)
        })
        .collect();
        let redis_target =
            |host_key: &str, port_key: &str, tls_key: Option<&str>, password_key: Option<&str>| {
                let host = get_string(&node, host_key);
                if host.is_empty() {
                    RedisTarget {
                        url_or_host: get_string(&node, "REDIS_URL"),
                        port: None,
                        password: None,
                        tls: false,
                    }
                } else {
                    RedisTarget {
                        url_or_host: host,
                        port: Some(get_number(&node, port_key) as u16),
                        password: password_key
                            .map(|k| get_string(&node, k))
                            .filter(|p| !p.is_empty()),
                        tls: tls_key.is_some_and(|k| get_bool(&node, k)),
                    }
                }
            };
        // `createMetricsRateLimiterRedis` passes host, port and TLS. It ignores METRICS_REDIS_PASSWORD.
        let metrics_redis = redis_target(
            "METRICS_REDIS_HOST",
            "METRICS_REDIS_PORT",
            Some("METRICS_REDIS_TLS"),
            None,
        );
        let posthog_redis = redis_target(
            "POSTHOG_REDIS_HOST",
            "POSTHOG_REDIS_PORT",
            None,
            Some("POSTHOG_REDIS_PASSWORD"),
        );
        let database_url = get_string(&node, "DATABASE_URL").trim().to_string();
        let readonly_url = get_string(&node, "DATABASE_READONLY_URL")
            .trim()
            .to_string();
        if database_url.is_empty() && readonly_url.is_empty() {
            return Err(ConfigError::Invalid("DATABASE_URL is required".to_string()));
        }
        let database_reader_url = if readonly_url.is_empty() {
            database_url.clone()
        } else {
            readonly_url
        };
        let database_writer_url = match mode {
            RunMode::Primary if database_url.is_empty() => {
                return Err(ConfigError::Invalid("DATABASE_URL is required".to_string()))
            }
            RunMode::Primary => Some(database_url),
            RunMode::Shadow => None,
        };
        let rack = get_string(&node, "KAFKA_CLIENT_RACK");
        Ok(Self {
            mode,
            node_env,
            limiter: MetricsLimiterConfig::from_node_config(&node),
            group_id,
            input_topic: get_string(&node, "METRICS_INGESTION_CONSUMER_CONSUME_TOPIC"),
            routes,
            kafka_consumer: rdkafka_from_env(env, "KAFKA_CONSUMER_", &[]),
            producers,
            kafka_client_rack: (!rack.is_empty()).then_some(rack),
            consumer_loop: ConsumerLoopConfig {
                batch_size: positive(&node, "CONSUMER_BATCH_SIZE")? as usize,
                batch_timeout: Duration::from_millis(500),
                max_background_tasks: positive(&node, "CONSUMER_MAX_BACKGROUND_TASKS")? as usize,
                background_task_timeout: Duration::from_millis(positive(
                    &node,
                    "CONSUMER_BACKGROUND_TASK_TIMEOUT_MS",
                )? as u64),
            },
            database_reader_url,
            database_writer_url,
            pool_size: positive(&node, "POSTGRES_CONNECTION_POOL_SIZE")? as u32,
            posthog_redis,
            metrics_redis,
            usage: UsageConfig {
                addr: get_string(&node, "USAGE_INGESTION_ADDR"),
                tls: get_bool(&node, "USAGE_INGESTION_TLS"),
                timeout: Duration::from_millis(
                    positive(&node, "USAGE_INGESTION_TIMEOUT_MS")? as u64
                ),
                max_batch_size: positive(&node, "USAGE_INGESTION_MAX_BATCH_SIZE")? as usize,
                report_teams: get_string(&node, "USAGE_INGESTION_REPORT_TEAMS"),
            },
            http_port: positive(&node, "HTTP_SERVER_PORT")? as u16,
            shutdown_timeout: SHUTDOWN_TIMEOUT,
            node,
        })
    }

    pub fn route(&self, output: &str) -> Option<&OutputRoute> {
        self.routes.iter().find(|r| r.output == output)
    }
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

    fn routes(c: &ServiceConfig) -> Vec<(&str, &str, &str)> {
        c.routes
            .iter()
            .map(|r| (r.output, r.topic.as_str(), r.producer.as_str()))
            .collect()
    }

    #[test]
    fn a_node_env_runs_as_a_shadow_with_suffixed_group_and_outputs() {
        let c = ServiceConfig::from_env(&env(&[
            ("PLUGIN_SERVER_MODE", "ingestion-metrics"),
            ("DATABASE_URL", "postgres://x"),
            (
                "METRICS_INGESTION_OUTPUT_APP_METRICS_TOPIC",
                "custom_app_metrics",
            ),
        ]))
        .unwrap();
        assert_eq!(c.mode, RunMode::Shadow);
        assert_eq!(c.group_id, "ingestion-metrics-rust-shadow");
        assert_eq!(c.input_topic, "metrics_ingestion");
        assert_eq!(
            routes(&c),
            vec![
                (
                    "metrics",
                    "clickhouse_metrics_rust_shadow",
                    WARPSTREAM_METRICS_PRODUCER
                ),
                (
                    "dlq",
                    "metrics_ingestion_dlq_rust_shadow",
                    WARPSTREAM_METRICS_PRODUCER
                ),
                (
                    "app_metrics",
                    "custom_app_metrics_rust_shadow",
                    WARPSTREAM_INGESTION_PRODUCER
                ),
            ]
        );
        assert_eq!(c.database_writer_url, None);
    }

    #[test]
    fn primary_mode_keeps_node_names_and_production_defaults() {
        let c = ServiceConfig::from_env(&env(&[
            ("PLUGIN_SERVER_MODE", "ingestion-metrics"),
            (SHADOW_MODE_KEY, "false"),
            ("DATABASE_URL", "postgres://x"),
            ("METRICS_REDIS_HOST", "metrics-redis"),
            ("METRICS_LIMITER_BUCKET_SIZE_KB", "2.5"),
        ]))
        .unwrap();
        assert_eq!(c.group_id, NODE_GROUP_ID);
        assert_eq!(c.route("metrics").unwrap().topic, "clickhouse_metrics");
        assert_eq!(c.limiter.bucket_size_kb, 2.5);
        assert_eq!(c.limiter.enabled_teams, "");
        assert!(c.metrics_redis.tls);
        assert_eq!(c.database_writer_url.as_deref(), Some("postgres://x"));
        assert_eq!(
            run_mode(&env(&[(SHADOW_MODE_KEY, "fals")])),
            Err(ConfigError::ShadowMode("fals".into()))
        );
        assert_eq!(
            ServiceConfig::from_env(&env(&[("PLUGIN_SERVER_MODE", "ingestion-logs")])).unwrap_err(),
            ConfigError::ServerMode("ingestion-logs".into())
        );
    }
}
