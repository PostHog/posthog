use envconfig::Envconfig;
use rdkafka::ClientConfig;
use tracing::info;

use crate::discovery::DiscoveryMode;
use crate::kafka_config::ConsumerConfigBuilder;
use crate::routing::RoutingStrategy;

/// Configuration for the ingestion consumer.
///
/// Kafka env vars match the Node.js ingestion consumer so this can be a
/// drop-in replacement using the same Kubernetes ConfigMap/env config.
/// The Node.js consumer reads `KAFKA_CONSUMER_*` env vars and maps them to
/// rdkafka config keys. We use the same env var names and defaults here.
///
/// Any `KAFKA_CONSUMER_*` env var is also read and applied as an rdkafka
/// config override — e.g. `KAFKA_CONSUMER_METADATA_BROKER_LIST=kafka:9092`
/// becomes `metadata.broker.list=kafka:9092`. This matches the Node.js
/// `getKafkaConfigFromEnv('CONSUMER')` behavior.
#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    // ---- Kafka connection (matches Node.js KafkaConsumer defaults) ----
    /// Kafka broker list. Overridable via KAFKA_CONSUMER_METADATA_BROKER_LIST
    /// (same as Node.js). This is used as the base default.
    #[envconfig(default = "kafka:9092")]
    pub kafka_hosts: String,

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    /// Security protocol (plaintext, ssl, sasl_plaintext, sasl_ssl)
    #[envconfig(default = "plaintext")]
    pub kafka_security_protocol: String,

    /// Client rack for cross-AZ traffic awareness (shared with Node.js via KAFKA_CLIENT_RACK)
    #[envconfig(default = "")]
    pub kafka_client_rack: String,

    // ---- Kafka consumer group (matches Node.js IngestionConsumerConfig) ----
    /// Consumer group ID. Same env var as Node.js IngestionConsumerConfig.
    #[envconfig(default = "events-ingestion-consumer")]
    pub ingestion_consumer_group_id: String,

    /// Topic to consume from. Same env var as Node.js IngestionConsumerConfig.
    #[envconfig(default = "events_plugin_ingestion")]
    pub ingestion_consumer_consume_topic: String,

    #[envconfig(default = "latest")]
    pub kafka_consumer_offset_reset: String,

    // ---- Kafka consumer tuning (defaults match Node.js KafkaConsumer) ----
    #[envconfig(default = "30000")]
    pub kafka_consumer_session_timeout_ms: u32,

    #[envconfig(default = "5000")]
    pub kafka_heartbeat_interval_ms: u32,

    #[envconfig(default = "300000")]
    pub kafka_consumer_max_poll_interval_ms: u32,

    /// 1MB — matches Node.js default
    #[envconfig(default = "1048576")]
    pub kafka_consumer_max_partition_fetch_bytes: u32,

    #[envconfig(default = "10000")]
    pub kafka_topic_metadata_refresh_interval_ms: u32,

    #[envconfig(default = "30000")]
    pub kafka_consumer_metadata_max_age_ms: u32,

    #[envconfig(default = "30000")]
    pub kafka_consumer_socket_timeout_ms: u32,

    #[envconfig(default = "100")]
    pub kafka_consumer_fetch_error_backoff_ms: u32,

    #[envconfig(default = "1")]
    pub kafka_consumer_fetch_min_bytes: u32,

    #[envconfig(default = "52428800")]
    pub kafka_consumer_fetch_max_bytes: u32,

    /// 10MB — matches Node.js fetch.message.max.bytes
    #[envconfig(default = "10485760")]
    pub kafka_consumer_fetch_message_max_bytes: u32,

    /// 50ms — matches Node.js default (aggressive fetch for low latency)
    #[envconfig(default = "50")]
    pub kafka_consumer_fetch_wait_max_ms: u32,

    #[envconfig(default = "100000")]
    pub kafka_consumer_queued_min_messages: u32,

    /// 100MB — matches Node.js default (reduced from rdkafka default of 1GB)
    #[envconfig(default = "102400")]
    pub kafka_consumer_queued_max_messages_kbytes: u32,

    /// Pod hostname from K8s, used as client.id and group.instance.id
    /// for sticky partition assignment (same as Node.js hostname())
    #[envconfig(from = "HOSTNAME")]
    pub pod_hostname: Option<String>,

    /// Enable Kafka static membership (pins `group.instance.id` to the pod
    /// hostname). Off by default: this runs as a Deployment, so pod names — and
    /// thus instance IDs — already change on every rollout, meaning static
    /// membership never avoids a deploy rebalance, yet it makes an in-place
    /// container restart fail fatally with `UnreleasedInstanceId` (the broker
    /// still holds the previous incarnation's slot until its session expires).
    /// Dynamic membership rejoins cleanly on restart. Only enable for pods with
    /// stable names (e.g. a StatefulSet).
    #[envconfig(from = "KAFKA_CONSUMER_STATIC_MEMBERSHIP", default = "false")]
    pub kafka_consumer_static_membership: bool,

    // ---- Batching ----
    /// Maximum number of messages to collect before dispatching a batch.
    /// Matches Node.js CONSUMER_BATCH_SIZE default.
    #[envconfig(default = "500")]
    pub consumer_batch_size: usize,

    /// Maximum time to wait while collecting a batch (milliseconds)
    #[envconfig(default = "500")]
    pub consumer_batch_timeout_ms: u64,

    /// Upper bound on retrying a batch's deferred messages (held because no
    /// worker was routable) before failing the batch (milliseconds). Bounds how
    /// long a full worker outage holds offsets before the process exits and
    /// restarts.
    #[envconfig(default = "60000")]
    pub consumer_deferred_flush_timeout_ms: u64,

    /// Maximum Kafka batches to process concurrently. Matches the Node.js
    /// CONSUMER_MAX_BACKGROUND_TASKS setting used by the Kafka consumer wrapper.
    #[envconfig(from = "CONSUMER_MAX_BACKGROUND_TASKS", default = "1")]
    pub consumer_max_background_tasks: usize,

    // ---- Worker transport ----
    /// Comma-separated list of worker HTTP URLs
    #[envconfig(default = "http://localhost:9001")]
    pub worker_addresses: String,

    /// HTTP request timeout for worker calls (milliseconds)
    #[envconfig(default = "30000")]
    pub http_timeout_ms: u64,

    /// Maximum number of retries for a failed worker call
    #[envconfig(default = "3")]
    pub max_retries: u32,

    /// Soft cap on in-flight batches per worker, enforced by a per-worker
    /// `Semaphore`. Ideally aligned with the worker's
    /// `BatchingPipeline.concurrentBatches` (`INGESTION_WORKER_CONCURRENT_BATCHES`
    /// on the Node.js side) so the happy path backpressures by waiting for a
    /// permit before the worker fills up. It need not match exactly: if the
    /// worker still responds 503, the transport treats it as retriable
    /// backpressure and retries with a longer, jittered backoff. Divergence
    /// remains observable via `ingestion_api_batch_capacity_rejections_total`.
    /// (A future adaptive-concurrency controller will replace this static cap.)
    #[envconfig(from = "INGESTION_WORKER_CONCURRENT_BATCHES", default = "1")]
    pub ingestion_worker_concurrent_batches: usize,

    /// Shared secret for authenticating with Node.js workers (X-Internal-Api-Secret header)
    #[envconfig(default = "")]
    pub internal_api_secret: String,

    // ---- Worker discovery ----
    /// How the worker pool is discovered: `static` (use WORKER_ADDRESSES — the
    /// co-located sidecar default) or `endpointslice` (watch a Kubernetes
    /// Service's EndpointSlices for a separately-deployed, autoscaled worker pool).
    #[envconfig(from = "WORKER_DISCOVERY_MODE", default = "static")]
    pub worker_discovery_mode: DiscoveryMode,

    /// EndpointSlice mode: Kubernetes Service name whose EndpointSlices list the
    /// worker pods (label selector `kubernetes.io/service-name=<name>`).
    #[envconfig(from = "WORKER_SERVICE_NAME", default = "")]
    pub worker_service_name: String,

    /// EndpointSlice mode: namespace of the worker Service. Defaults to the
    /// pod's own namespace via the downward-API `POD_NAMESPACE` env var.
    #[envconfig(from = "POD_NAMESPACE", default = "default")]
    pub worker_namespace: String,

    /// EndpointSlice mode: the worker pods' HTTP port (the ingestion-api port).
    #[envconfig(from = "WORKER_PORT", default = "9001")]
    pub worker_port: u16,

    /// When a worker leaves the pool (e.g. a draining pod during a deploy), it is
    /// marked draining rather than removed: no new work is routed to it, but its
    /// in-flight batches are allowed to finish and ACK. It is fully removed once
    /// its in-flight count reaches zero, or after this timeout as a safety net
    /// (milliseconds) — sized above the worst-case batch processing time.
    #[envconfig(from = "WORKER_DRAIN_TIMEOUT_MS", default = "30000")]
    pub worker_drain_timeout_ms: u64,

    /// How unpinned routing keys are assigned to workers: `binpack` (default,
    /// least-loaded — accurate for the co-located sidecar) or `p2c`
    /// (power-of-two-choices — herd-resistant for a shared worker pool).
    #[envconfig(from = "INGESTION_ROUTING_STRATEGY", default = "binpack")]
    pub routing_strategy: RoutingStrategy,

    // ---- Worker health / registry ----
    /// How often to probe each worker's /_ready endpoint (milliseconds).
    #[envconfig(default = "5000")]
    pub worker_probe_interval_ms: u64,

    /// Time a worker must spend in Unhealthy before it is declared dead and
    /// sticky pins are dropped (milliseconds).
    #[envconfig(default = "15000")]
    pub worker_dead_declaration_ms: u64,

    /// Rolling window over which passive send outcomes are aggregated (milliseconds).
    #[envconfig(default = "30000")]
    pub worker_passive_window_ms: u64,

    /// Error rate above which the passive signal promotes a worker toward Unhealthy.
    /// Requires at least worker_passive_min_samples samples in the window.
    #[envconfig(default = "0.2")]
    pub worker_passive_error_threshold: f64,

    /// Minimum number of samples in the passive window before the error rate triggers
    /// a state transition. Prevents noise on low-traffic workers.
    #[envconfig(default = "5")]
    pub worker_passive_min_samples: usize,

    /// How long a worker stays in Degraded after recovering from Unhealthy before
    /// being promoted back to Healthy (milliseconds).
    #[envconfig(default = "10000")]
    pub worker_degraded_hold_ms: u64,

    /// Minimum time a worker must remain in a state before any transition is allowed.
    /// Prevents flapping (milliseconds).
    #[envconfig(default = "2000")]
    pub worker_min_state_duration_ms: u64,

    /// Number of consecutive probe failures before a worker is marked Unhealthy.
    #[envconfig(default = "2")]
    pub worker_probe_failure_threshold: u32,

    // ---- Health/metrics server ----
    #[envconfig(default = "0.0.0.0")]
    pub bind_host: String,

    #[envconfig(default = "3301")]
    pub bind_port: u16,

    #[envconfig(default = "true")]
    pub export_prometheus: bool,

    // ---- Metric labels (match Node.js global default labels) ----
    /// Ingestion pipeline this consumer serves (e.g. `analytics`). Emitted as a
    /// global `ingestion_pipeline` label on every metric, mirroring the Node.js
    /// `initializePrometheusLabels` default labels so dashboards, alerts, and
    /// KEDA lag triggers select this consumer's series the same way.
    #[envconfig(from = "INGESTION_PIPELINE")]
    pub ingestion_pipeline: Option<String>,

    /// Ingestion lane this consumer serves (e.g. `main`, `overflow`). Emitted as
    /// a global `ingestion_lane` label on every metric, matching the Node.js
    /// default labels. The lag-based KEDA autoscaler selects on this label.
    #[envconfig(from = "INGESTION_LANE")]
    pub ingestion_lane: Option<String>,
}

