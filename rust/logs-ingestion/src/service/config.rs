//! Node settings keep their Node name, default and parse; `LOGS_RUST_*` settings use envconfig.

use std::collections::BTreeSet;
use std::time::Duration;

use envconfig::Envconfig;

use crate::js::{JsObject, JsValue};
use crate::pipeline::LogsIngestionConsumerConfig;

use super::node_env::{
    determine_node_env, get_bool, get_number, get_string, kafka_topic, override_with_env,
    rdkafka_from_env, string_to_boolean, Env, NodeEnv,
};

pub const WARPSTREAM_LOGS_PRODUCER: &str = "WARPSTREAM_LOGS_PRODUCER";
pub const WARPSTREAM_INGESTION_PRODUCER: &str = "WARPSTREAM_INGESTION_PRODUCER";
pub const NODE_LOGS_GROUP_ID: &str = "ingestion-logs";
pub const NODE_TRACES_GROUP_ID: &str = "ingestion-traces";
/// Every shadow topic ends with this, so a production name can never pass as a shadow topic.
pub const SHADOW_TOPIC_SUFFIX: &str = "_rust_shadow";
pub const SHADOW_GROUP_SUFFIX: &str = "-rust-shadow";
/// Node's `defaultConfig` has no `KAFKA_CONSUMER_*` key, so `skipKeysInDefaultConfig` skips none.
pub const NODE_DEFAULT_CONFIG_CONSUMER_KEYS: &[&str] = &[];
const SHADOW_REDIS_DEFAULT_PORT: u16 = 6379;

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

