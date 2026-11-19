//! Node settings keep their Node name, default and parse. `LOGS_RUST_SHADOW_MODE` is the only setting Node does not have.

use std::time::Duration;

use crate::js::{JsObject, JsValue};
use crate::pipeline::LogsIngestionConsumerConfig;

use super::node_env::{
    determine_node_env, get_bool, get_number, get_string, kafka_topic, override_with_env,
    rdkafka_from_env, Env, NodeEnv,
};

pub const WARPSTREAM_LOGS_PRODUCER: &str = "WARPSTREAM_LOGS_PRODUCER";
pub const WARPSTREAM_INGESTION_PRODUCER: &str = "WARPSTREAM_INGESTION_PRODUCER";
pub const NODE_LOGS_GROUP_ID: &str = "ingestion-logs";
pub const NODE_TRACES_GROUP_ID: &str = "ingestion-traces";
pub const SHADOW_TOPIC_SUFFIX: &str = "_rust_shadow";
pub const SHADOW_GROUP_SUFFIX: &str = "-rust-shadow";
/// Node's `defaultConfig` has no `KAFKA_CONSUMER_*` key, so `skipKeysInDefaultConfig` skips none.
pub const NODE_DEFAULT_CONFIG_CONSUMER_KEYS: &[&str] = &[];
pub const SHADOW_MODE_KEY: &str = "LOGS_RUST_SHADOW_MODE";
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(60);