/// Parse `KAFKA_CONSUMER_*` env vars into rdkafka config key-value pairs.
///
/// Mirrors the Node.js `getKafkaConfigFromEnv('CONSUMER')` behavior:
/// strips the `KAFKA_CONSUMER_` prefix, replaces underscores with dots,
/// and lowercases the key.
///
/// Example: `KAFKA_CONSUMER_METADATA_BROKER_LIST=kafka:9092`
/// becomes `("metadata.broker.list", "kafka:9092")`
fn parse_kafka_consumer_env_overrides() -> Vec<(String, String)> {
    std::env::vars()
        .filter(|(key, _)| key.starts_with("KAFKA_CONSUMER_"))
        .map(|(key, value)| {
            let rdkafka_key = key
                .strip_prefix("KAFKA_CONSUMER_")
                .unwrap()
                .replace('_', ".")
                .to_lowercase();
            (rdkafka_key, value)
        })
        .collect()
}

impl Config {
    pub fn bind_address(&self) -> String {
        format!("{}:{}", self.bind_host, self.bind_port)
    }

    pub fn worker_urls(&self) -> Vec<String> {
        self.worker_addresses
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    }

    /// Build a fully-configured rdkafka ClientConfig.
    ///
    /// Mirrors the Node.js KafkaConsumer constructor config with the same
    /// defaults and override priority:
    /// 1. Hardcoded defaults (from struct field defaults)
    /// 2. `KAFKA_CONSUMER_*` env var overrides (same as Node.js getKafkaConfigFromEnv)
    /// 3. Non-overridable settings (partition.assignment.strategy, enable.auto.offset.store)
    pub fn build_consumer_config(&self) -> ClientConfig {
        let mut builder = ConsumerConfigBuilder::for_batch_consumer(
            &self.kafka_hosts,
            &self.ingestion_consumer_group_id,
        )
        .with_tls(self.kafka_tls)
        .with_offset_reset(&self.kafka_consumer_offset_reset)
        .with_session_timeout_ms(self.kafka_consumer_session_timeout_ms)
        .with_heartbeat_interval_ms(self.kafka_heartbeat_interval_ms)
        .with_max_poll_interval_ms(self.kafka_consumer_max_poll_interval_ms)
        .with_max_partition_fetch_bytes(self.kafka_consumer_max_partition_fetch_bytes)
        .with_topic_metadata_refresh_interval_ms(self.kafka_topic_metadata_refresh_interval_ms)
        .with_metadata_max_age_ms(self.kafka_consumer_metadata_max_age_ms)
        .with_fetch_min_bytes(self.kafka_consumer_fetch_min_bytes)
        .with_fetch_max_bytes(self.kafka_consumer_fetch_max_bytes)
        .with_fetch_wait_max_ms(self.kafka_consumer_fetch_wait_max_ms)
        .with_queued_min_messages(self.kafka_consumer_queued_min_messages)
        .with_queued_max_messages_kbytes(self.kafka_consumer_queued_max_messages_kbytes)
        .with_sticky_partition_assignment(
            self.pod_hostname.as_deref(),
            self.kafka_consumer_static_membership,
        )
        .set("security.protocol", &self.kafka_security_protocol)
        .set(
            "socket.timeout.ms",
            &self.kafka_consumer_socket_timeout_ms.to_string(),
        )
        .set(
            "fetch.error.backoff.ms",
            &self.kafka_consumer_fetch_error_backoff_ms.to_string(),
        )
        .set(
            "fetch.message.max.bytes",
            &self.kafka_consumer_fetch_message_max_bytes.to_string(),
        );

        if !self.kafka_client_rack.is_empty() {
            builder = builder.set("client.rack", &self.kafka_client_rack);
        }

        // Apply KAFKA_CONSUMER_* env var overrides (same as Node.js getKafkaConfigFromEnv)
        let overrides = parse_kafka_consumer_env_overrides();
        for (key, value) in &overrides {
            info!(key = %key, value = %value, "Applying KAFKA_CONSUMER_ env override");
            builder = builder.set(key, value);
        }

        // After all overrides: if KAFKA_CONSUMER_GROUP_PROTOCOL=consumer selected the
        // KIP-848 protocol, drop the classic-only keys librdkafka would reject.
        builder = builder.strip_classic_protocol_keys_if_consumer();

        builder.build()
    }
}