#[derive(Envconfig, Debug, Clone)]
pub struct RustServiceEnv {
    /// `shadow` or `primary`. Required, so a copied Node deployment cannot start as primary.
    #[envconfig(from = "LOGS_RUST_MODE")]
    pub mode: Option<String>,
    #[envconfig(from = "LOGS_RUST_SHADOW_CONSUMER_GROUP_ID")]
    pub shadow_group_id: Option<String>,
    #[envconfig(from = "LOGS_RUST_SHADOW_LOGS_TOPIC")]
    pub shadow_logs_topic: Option<String>,
    #[envconfig(from = "LOGS_RUST_SHADOW_DLQ_TOPIC")]
    pub shadow_dlq_topic: Option<String>,
    #[envconfig(from = "LOGS_RUST_SHADOW_APP_METRICS_TOPIC")]
    pub shadow_app_metrics_topic: Option<String>,
    #[envconfig(from = "LOGS_RUST_SHADOW_REDIS_HOST")]
    pub shadow_redis_host: Option<String>,
    #[envconfig(from = "LOGS_RUST_SHADOW_REDIS_PORT")]
    pub shadow_redis_port: Option<String>,
    #[envconfig(from = "LOGS_RUST_SHADOW_REDIS_PASSWORD")]
    pub shadow_redis_password: Option<String>,
    #[envconfig(from = "LOGS_RUST_SHADOW_REDIS_TLS")]
    pub shadow_redis_tls: Option<String>,
    #[envconfig(from = "LOGS_RUST_SHUTDOWN_TIMEOUT_SECS", default = "60")]
    pub shutdown_timeout_secs: u64,
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
    #[error("LOGS_RUST_MODE is required and must be shadow or primary, got {0:?}")]
    Mode(String),
    #[error("shadow mode requires {0}")]
    MissingShadowSetting(&'static str),
    #[error("shadow consumer group {0:?} is a production consumer group")]
    ProductionGroup(String),
    #[error("shadow output topic {0:?} is a production topic")]
    ProductionTopic(String),
    #[error("shadow output topics must differ from each other, {0:?} repeats")]
    DuplicateShadowTopic(String),
    #[error("{0} must end with {SHADOW_TOPIC_SUFFIX:?}, got {1:?}")]
    ShadowTopicSuffix(&'static str, String),
    #[error("LOGS_RUST_SHADOW_CONSUMER_GROUP_ID must end with {SHADOW_GROUP_SUFFIX:?}, got {0:?}")]
    ShadowGroupSuffix(String),
    #[error("LOGS_RUST_SHADOW_REDIS_HOST and LOGS_RUST_SHADOW_REDIS_PORT name the production Redis in {0}")]
    ShadowRedisIsProduction(String),
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

pub fn production_topics(env: &Env) -> BTreeSet<String> {
    let mut topics = BTreeSet::new();
    for name in [
        "logs_ingestion",
        "logs_ingestion_overflow",
        "logs_ingestion_dlq",
        "clickhouse_logs",
        "ingestion-traces",
        "ingestion-traces-overflow",
        "ingestion-traces-dlq",
        "clickhouse_traces",
        "clickhouse_app_metrics2",
        "log_entries",
    ] {
        topics.insert(name.to_string());
        topics.insert(format!("{name}_test"));
        topics.insert(kafka_topic(env, name));
    }
    for (key, value) in env {
        let is_topic_key = key.starts_with("LOGS_INGESTION_OUTPUT_") && key.ends_with("_TOPIC")
            || [
                "_CLICKHOUSE_TOPIC",
                "_DLQ_TOPIC",
                "_CONSUME_TOPIC",
                "_OVERFLOW_TOPIC",
            ]
            .iter()
            .any(|suffix| key.ends_with(suffix));
        if is_topic_key && !key.starts_with("LOGS_RUST_") && !value.is_empty() {
            topics.insert(value.clone());
        }
    }
    topics
}

fn required(value: &Option<String>, name: &'static str) -> Result<String, ConfigError> {
    match value.as_deref().map(str::trim) {
        Some(v) if !v.is_empty() => Ok(v.to_string()),
        _ => Err(ConfigError::MissingShadowSetting(name)),
    }
}

pub fn shadow_routes(
    env: &Env,
    rust: &RustServiceEnv,
    node_group_key: &str,
    input_topic: &str,
    production: &[OutputRoute],
) -> Result<(String, Vec<OutputRoute>), ConfigError> {
    let group = required(&rust.shadow_group_id, "LOGS_RUST_SHADOW_CONSUMER_GROUP_ID")?;
    if !group.ends_with(SHADOW_GROUP_SUFFIX) {
        return Err(ConfigError::ShadowGroupSuffix(group));
    }
    let mut production_groups = vec![
        NODE_LOGS_GROUP_ID.to_string(),
        NODE_TRACES_GROUP_ID.to_string(),
    ];
    for key in [
        "LOGS_INGESTION_CONSUMER_GROUP_ID",
        "TRACES_INGESTION_CONSUMER_GROUP_ID",
        node_group_key,
    ] {
        if let Some(v) = env.get(key) {
            production_groups.push(v.clone());
        }
    }
    if production_groups.contains(&group) {
        return Err(ConfigError::ProductionGroup(group));
    }

    let mut forbidden = production_topics(env);
    forbidden.insert(input_topic.to_string());
    forbidden.extend(production.iter().map(|r| r.topic.clone()));
    let shadow = [
        (
            crate::pipeline::LOGS_OUTPUT,
            &rust.shadow_logs_topic,
            "LOGS_RUST_SHADOW_LOGS_TOPIC",
        ),
        (
            crate::pipeline::LOGS_DLQ_OUTPUT,
            &rust.shadow_dlq_topic,
            "LOGS_RUST_SHADOW_DLQ_TOPIC",
        ),
        (
            crate::pipeline::app_metrics::APP_METRICS_OUTPUT,
            &rust.shadow_app_metrics_topic,
            "LOGS_RUST_SHADOW_APP_METRICS_TOPIC",
        ),
    ];
    let mut seen = BTreeSet::new();
    let mut routes = Vec::new();
    for (output, value, name) in shadow {
        let topic = required(value, name)?;
        if !topic.ends_with(SHADOW_TOPIC_SUFFIX) {
            return Err(ConfigError::ShadowTopicSuffix(name, topic));
        }
        if forbidden.contains(&topic) {
            return Err(ConfigError::ProductionTopic(topic));
        }
        if !seen.insert(topic.clone()) {
            return Err(ConfigError::DuplicateShadowTopic(topic));
        }
        let producer = production
            .iter()
            .find(|r| r.output == output)
            .map(|r| r.producer.clone())
            .unwrap_or_default();
        routes.push(OutputRoute {
            output,
            topic,
            producer,
        });
    }
    Ok((group, routes))
}

/// The scheme, user info and path are dropped, and the host is lower case.
fn redis_endpoint(raw: &str) -> (String, Option<u16>) {
    let raw = raw.trim();
    let rest = raw.split_once("://").map_or(raw, |(_, rest)| rest);
    let authority = rest.split(['/', '?', '#']).next().unwrap_or_default();
    let authority = authority.rsplit_once('@').map_or(authority, |(_, a)| a);
    let (host, port) = match authority.strip_prefix('[') {
        Some(v6) => match v6.split_once(']') {
            Some((host, tail)) => (host, tail.strip_prefix(':')),
            None => (v6, None),
        },
        None => match authority.rsplit_once(':') {
            Some((host, port)) => (host, Some(port)),
            None => (authority, None),
        },
    };
    (host.to_ascii_lowercase(), port.and_then(|p| p.parse().ok()))
}

/// A URL port and the port key both count, so the guard holds whichever one the client applies.
fn production_redis_endpoints(env: &Env, prefix: &str) -> Vec<(String, String, Vec<u16>)> {
    let mut out = Vec::new();
    let host_key = format!("{prefix}_REDIS_HOST");
    let port_key = format!("{prefix}_REDIS_PORT");
    if let Some(raw) = env.get(&host_key).filter(|v| !v.trim().is_empty()) {
        let (host, url_port) = redis_endpoint(raw);
        let configured = env
            .get(&port_key)
            .and_then(|p| p.trim().parse().ok())
            .unwrap_or(SHADOW_REDIS_DEFAULT_PORT);
        out.push((
            host_key,
            host,
            url_port.into_iter().chain([configured]).collect(),
        ));
    }
    if let Some(raw) = env.get("REDIS_URL").filter(|v| !v.trim().is_empty()) {
        let (host, url_port) = redis_endpoint(raw);
        out.push((
            "REDIS_URL".to_string(),
            host,
            vec![url_port.unwrap_or(SHADOW_REDIS_DEFAULT_PORT)],
        ));
    }
    out
}

/// The shadow token buckets must never share a Redis with Node, so only `LOGS_RUST_SHADOW_REDIS_*` is read.
pub fn shadow_redis(
    env: &Env,
    rust: &RustServiceEnv,
    prefix: &str,
) -> Result<RedisTarget, ConfigError> {
    let host = required(&rust.shadow_redis_host, "LOGS_RUST_SHADOW_REDIS_HOST")?;
    // The value is not echoed, because a URL can carry a password.
    if host.contains("://") || host.contains('@') {
        return Err(ConfigError::Invalid(
            "LOGS_RUST_SHADOW_REDIS_HOST must be a host name, not a URL".to_string(),
        ));
    }
    let port = match rust.shadow_redis_port.as_deref().map(str::trim) {
        None | Some("") => SHADOW_REDIS_DEFAULT_PORT,
        Some(p) => p.parse().map_err(|_| {
            ConfigError::Invalid(format!(
                "LOGS_RUST_SHADOW_REDIS_PORT must be a port, got {p:?}"
            ))
        })?,
    };
    let (shadow_host, _) = redis_endpoint(&host);
    for (key, production_host, ports) in production_redis_endpoints(env, prefix) {
        if production_host == shadow_host && ports.contains(&port) {
            return Err(ConfigError::ShadowRedisIsProduction(key));
        }
    }
    Ok(RedisTarget {
        url_or_host: host,
        port: Some(port),
        password: rust.shadow_redis_password.clone().filter(|p| !p.is_empty()),
        tls: rust
            .shadow_redis_tls
            .as_deref()
            .is_some_and(string_to_boolean),
    })
}

impl ServiceConfig {
    pub fn from_env(env: &Env) -> Result<Self, ConfigError> {
        let rust = RustServiceEnv::init_from_hashmap(env)
            .map_err(|e| ConfigError::Invalid(e.to_string()))?;
        let kind = match env.get("PLUGIN_SERVER_MODE").map(String::as_str) {
            Some("ingestion-logs") => ConsumerKind::Logs,
            Some("ingestion-traces") => ConsumerKind::Traces,
            other => return Err(ConfigError::ConsumerKind(other.unwrap_or("").to_string())),
        };
        let mode = match rust.mode.as_deref().map(str::trim) {
            Some("shadow") => RunMode::Shadow,
            Some("primary") => RunMode::Primary,
            other => return Err(ConfigError::Mode(other.unwrap_or("").to_string())),
        };
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
        let node_group_key = format!("{p}_INGESTION_CONSUMER_GROUP_ID");
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
        let (group_id, routes) = match mode {
            RunMode::Primary => (get_string(&node, &node_group_key), production_routes),
            RunMode::Shadow => shadow_routes(
                env,
                &rust,
                &node_group_key,
                &input_topic,
                &production_routes,
            )?,
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
        let logs_redis = match mode {
            // Node passes no password for the logs Redis, only host, port and TLS.
            RunMode::Primary => redis_target(
                &format!("{p}_REDIS_HOST"),
                &format!("{p}_REDIS_PORT"),
                Some(&format!("{p}_REDIS_TLS")),
                None,
            ),
            RunMode::Shadow => shadow_redis(env, &rust, p)?,
        };
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
        let (database_reader_url, database_writer_url) = match mode {
            RunMode::Primary if database_url.is_empty() => {
                return Err(ConfigError::Invalid("DATABASE_URL is required".to_string()))
            }
            RunMode::Primary if readonly_url.is_empty() => {
                (database_url.clone(), Some(database_url))
            }
            RunMode::Primary => (readonly_url, Some(database_url)),
            // The shadow reads only from a replica, so it never falls back to DATABASE_URL.
            RunMode::Shadow if readonly_url.is_empty() => {
                return Err(ConfigError::MissingShadowSetting("DATABASE_READONLY_URL"))
            }
            RunMode::Shadow => (readonly_url, None),
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
            shutdown_timeout: Duration::from_secs(rust.shutdown_timeout_secs),
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

    fn shadow_env(extra: &[(&str, &str)]) -> Env {
        let mut e = env(&[
            ("PLUGIN_SERVER_MODE", "ingestion-logs"),
            ("LOGS_RUST_MODE", "shadow"),
            ("DATABASE_URL", "postgres://x"),
            ("DATABASE_READONLY_URL", "postgres://replica"),
            ("LOGS_RUST_SHADOW_REDIS_HOST", "shadow-redis"),
            (
                "LOGS_RUST_SHADOW_CONSUMER_GROUP_ID",
                "ingestion-logs-rust-shadow",
            ),
            ("LOGS_RUST_SHADOW_LOGS_TOPIC", "clickhouse_logs_rust_shadow"),
            (
                "LOGS_RUST_SHADOW_DLQ_TOPIC",
                "logs_ingestion_dlq_rust_shadow",
            ),
            (
                "LOGS_RUST_SHADOW_APP_METRICS_TOPIC",
                "app_metrics_rust_shadow",
            ),
        ]);
        e.extend(extra.iter().map(|(k, v)| (k.to_string(), v.to_string())));
        e
    }

    #[test]
    fn shadow_config_routes_every_output_to_its_shadow_topic() {
        let c = ServiceConfig::from_env(&shadow_env(&[
            ("LOGS_REDIS_HOST", "prod-redis"),
            ("REDIS_URL", "redis://prod-redis"),
        ]))
        .unwrap();
        assert_eq!(c.mode, RunMode::Shadow);
        assert_eq!(c.database_reader_url, "postgres://replica");
        assert_eq!(c.database_writer_url, None);
        assert_eq!(c.logs_redis.url_or_host, "shadow-redis");
        assert_eq!(c.logs_redis.port, Some(6379));
        assert!(!c.logs_redis.tls);
        assert_eq!(c.group_id, "ingestion-logs-rust-shadow");
        assert_eq!(c.input_topic, "logs_ingestion");
        let topics: Vec<(&str, &str, &str)> = c
            .routes
            .iter()
            .map(|r| (r.output, r.topic.as_str(), r.producer.as_str()))
            .collect();
        assert_eq!(
            topics,
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
                    "app_metrics_rust_shadow",
                    WARPSTREAM_INGESTION_PRODUCER
                ),
            ]
        );
    }

    #[test]
    fn shadow_guards_reject_unsafe_settings() {
        let cases: Vec<(Env, ConfigError)> = vec![
            (
                shadow_env(&[("LOGS_RUST_MODE", "")]),
                ConfigError::Mode(String::new()),
            ),
            (
                shadow_env(&[("LOGS_RUST_SHADOW_CONSUMER_GROUP_ID", "ingestion-logs")]),
                ConfigError::ShadowGroupSuffix("ingestion-logs".into()),
            ),
            (
                shadow_env(&[
                    ("LOGS_INGESTION_CONSUMER_GROUP_ID", "custom-rust-shadow"),
                    ("LOGS_RUST_SHADOW_CONSUMER_GROUP_ID", "custom-rust-shadow"),
                ]),
                ConfigError::ProductionGroup("custom-rust-shadow".into()),
            ),
            (
                shadow_env(&[("LOGS_RUST_SHADOW_LOGS_TOPIC", "clickhouse_logs")]),
                ConfigError::ShadowTopicSuffix(
                    "LOGS_RUST_SHADOW_LOGS_TOPIC",
                    "clickhouse_logs".into(),
                ),
            ),
            (
                shadow_env(&[("LOGS_RUST_SHADOW_DLQ_TOPIC", "example-logs-dlq")]),
                ConfigError::ShadowTopicSuffix(
                    "LOGS_RUST_SHADOW_DLQ_TOPIC",
                    "example-logs-dlq".into(),
                ),
            ),
            (
                shadow_env(&[
                    (
                        "LOGS_INGESTION_OUTPUT_APP_METRICS_TOPIC",
                        "metrics_rust_shadow",
                    ),
                    ("LOGS_RUST_SHADOW_APP_METRICS_TOPIC", "metrics_rust_shadow"),
                ]),
                ConfigError::ProductionTopic("metrics_rust_shadow".into()),
            ),
            (
                shadow_env(&[("DATABASE_READONLY_URL", " ")]),
                ConfigError::MissingShadowSetting("DATABASE_READONLY_URL"),
            ),
            (
                shadow_env(&[("LOGS_RUST_SHADOW_REDIS_HOST", "")]),
                ConfigError::MissingShadowSetting("LOGS_RUST_SHADOW_REDIS_HOST"),
            ),
            (
                shadow_env(&[("LOGS_REDIS_HOST", "Shadow-Redis")]),
                ConfigError::ShadowRedisIsProduction("LOGS_REDIS_HOST".into()),
            ),
            (
                shadow_env(&[("LOGS_REDIS_HOST", "redis://user:pw@SHADOW-redis:6379/0")]),
                ConfigError::ShadowRedisIsProduction("LOGS_REDIS_HOST".into()),
            ),
            (
                shadow_env(&[
                    ("LOGS_REDIS_HOST", ""),
                    ("REDIS_URL", "rediss://shadow-redis"),
                ]),
                ConfigError::ShadowRedisIsProduction("REDIS_URL".into()),
            ),
            (
                shadow_env(&[(
                    "LOGS_RUST_SHADOW_REDIS_HOST",
                    "redis://:hunter2@shadow-redis",
                )]),
                ConfigError::Invalid(
                    "LOGS_RUST_SHADOW_REDIS_HOST must be a host name, not a URL".into(),
                ),
            ),
            (
                shadow_env(&[("LOGS_RUST_SHADOW_DLQ_TOPIC", "clickhouse_logs_rust_shadow")]),
                ConfigError::DuplicateShadowTopic("clickhouse_logs_rust_shadow".into()),
            ),
            (
                shadow_env(&[("LOGS_RUST_SHADOW_APP_METRICS_TOPIC", " ")]),
                ConfigError::MissingShadowSetting("LOGS_RUST_SHADOW_APP_METRICS_TOPIC"),
            ),
        ];
        for (e, expected) in cases {
            let error = ServiceConfig::from_env(&e).unwrap_err();
            assert!(!error.to_string().contains("hunter2"), "{error}");
            assert_eq!(error, expected);
        }
        // Another port on the same host is another Redis.
        ServiceConfig::from_env(&shadow_env(&[
            ("LOGS_REDIS_HOST", "shadow-redis"),
            ("LOGS_RUST_SHADOW_REDIS_PORT", "6380"),
        ]))
        .unwrap();
        let mut no_mode = shadow_env(&[]);
        no_mode.remove("LOGS_RUST_MODE");
        assert_eq!(
            ServiceConfig::from_env(&no_mode).unwrap_err(),
            ConfigError::Mode(String::new())
        );
    }

    #[test]
    fn primary_config_matches_node_defaults() {
        let c = ServiceConfig::from_env(&env(&[
            ("PLUGIN_SERVER_MODE", "ingestion-traces"),
            ("LOGS_RUST_MODE", "primary"),
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
            ("LOGS_RUST_MODE", "primary"),
            ("DATABASE_URL", "postgres://x"),
            ("LOGS_TRANSFORMATIONS_ENABLED_TEAMS", "2"),
        ]))
        .unwrap_err();
        assert!(transformations
            .to_string()
            .contains("LOGS_TRANSFORMATIONS_ENABLED_TEAMS"));
    }
}