const PRODUCER_KEYS: &[(&str, &str)] = &[
    ("client.id", "CLIENT_ID"),
    ("metadata.broker.list", "METADATA_BROKER_LIST"),
    ("security.protocol", "SECURITY_PROTOCOL"),
    ("sasl.mechanisms", "SASL_MECHANISMS"),
    ("sasl.username", "SASL_USERNAME"),
    ("sasl.password", "SASL_PASSWORD"),
    ("compression.codec", "COMPRESSION_CODEC"),
    ("linger.ms", "LINGER_MS"),
    ("batch.size", "BATCH_SIZE"),
    (
        "queue.buffering.max.messages",
        "QUEUE_BUFFERING_MAX_MESSAGES",
    ),
    ("queue.buffering.max.kbytes", "QUEUE_BUFFERING_MAX_KBYTES"),
    (
        "enable.ssl.certificate.verification",
        "ENABLE_SSL_CERTIFICATE_VERIFICATION",
    ),
    ("enable.idempotence", "ENABLE_IDEMPOTENCE"),
    ("message.max.bytes", "MESSAGE_MAX_BYTES"),
    ("batch.num.messages", "BATCH_NUM_MESSAGES"),
    (
        "sticky.partitioning.linger.ms",
        "STICKY_PARTITIONING_LINGER_MS",
    ),
    (
        "topic.metadata.refresh.interval.ms",
        "TOPIC_METADATA_REFRESH_INTERVAL_MS",
    ),
    ("metadata.max.age.ms", "METADATA_MAX_AGE_MS"),
    ("message.send.max.retries", "RETRIES"),
    (
        "max.in.flight.requests.per.connection",
        "MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION",
    ),
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConsumerKind {
    Logs,
    Traces,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunMode {
    Primary,
    Shadow,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OutputRoute {
    pub output: &'static str,
    pub topic: String,
    pub producer: String,
}

#[derive(Debug, Clone)]
pub struct RedisTarget {
    pub url_or_host: String,
    pub port: Option<u16>,
    pub password: Option<String>,
    pub tls: bool,
}

#[derive(Debug, Clone)]
pub struct UsageConfig {
    pub addr: String,
    pub tls: bool,
    pub timeout: Duration,
    pub max_batch_size: usize,
    pub report_teams: String,
}

#[derive(Debug, Clone)]
pub struct ConsumerLoopConfig {
    pub batch_size: usize,
    pub batch_timeout: Duration,
    pub max_background_tasks: usize,
    pub background_task_timeout: Duration,
}

#[derive(Debug, Clone)]
pub struct ServiceConfig {
    pub kind: ConsumerKind,
    pub mode: RunMode,
    pub node_env: NodeEnv,
    pub node: JsObject,
    pub consumer: LogsIngestionConsumerConfig,
    pub group_id: String,
    pub input_topic: String,
    pub routes: Vec<OutputRoute>,
    pub metrics_export_url: String,
    pub kafka_consumer: Vec<(String, String)>,
    pub producers: Vec<(String, Vec<(String, String)>)>,
    pub kafka_client_rack: Option<String>,
    pub consumer_loop: ConsumerLoopConfig,
    pub database_reader_url: String,
    /// `None` in shadow mode, which opens no write pool.
    pub database_writer_url: Option<String>,
    pub pool_size: u32,
    pub posthog_redis: RedisTarget,
    pub logs_redis: RedisTarget,
    pub usage: UsageConfig,
    pub http_port: u16,
    pub shutdown_timeout: Duration,
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum ConfigError {
    #[error("PLUGIN_SERVER_MODE must be ingestion-logs or ingestion-traces, got {0:?}")]
    ConsumerKind(String),
    #[error("{SHADOW_MODE_KEY} must be true or false, got {0:?}")]
    ShadowMode(String),
    #[error(
        "{0} is not empty, but hog transformations are not ported, so primary mode refuses it"
    )]
    TransformationsNotPorted(&'static str),
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

fn node_defaults(env: &Env) -> Vec<(String, JsValue)> {
    let node_env = determine_node_env(env);
    let prod = node_env == NodeEnv::Production;
    let off_in_prod = |_: ()| s(if prod { "" } else { "*" });
    let topic = |name: &str| s(&kafka_topic(env, name));
    let d: Vec<(&str, JsValue)> = vec![
        ("LOGS_INGESTION_CONSUMER_GROUP_ID", s(NODE_LOGS_GROUP_ID)),
        (
            "LOGS_INGESTION_CONSUMER_CONSUME_TOPIC",
            topic("logs_ingestion"),
        ),
        (
            "LOGS_INGESTION_CONSUMER_OVERFLOW_TOPIC",
            topic("logs_ingestion_overflow"),
        ),
        (
            "LOGS_INGESTION_CONSUMER_DLQ_TOPIC",
            topic("logs_ingestion_dlq"),
        ),
        (
            "LOGS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC",
            topic("clickhouse_logs"),
        ),
        ("LOGS_REDIS_HOST", s("127.0.0.1")),
        ("LOGS_REDIS_PORT", n(6379.0)),
        ("LOGS_REDIS_PASSWORD", s("")),
        ("LOGS_REDIS_TLS", b(prod)),
        ("LOGS_LIMITER_ENABLED_TEAMS", off_in_prod(())),
        ("LOGS_LIMITER_DISABLED_FOR_TEAMS", s("")),
        ("LOGS_LIMITER_BUCKET_SIZE_KB", n(10000.0)),
        ("LOGS_LIMITER_REFILL_RATE_KB_PER_SECOND", n(1000.0)),
        ("LOGS_LIMITER_TTL_SECONDS", n(86400.0)),
        ("LOGS_LIMITER_TEAM_BUCKET_SIZE_KB", s("")),
        ("LOGS_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND", s("")),
        ("LOGS_SAMPLING_ENABLED_TEAMS", s("*")),
        ("LOGS_SAMPLING_KILLSWITCH", b(false)),
        ("LOGS_METRICS_RULES_ENABLED_TEAMS", off_in_prod(())),
        ("LOGS_METRICS_RULES_KILLSWITCH", b(false)),
        ("LOGS_METRICS_RULES_EXPORT_URL", s("")),
        ("LOGS_DEFAULT_METRIC_RULES_ENABLED_TEAMS", s("")),
        ("LOGS_RETENTION_ENABLED_TEAMS", off_in_prod(())),
        ("LOGS_BACKFILL_ENABLED_TEAMS", off_in_prod(())),
        ("LOGS_RETENTION_KILLSWITCH", b(false)),
        ("LOGS_INTERNAL_INGESTION_ENABLED_TEAMS", s("")),
        ("LOGS_INTERNAL_INGESTION_SIGNING_KEYS", s("")),
        ("LOGS_PATTERN_MASKING_ENABLED_TEAMS", s("")),
        ("LOGS_JSON_ATTRIBUTE_PARSING_ENABLED_TEAMS", s("")),
        ("LOGS_JSON_ATTRIBUTE_EXTRACTION_ENABLED_TEAMS", s("")),
        ("LOGS_BILLING_PRORATE_ENABLED", b(false)),
        ("LOGS_TRANSFORMATIONS_ENABLED_TEAMS", s("")),
        ("LOGS_TRANSFORMATIONS_KILLSWITCH", b(false)),
        ("REDIS_URL", s("redis://127.0.0.1")),
        (
            "TRACES_INGESTION_CONSUMER_GROUP_ID",
            s(NODE_TRACES_GROUP_ID),
        ),
        (
            "TRACES_INGESTION_CONSUMER_CONSUME_TOPIC",
            topic("ingestion-traces"),
        ),
        (
            "TRACES_INGESTION_CONSUMER_OVERFLOW_TOPIC",
            topic("ingestion-traces-overflow"),
        ),
        (
            "TRACES_INGESTION_CONSUMER_DLQ_TOPIC",
            topic("ingestion-traces-dlq"),
        ),
        (
            "TRACES_INGESTION_CONSUMER_CLICKHOUSE_TOPIC",
            topic("clickhouse_traces"),
        ),
        ("TRACES_REDIS_HOST", s("127.0.0.1")),
        ("TRACES_REDIS_PORT", n(6379.0)),
        ("TRACES_REDIS_PASSWORD", s("")),
        ("TRACES_REDIS_TLS", b(prod)),
        ("TRACES_LIMITER_ENABLED_TEAMS", off_in_prod(())),
        ("TRACES_LIMITER_DISABLED_FOR_TEAMS", s("")),
        ("TRACES_LIMITER_BUCKET_SIZE_KB", n(10000.0)),
        ("TRACES_LIMITER_REFILL_RATE_KB_PER_SECOND", n(1000.0)),
        ("TRACES_LIMITER_TTL_SECONDS", n(86400.0)),
        ("TRACES_LIMITER_TEAM_BUCKET_SIZE_KB", s("")),
        ("TRACES_LIMITER_TEAM_REFILL_RATE_KB_PER_SECOND", s("")),
        ("TRACES_METRICS_RULES_ENABLED_TEAMS", off_in_prod(())),
        ("TRACES_METRICS_RULES_KILLSWITCH", b(false)),
        ("TRACES_METRICS_RULES_EXPORT_URL", s("")),
        ("TRACES_DEFAULT_METRIC_RULES_ENABLED_TEAMS", s("")),
        ("TRACES_RETENTION_ENABLED_TEAMS", off_in_prod(())),
        ("TRACES_RETENTION_KILLSWITCH", b(false)),
        (
            "LOGS_INGESTION_OUTPUT_APP_METRICS_TOPIC",
            topic("clickhouse_app_metrics2"),
        ),
        (
            "LOGS_INGESTION_OUTPUT_APP_METRICS_PRODUCER",
            s(WARPSTREAM_INGESTION_PRODUCER),
        ),
        (
            "LOGS_INGESTION_OUTPUT_LOG_ENTRIES_TOPIC",
            topic("log_entries"),
        ),
        (
            "LOGS_INGESTION_OUTPUT_LOG_ENTRIES_PRODUCER",
            s(WARPSTREAM_INGESTION_PRODUCER),
        ),
        (
            "LOGS_INGESTION_OUTPUT_LOGS_PRODUCER",
            s(WARPSTREAM_LOGS_PRODUCER),
        ),
        (
            "LOGS_INGESTION_OUTPUT_DLQ_PRODUCER",
            s(WARPSTREAM_LOGS_PRODUCER),
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
        "KAFKA_WARPSTREAM_LOGS_PRODUCER_",
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

fn shadow_route(route: OutputRoute) -> OutputRoute {
    OutputRoute {
        topic: format!("{}{SHADOW_TOPIC_SUFFIX}", route.topic),
        ..route
    }
}

impl ServiceConfig {
    pub fn from_env(env: &Env) -> Result<Self, ConfigError> {
        let kind = match env.get("PLUGIN_SERVER_MODE").map(String::as_str) {
            Some("ingestion-logs") => ConsumerKind::Logs,
            Some("ingestion-traces") => ConsumerKind::Traces,
            other => return Err(ConfigError::ConsumerKind(other.unwrap_or("").to_string())),
        };
        let mode = run_mode(env)?;
        let node_env = determine_node_env(env);
        let defaults = node_defaults(env);
        let defaults: Vec<(&str, JsValue)> = defaults
            .iter()
            .map(|(k, v)| (k.as_str(), v.clone()))
            .collect();
        let node = override_with_env(&defaults, env);
        let p = match kind {
            ConsumerKind::Logs => "LOGS",
            ConsumerKind::Traces => "TRACES",
        };
        let consumer = match kind {
            ConsumerKind::Logs => LogsIngestionConsumerConfig::from_logs_config(&node),
            ConsumerKind::Traces => LogsIngestionConsumerConfig::from_traces_config(&node),
        };
        // The traces consumer extends the logs one in Node and reads this same key.
        if mode == RunMode::Primary && !consumer.transformations_enabled_teams.trim().is_empty() {
            return Err(ConfigError::TransformationsNotPorted(
                "LOGS_TRANSFORMATIONS_ENABLED_TEAMS",
            ));
        }
        let input_topic = get_string(&node, &format!("{p}_INGESTION_CONSUMER_CONSUME_TOPIC"));
        let production_routes = vec![
            OutputRoute {
                output: crate::pipeline::LOGS_OUTPUT,
                topic: get_string(&node, &format!("{p}_INGESTION_CONSUMER_CLICKHOUSE_TOPIC")),
                producer: get_string(&node, "LOGS_INGESTION_OUTPUT_LOGS_PRODUCER"),
            },
            OutputRoute {
                output: crate::pipeline::LOGS_DLQ_OUTPUT,
                topic: get_string(&node, &format!("{p}_INGESTION_CONSUMER_DLQ_TOPIC")),
                producer: get_string(&node, "LOGS_INGESTION_OUTPUT_DLQ_PRODUCER"),
            },
            OutputRoute {
                output: crate::pipeline::app_metrics::APP_METRICS_OUTPUT,
                topic: get_string(&node, "LOGS_INGESTION_OUTPUT_APP_METRICS_TOPIC"),
                producer: get_string(&node, "LOGS_INGESTION_OUTPUT_APP_METRICS_PRODUCER"),
            },
        ];
        let node_group = get_string(&node, &format!("{p}_INGESTION_CONSUMER_GROUP_ID"));
        let (group_id, routes) = match mode {
            RunMode::Primary => (node_group, production_routes),
            RunMode::Shadow => (
                format!("{node_group}{SHADOW_GROUP_SUFFIX}"),
                production_routes.into_iter().map(shadow_route).collect(),
            ),
        };
        for route in &routes {
            if route.producer != WARPSTREAM_LOGS_PRODUCER
                && route.producer != WARPSTREAM_INGESTION_PRODUCER
            {
                return Err(ConfigError::Invalid(format!(
                    "unknown producer {:?} for output {}",
                    route.producer, route.output
                )));
            }
        }
        let mut producers = Vec::new();
        for (name, prefix) in [
            (WARPSTREAM_LOGS_PRODUCER, "KAFKA_WARPSTREAM_LOGS_PRODUCER_"),
            (
                WARPSTREAM_INGESTION_PRODUCER,
                "KAFKA_WARPSTREAM_INGESTION_PRODUCER_",
            ),
        ] {
            let values = PRODUCER_KEYS
                .iter()
                .filter_map(|(rdkafka, suffix)| {
                    let v = get_string(&node, &format!("{prefix}{suffix}"));
                    (!v.is_empty()).then(|| (rdkafka.to_string(), v))
                })
                .collect();
            producers.push((name.to_string(), values));
        }
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
        // Node passes no password for the logs Redis, only host, port and TLS. The shadow keeps its buckets under its own key root there.
        let logs_redis = redis_target(
            &format!("{p}_REDIS_HOST"),
            &format!("{p}_REDIS_PORT"),
            Some(&format!("{p}_REDIS_TLS")),
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
        let usage = UsageConfig {
            addr: get_string(&node, "USAGE_INGESTION_ADDR"),
            tls: get_bool(&node, "USAGE_INGESTION_TLS"),
            timeout: Duration::from_millis(positive(&node, "USAGE_INGESTION_TIMEOUT_MS")? as u64),
            max_batch_size: positive(&node, "USAGE_INGESTION_MAX_BATCH_SIZE")? as usize,
            report_teams: get_string(&node, "USAGE_INGESTION_REPORT_TEAMS"),
        };
        let rack = get_string(&node, "KAFKA_CLIENT_RACK");
        Ok(Self {
            kind,
            mode,
            node_env,
            metrics_export_url: get_string(&node, &format!("{p}_METRICS_RULES_EXPORT_URL")),
            kafka_consumer: rdkafka_from_env(
                env,
                "KAFKA_CONSUMER_",
                NODE_DEFAULT_CONFIG_CONSUMER_KEYS,
            ),
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
            usage,
            http_port: positive(&node, "HTTP_SERVER_PORT")? as u16,
            kafka_client_rack: (!rack.is_empty()).then_some(rack),
            shutdown_timeout: SHUTDOWN_TIMEOUT,
            group_id,
            input_topic,
            routes,
            producers,
            logs_redis,
            posthog_redis,
            consumer,
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

    fn node_env(extra: &[(&str, &str)]) -> Env {
        let mut e = env(&[
            ("PLUGIN_SERVER_MODE", "ingestion-logs"),
            ("DATABASE_URL", "postgres://x"),
            ("LOGS_REDIS_HOST", "logs-redis"),
        ]);
        e.extend(extra.iter().map(|(k, v)| (k.to_string(), v.to_string())));
        e
    }

    fn topics(c: &ServiceConfig) -> Vec<(&str, &str, &str)> {
        c.routes
            .iter()
            .map(|r| (r.output, r.topic.as_str(), r.producer.as_str()))
            .collect()
    }

    #[test]
    fn a_node_env_runs_as_a_shadow_with_suffixed_group_and_outputs() {
        let c = ServiceConfig::from_env(&node_env(&[
            ("LOGS_INGESTION_CONSUMER_GROUP_ID", "custom-group"),
            ("LOGS_INGESTION_OUTPUT_APP_METRICS_TOPIC", "custom_metrics"),
        ]))
        .unwrap();
        assert_eq!(c.mode, RunMode::Shadow);
        assert_eq!(c.group_id, "custom-group-rust-shadow");
        assert_eq!(c.input_topic, "logs_ingestion");
        assert_eq!(
            topics(&c),
            vec![
                (
                    "logs",
                    "clickhouse_logs_rust_shadow",
                    WARPSTREAM_LOGS_PRODUCER
                ),
                (
                    "logs_dlq",
                    "logs_ingestion_dlq_rust_shadow",
                    WARPSTREAM_LOGS_PRODUCER
                ),
                (
                    "app_metrics",
                    "custom_metrics_rust_shadow",
                    WARPSTREAM_INGESTION_PRODUCER
                ),
            ]
        );
        assert_eq!(c.logs_redis.url_or_host, "logs-redis");
        assert_eq!(c.database_reader_url, "postgres://x");
        assert_eq!(c.database_writer_url, None);

        let replica = ServiceConfig::from_env(&node_env(&[(
            "DATABASE_READONLY_URL",
            "postgres://replica",
        )]))
        .unwrap();
        assert_eq!(replica.database_reader_url, "postgres://replica");
    }

    #[test]
    fn only_an_explicit_false_selects_primary() {
        for (value, expected) in [
            ("", Ok(RunMode::Shadow)),
            ("true", Ok(RunMode::Shadow)),
            (" TRUE ", Ok(RunMode::Shadow)),
            ("false", Ok(RunMode::Primary)),
            ("0", Ok(RunMode::Primary)),
            ("fals", Err(ConfigError::ShadowMode("fals".into()))),
        ] {
            assert_eq!(
                run_mode(&env(&[(SHADOW_MODE_KEY, value)])),
                expected,
                "{value:?}"
            );
        }
        assert_eq!(run_mode(&env(&[])), Ok(RunMode::Shadow));
    }

    #[test]
    fn primary_config_matches_node_defaults() {
        let c = ServiceConfig::from_env(&env(&[
            ("PLUGIN_SERVER_MODE", "ingestion-traces"),
            (SHADOW_MODE_KEY, "false"),
            ("DATABASE_URL", "postgres://x"),
            ("TRACES_LIMITER_BUCKET_SIZE_KB", "2.5"),
        ]))
        .unwrap();
        assert_eq!(c.group_id, NODE_TRACES_GROUP_ID);
        assert_eq!(c.input_topic, "ingestion-traces");
        assert_eq!(c.route("logs").unwrap().topic, "clickhouse_traces");
        assert_eq!(c.route("logs_dlq").unwrap().topic, "ingestion-traces-dlq");
        assert_eq!(
            c.route("app_metrics").unwrap().topic,
            "clickhouse_app_metrics2"
        );
        assert_eq!(c.consumer.limiter_bucket_size_kb, 2.5);
        assert_eq!(c.consumer.limiter_enabled_teams, "");
        assert!(c.logs_redis.tls);
        assert_eq!(c.consumer_loop.max_background_tasks, 1);
        assert_eq!(c.database_writer_url.as_deref(), Some("postgres://x"));

        let transformations = ServiceConfig::from_env(&env(&[
            ("PLUGIN_SERVER_MODE", "ingestion-logs"),
            (SHADOW_MODE_KEY, "false"),
            ("DATABASE_URL", "postgres://x"),
            ("LOGS_TRANSFORMATIONS_ENABLED_TEAMS", "2"),
        ]))
        .unwrap_err();
        assert!(transformations
            .to_string()
            .contains("LOGS_TRANSFORMATIONS_ENABLED_TEAMS"));
        let no_writer = ServiceConfig::from_env(&env(&[
            ("PLUGIN_SERVER_MODE", "ingestion-logs"),
            (SHADOW_MODE_KEY, "false"),
            ("DATABASE_READONLY_URL", "postgres://replica"),
        ]))
        .unwrap_err();
        assert_eq!(
            no_writer,
            ConfigError::Invalid("DATABASE_URL is required".into())
        );
    }
}
