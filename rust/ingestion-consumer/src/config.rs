use std::num::{NonZeroU32, NonZeroU64, NonZeroUsize};
use std::str::FromStr;
use std::time::{Duration, Instant};

use common_continuous_profiling::ContinuousProfilingConfig;
use envconfig::Envconfig;
use rdkafka::ClientConfig;
use tracing::info;

use crate::batcher::governor::{Adaptation, GovernorSettings};
use crate::batcher::key_queues::RunCap;
use crate::batcher::packer::{PackTargets, Packer};
use crate::batcher::retry_policy::RetryPolicy;
use crate::batcher::state_machine::{BatcherStateMachine, RequestBudget};
use crate::batcher::worker_assigner::WorkerAssigner;
use crate::charge_limit::ChargeLimit;
use crate::discovery::DiscoveryMode;
use crate::partition_budget::BudgetLimits;
use crate::routing::{Router, RoutingStrategy};
use common_kafka_consumer::config::ConsumerConfigBuilder;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum CompletionGranularity {
    #[default]
    Poll,
    Group,
}

impl FromStr for CompletionGranularity {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_lowercase().as_str() {
            "poll" => Ok(Self::Poll),
            "group" => Ok(Self::Group),
            other => Err(format!(
                "unknown consumer completion granularity '{other}' (expected 'poll' or 'group')"
            )),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum Polling {
    #[default]
    Capped,
    Continuous,
}

impl FromStr for Polling {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_lowercase().as_str() {
            "capped" => Ok(Self::Capped),
            "continuous" => Ok(Self::Continuous),
            other => Err(format!(
                "unknown consumer polling strategy '{other}' (expected 'capped' or 'continuous')"
            )),
        }
    }
}

/// Configuration for the ingestion consumer. Env var names and defaults match
/// the Node.js ingestion consumer, so both read the same ConfigMap.
/// `KAFKA_CONSUMER_*` vars also apply as rdkafka overrides; see
/// `parse_kafka_consumer_env_overrides`.
#[derive(Envconfig, Clone, Debug)]
pub struct Config {
    // ---- Kafka connection (matches Node.js KafkaConsumer defaults) ----
    /// Kafka broker list. `KAFKA_CONSUMER_METADATA_BROKER_LIST` overrides it.
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

    #[envconfig(default = "10485760")]
    pub kafka_consumer_fetch_message_max_bytes: u32,

    /// Below the librdkafka default of 500ms, for low fetch latency.
    #[envconfig(default = "50")]
    pub kafka_consumer_fetch_wait_max_ms: u32,

    #[envconfig(default = "100000")]
    pub kafka_consumer_queued_min_messages: u32,

    #[envconfig(default = "102400")]
    pub kafka_consumer_queued_max_messages_kbytes: u32,

    /// How often librdkafka emits its internal statistics snapshot to the
    /// consumer's `stats` callback (milliseconds), which exports the
    /// `kafka_consumer_*` gauges. `0` disables the callback entirely. The
    /// callback runs on a librdkafka thread and only walks the assigned
    /// partitions and connected brokers, so 15s is cheap; lower it only when
    /// actively debugging queue growth.
    #[envconfig(default = "15000")]
    pub kafka_consumer_statistics_interval_ms: u32,

    /// Pod hostname from K8s. Used as `client.id`, and as `group.instance.id`
    /// when `KAFKA_CONSUMER_STATIC_MEMBERSHIP` is on.
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

    /// Maximum payload bytes to collect into one poll, in KiB. `0` (default)
    /// disables the bound. Whichever of this and `CONSUMER_BATCH_SIZE` is reached
    /// first ends collection: the count bounds request shape, this bounds memory,
    /// because event size differs per lane. A poll can pass it by one message.
    #[envconfig(from = "CONSUMER_BATCH_SIZE_KB", default = "0")]
    pub consumer_batch_size_kb: usize,

    /// Maximum time to wait while collecting a batch (milliseconds)
    #[envconfig(default = "500")]
    pub consumer_batch_timeout_ms: u64,

    /// No-progress bound on the batcher's pending work (milliseconds): the
    /// deadline resets whenever a worker accepts a request, so a slow drain
    /// keeps going and the consumer only fails (exiting the process) after a
    /// full window with pending work and nothing landed, for example with no
    /// worker routable at all. Bounds how long a genuine wedge holds offsets
    /// before the process exits and restarts.
    #[envconfig(default = "60000")]
    pub consumer_deferred_flush_timeout_ms: u64,

    /// How long the batcher waits before it retries a failed send, and how
    /// often a request with no routable worker tries again (milliseconds).
    #[envconfig(from = "INGESTION_PARKED_RETRY_INTERVAL_MS", default = "200")]
    pub parked_retry_interval_ms: u64,

    /// Target request size in events for the packer: once this many events
    /// are ready, a free worker slot gets a request at once. Unless a run cap
    /// is set, one key's run never holds more, so a key's backlog leaves in
    /// consecutive requests. `0` disables the event target and the cap, and
    /// needs a byte target.
    #[envconfig(from = "INGESTION_PACK_TARGET_EVENTS", default = "500")]
    pub pack_target_events: usize,

    /// Target request size in key-plus-value bytes for the packer. Unless a
    /// run cap is set, one key's run never holds more. `0` (default) disables
    /// the byte target and the cap, and needs an event target.
    #[envconfig(from = "INGESTION_PACK_TARGET_BYTES", default = "0")]
    pub pack_target_bytes: usize,

    /// With both run caps at `0` (default), the pack targets cap runs.
    /// Otherwise a `0` run cap leaves that dimension uncapped.
    #[envconfig(from = "INGESTION_RUN_CAP_EVENTS", default = "0")]
    pub run_cap_events: usize,

    #[envconfig(from = "INGESTION_RUN_CAP_BYTES", default = "0")]
    pub run_cap_bytes: usize,

    /// How long ready events below the target wait for more, counted from
    /// when a worker slot is free for them, before the packer sends them
    /// short of the target (milliseconds). `0` (default) waits for nothing:
    /// each free slot gets what is ready, packed up to the target. At most
    /// half of `CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS`.
    #[envconfig(from = "INGESTION_PACK_LATENCY_BUDGET_MS", default = "0")]
    pub pack_latency_budget_ms: u64,

    /// How long a worker may spend on one request before it stops starting
    /// work and acks what finished as partial (milliseconds). `0` (default)
    /// sends no budget, otherwise at least 100. See `request_budget` for the
    /// bounds against the ack and stall timeouts.
    #[envconfig(from = "INGESTION_REQUEST_SOFT_BUDGET_MS", default = "0")]
    pub request_soft_budget_ms: u64,

    /// How many budgeted attempts may leave a key's messages unfinished, since
    /// the key last finished a run, before it resends without a budget. At
    /// least 1. Only read when `INGESTION_REQUEST_SOFT_BUDGET_MS` is set.
    #[envconfig(from = "INGESTION_REQUEST_BUDGET_ATTEMPTS", default = "3")]
    pub request_budget_attempts: u32,

    /// `off` (default) keeps the governor observing: it measures request
    /// round-trip time and reports the permit pool it would run, while free
    /// worker slots size each pass. `on` sizes the pass by free permits too.
    #[envconfig(from = "INGESTION_GOVERNOR_ADAPTATION", default = "off")]
    pub governor_adaptation: Adaptation,

    /// A round-trip average above this shrinks the permit pool by one per
    /// step (milliseconds). `0` (default) never shrinks. Required when
    /// adaptation is on. See `governor_settings` for the bounds against the
    /// soft budget and the ack timeout.
    #[envconfig(from = "INGESTION_GOVERNOR_LATENCY_BUDGET_MS", default = "0")]
    pub governor_latency_budget_ms: u64,

    /// The permit pool never shrinks below this many permits per routable
    /// worker. At least 1, at most `INGESTION_WORKER_CONCURRENT_BATCHES`.
    #[envconfig(from = "INGESTION_GOVERNOR_MIN_PERMITS_PER_WORKER", default = "1")]
    pub governor_min_permits_per_worker: usize,

    /// The least time between two permit steps (milliseconds). At least 100.
    #[envconfig(from = "INGESTION_GOVERNOR_STEP_INTERVAL_MS", default = "1000")]
    pub governor_step_interval_ms: u64,

    /// Maximum polls in flight under the capped polling strategy; continuous
    /// polling does not read it. Same name as the Node.js setting.
    #[envconfig(from = "CONSUMER_MAX_BACKGROUND_TASKS", default = "1")]
    pub consumer_max_background_tasks: usize,

    /// `poll` or `group`; see [`CompletionGranularity`].
    #[envconfig(from = "CONSUMER_COMPLETION_GRANULARITY", default = "poll")]
    pub consumer_completion_granularity: CompletionGranularity,

    /// Minimum spacing between offset commits at `group` granularity
    /// (milliseconds). Not read at `poll` granularity.
    #[envconfig(from = "CONSUMER_COMMIT_INTERVAL_MS", default = "500")]
    pub consumer_commit_interval_ms: u64,

    /// Uncommitted events at which a partition's fetch pauses. `0` (default)
    /// sets no event limit. Not read at `poll` granularity.
    #[envconfig(from = "CONSUMER_PARTITION_BUDGET_EVENTS", default = "0")]
    pub consumer_partition_budget_events: u64,

    /// Uncommitted key-plus-value-plus-header bytes at which a partition's
    /// fetch pauses. `0` (default) sets no byte limit. Not read at `poll`
    /// granularity.
    #[envconfig(from = "CONSUMER_PARTITION_BUDGET_BYTES", default = "0")]
    pub consumer_partition_budget_bytes: u64,

    /// Fraction of the budget a paused partition must be back under, on
    /// every set axis, before its fetch resumes. Above 0 and at most 1.
    #[envconfig(from = "CONSUMER_PARTITION_BUDGET_LOW_WATERMARK", default = "0.8")]
    pub consumer_partition_budget_low_watermark: f64,

    /// `capped` or `continuous`. `continuous` runs only with `group`
    /// granularity, a partition budget, and an in-flight limit; without all
    /// three the consumer runs `capped`.
    #[envconfig(from = "CONSUMER_POLLING_STRATEGY", default = "capped")]
    pub consumer_polling_strategy: Polling,

    /// Uncommitted events across all partitions at which the continuous
    /// strategy stops reading from Kafka. The poll in progress still
    /// completes, so the total can pass it by `CONSUMER_BATCH_SIZE`. `0`
    /// (default) sets no event limit.
    #[envconfig(from = "CONSUMER_IN_FLIGHT_EVENTS", default = "0")]
    pub consumer_in_flight_events: u64,

    /// Uncommitted key-plus-value-plus-header bytes across all partitions at
    /// which the continuous strategy stops reading from Kafka. The poll in
    /// progress still completes, so the total can pass it by one poll. `0`
    /// (default) sets no byte limit.
    #[envconfig(from = "CONSUMER_IN_FLIGHT_BYTES", default = "0")]
    pub consumer_in_flight_bytes: u64,

    // ---- Debug API ----
    /// Serve the real-time debug API (`/debug/load`, `/debug/state`,
    /// `/debug/events` SSE) on the health server, recording structured events
    /// (batch lifecycle, deferrals, retries, worker health) into a bounded
    /// in-memory buffer. Consumed by the ingestion control plane UI. A pure
    /// observer for dev and incident debugging; off by default. Requires
    /// DEBUG_API_SECRET — enabling without a secret mounts nothing.
    #[envconfig(from = "DEBUG_API_ENABLED", default = "false")]
    pub debug_api_enabled: bool,

    /// Shared secret callers must present as `X-Debug-Api-Secret` on every
    /// `/debug/*` request. Dedicated to this one control-plane→consumer hop
    /// (deliberately not `INTERNAL_API_SECRET` — see .agents/security.md).
    /// Empty fails closed: the debug API is not mounted without it.
    #[envconfig(from = "DEBUG_API_SECRET", default = "")]
    pub debug_api_secret: String,

    // ---- Ordering sentinels ----
    /// Kill switch for the per-key send-order sentinel. The worker-side
    /// feed-order sentinel has its own flag
    /// (INGESTION_API_FEED_ORDER_SENTINEL_ENABLED on the Node.js side).
    #[envconfig(from = "CONSUMER_ORDER_SENTINEL_ENABLED", default = "true")]
    pub consumer_order_sentinel_enabled: bool,

    // ---- Worker transport ----
    /// Comma-separated list of worker HTTP URLs. Readiness probes hit these
    /// directly; each worker's gRPC stream address is derived from its URL's
    /// host plus the gRPC port settings below.
    #[envconfig(default = "http://localhost:9001")]
    pub worker_addresses: String,

    /// The most requests the batcher keeps in flight on one worker, and the
    /// governor's permits per worker at its ceiling. Aligned with the worker's
    /// `BatchingPipeline.concurrentBatches` (`INGESTION_WORKER_CONCURRENT_BATCHES`
    /// on the Node.js side), because the worker queues requests past it
    /// without saying so.
    #[envconfig(from = "INGESTION_WORKER_CONCURRENT_BATCHES", default = "1")]
    pub ingestion_worker_concurrent_batches: usize,

    /// Cap on the estimated serialized size of one sub-batch frame (bytes).
    /// Sub-batches above it ride the worker stream as consecutive chunks. Must
    /// stay under the worker's gRPC message limit with headroom for the size
    /// estimate.
    #[envconfig(from = "INGESTION_TRANSPORT_MAX_BODY_BYTES", default = "10485760")]
    pub transport_max_body_bytes: usize,

    /// The worker pods' gRPC port (`INGESTION_API_GRPC_PORT` on the Node.js
    /// side). Worker streams derive each worker's stream address from its HTTP URL's
    /// host plus this port.
    #[envconfig(from = "INGESTION_WORKER_GRPC_PORT", default = "6739")]
    pub ingestion_worker_grpc_port: u16,

    /// When non-zero, override the fixed gRPC port: each worker's stream
    /// address becomes its HTTP port plus this offset. For single-host setups
    /// (local dev) where workers share an IP and differ only by port.
    #[envconfig(from = "INGESTION_WORKER_GRPC_PORT_OFFSET", default = "0")]
    pub ingestion_worker_grpc_port_offset: u16,

    /// Fence a worker stream (fail its un-acked and queued sub-batches back to
    /// the caller, reconnect) when one sub-batch waits this long for its ack
    /// (milliseconds). The stream has no other per-send timeout. Size it above
    /// the worst-case batch processing time.
    #[envconfig(from = "INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS", default = "60000")]
    pub ingestion_worker_stream_ack_timeout_ms: u64,

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

    /// How requests are placed on workers: `p2c` (default,
    /// power-of-two-choices — herd-resistant for a shared worker pool) or
    /// `aperture` (P2C within this consumer's slice of the worker ring).
    #[envconfig(from = "INGESTION_ROUTING_STRATEGY", default = "p2c")]
    pub routing_strategy: RoutingStrategy,

    /// Minimum aperture width for `INGESTION_ROUTING_STRATEGY=aperture`: how
    /// many workers this dispatcher's ring slice spans. The effective width
    /// is floored at `ceil(pool / dispatchers)` so the fleet's slices always
    /// cover the whole pool. Small values maximize sub-batch consolidation.
    #[envconfig(from = "INGESTION_MIN_APERTURE", default = "3")]
    pub min_aperture: usize,

    // ---- Peer awareness ----
    /// Kubernetes Service whose EndpointSlices list this consumer's own peer
    /// pods. Enables coordination-free peer awareness (each pod's stable index
    /// among its replicas), the basis for deterministic aperture routing.
    /// Empty (default) disables it. The Service is looked up in the pod's own
    /// namespace (`POD_NAMESPACE`).
    #[envconfig(from = "PEER_SERVICE_NAME", default = "")]
    pub peer_service_name: String,

    /// This pod's IP from the downward API, used to locate self in the peer
    /// Service's EndpointSlices. Required when PEER_SERVICE_NAME is set.
    #[envconfig(from = "POD_IP")]
    pub pod_ip: Option<String>,

    // ---- Worker health / registry ----
    /// How often to probe each worker's /_ready endpoint (milliseconds).
    #[envconfig(default = "5000")]
    pub worker_probe_interval_ms: u64,

    /// Time a worker must spend in Unhealthy before it is declared dead
    /// (milliseconds).
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

    #[envconfig(nested = true)]
    pub continuous_profiling: ContinuousProfilingConfig,
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

    /// The batcher state machine. It takes the parked-retry interval for every
    /// retry and the deferred-flush timeout as its stall timeout.
    pub fn batcher_state_machine(&self) -> Result<BatcherStateMachine, String> {
        let mut packer = Packer::new(PackTargets {
            events: NonZeroUsize::new(self.pack_target_events),
            bytes: NonZeroUsize::new(self.pack_target_bytes),
            latency_budget: Duration::from_millis(self.pack_latency_budget_ms),
        });
        let run_cap = RunCap {
            messages: NonZeroUsize::new(self.run_cap_events),
            bytes: NonZeroUsize::new(self.run_cap_bytes),
        };
        if run_cap != RunCap::default() {
            packer = packer.with_run_cap(run_cap);
        }
        let assigner = WorkerAssigner::new(
            Router::new(self.routing_strategy),
            self.ingestion_worker_concurrent_batches,
        )?;
        let retry = RetryPolicy::uniform(Duration::from_millis(self.parked_retry_interval_ms))?;
        BatcherStateMachine::new(
            packer,
            assigner,
            retry,
            Duration::from_millis(self.consumer_deferred_flush_timeout_ms),
            Instant::now(),
        )?
        .with_request_budget(self.request_budget()?)
        .with_governor(self.governor_settings()?)
    }

    const MIN_GOVERNOR_STEP_INTERVAL_MS: u64 = 100;

    pub fn governor_settings(&self) -> Result<GovernorSettings, String> {
        let budget_ms = self.governor_latency_budget_ms;
        if self.governor_adaptation == Adaptation::On && budget_ms == 0 {
            return Err(
                "INGESTION_GOVERNOR_ADAPTATION=on needs INGESTION_GOVERNOR_LATENCY_BUDGET_MS"
                    .to_string(),
            );
        }
        // A saturated worker answers partial at about the soft budget, so a
        // latency budget at or above it never shrinks on saturation.
        if budget_ms > 0
            && self.request_soft_budget_ms > 0
            && budget_ms >= self.request_soft_budget_ms
        {
            return Err("INGESTION_GOVERNOR_LATENCY_BUDGET_MS must be below \
                 INGESTION_REQUEST_SOFT_BUDGET_MS"
                .to_string());
        }
        // The ack watchdog fails a request at the timeout, and a failure is
        // no sample.
        if budget_ms >= self.ingestion_worker_stream_ack_timeout_ms {
            return Err("INGESTION_GOVERNOR_LATENCY_BUDGET_MS must be below \
                 INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS"
                .to_string());
        }
        let min_permits = self.governor_min_permits_per_worker;
        if min_permits == 0 || min_permits > self.ingestion_worker_concurrent_batches {
            return Err(
                "INGESTION_GOVERNOR_MIN_PERMITS_PER_WORKER must be at least 1 and at most \
                 INGESTION_WORKER_CONCURRENT_BATCHES"
                    .to_string(),
            );
        }
        if self.governor_adaptation == Adaptation::On
            && min_permits == self.ingestion_worker_concurrent_batches
        {
            return Err(
                "INGESTION_GOVERNOR_ADAPTATION=on needs INGESTION_GOVERNOR_MIN_PERMITS_PER_WORKER \
                 below INGESTION_WORKER_CONCURRENT_BATCHES, or the pool cannot move"
                    .to_string(),
            );
        }
        if self.governor_step_interval_ms < Self::MIN_GOVERNOR_STEP_INTERVAL_MS {
            return Err(format!(
                "INGESTION_GOVERNOR_STEP_INTERVAL_MS must be at least {}",
                Self::MIN_GOVERNOR_STEP_INTERVAL_MS
            ));
        }
        Ok(GovernorSettings {
            adaptation: self.governor_adaptation,
            latency_budget: (budget_ms > 0).then(|| Duration::from_millis(budget_ms)),
            min_permits_per_worker: min_permits,
            step_interval: Duration::from_millis(self.governor_step_interval_ms),
        })
    }

    pub fn partition_budget(&self) -> Result<BudgetLimits, String> {
        BudgetLimits::new(
            NonZeroU64::new(self.consumer_partition_budget_events),
            NonZeroU64::new(self.consumer_partition_budget_bytes),
            self.consumer_partition_budget_low_watermark,
        )
    }

    pub fn in_flight_limit(&self) -> ChargeLimit {
        ChargeLimit::new(
            NonZeroU64::new(self.consumer_in_flight_events),
            NonZeroU64::new(self.consumer_in_flight_bytes),
        )
    }

    const MIN_REQUEST_SOFT_BUDGET_MS: u64 = 100;

    pub fn request_budget(&self) -> Result<Option<RequestBudget>, String> {
        let budget_ms = self.request_soft_budget_ms;
        if budget_ms == 0 {
            return Ok(None);
        }
        // Below this the worker's fixed work per frame outlasts the budget, so
        // nearly every request comes back partial with nothing finished.
        if budget_ms < Self::MIN_REQUEST_SOFT_BUDGET_MS {
            return Err(format!(
                "INGESTION_REQUEST_SOFT_BUDGET_MS must be at least {}",
                Self::MIN_REQUEST_SOFT_BUDGET_MS
            ));
        }
        // The worker treats a longer budget as unlimited.
        if budget_ms > i32::MAX as u64 {
            return Err(format!(
                "INGESTION_REQUEST_SOFT_BUDGET_MS must be at most {}",
                i32::MAX
            ));
        }
        // The worker starts a frame's budget when it reads the frame, and a
        // full worker reads the next frame only once the previous one has a
        // slot, so the last frame in flight can ack a budget per frame late.
        let in_flight = self.ingestion_worker_concurrent_batches.max(1) as u64;
        if budget_ms.saturating_mul(in_flight) >= self.ingestion_worker_stream_ack_timeout_ms {
            return Err(
                "INGESTION_REQUEST_SOFT_BUDGET_MS times INGESTION_WORKER_CONCURRENT_BATCHES must \
                 be below INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS"
                    .to_string(),
            );
        }
        let attempts = NonZeroU32::new(self.request_budget_attempts)
            .ok_or("INGESTION_REQUEST_BUDGET_ATTEMPTS must be at least 1")?;
        // A partial ack that finished nothing does not count as progress, so
        // it must come back before the stall watchdog fires. Its resend goes
        // without a budget, so no second one follows for the same key.
        if budget_ms.saturating_add(self.pack_latency_budget_ms)
            >= self.consumer_deferred_flush_timeout_ms
        {
            return Err(
                "INGESTION_REQUEST_SOFT_BUDGET_MS plus INGESTION_PACK_LATENCY_BUDGET_MS must be \
                 below CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS"
                    .to_string(),
            );
        }
        Ok(Some(RequestBudget {
            soft_budget: Duration::from_millis(budget_ms),
            attempts,
        }))
    }

    pub fn worker_urls(&self) -> Vec<String> {
        self.worker_addresses
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    }

    /// Build a fully-configured rdkafka ClientConfig, in Node.js order:
    /// 1. Defaults from the struct fields.
    /// 2. `KAFKA_CONSUMER_*` env var overrides.
    /// 3. Classic-protocol keys removed when `group.protocol=consumer`.
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
        )
        // Set before the env-override loop below so
        // KAFKA_CONSUMER_STATISTICS_INTERVAL_MS stays authoritative.
        .set(
            "statistics.interval.ms",
            &self.kafka_consumer_statistics_interval_ms.to_string(),
        );

        if !self.kafka_client_rack.is_empty() {
            builder = builder.set("client.rack", &self.kafka_client_rack);
        }

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

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use rstest::rstest;

    use super::*;

    fn config(vars: &[(&str, &str)]) -> Config {
        let vars: HashMap<String, String> = vars
            .iter()
            .map(|(key, value)| (key.to_string(), value.to_string()))
            .collect();
        Config::init_from_hashmap(&vars).expect("valid config")
    }

    #[rstest]
    #[case::unset(&[], None)]
    #[case::set(&[("INGESTION_REQUEST_SOFT_BUDGET_MS", "250")], Some((250, 3)))]
    #[case::at_the_floor(&[("INGESTION_REQUEST_SOFT_BUDGET_MS", "100")], Some((100, 3)))]
    #[case::just_below_the_ack_and_stall_timeouts(
        &[("INGESTION_REQUEST_SOFT_BUDGET_MS", "59999")],
        Some((59999, 3))
    )]
    #[case::just_below_the_stall_timeout_with_the_pack_latency(
        &[
            ("INGESTION_REQUEST_SOFT_BUDGET_MS", "49999"),
            ("INGESTION_PACK_LATENCY_BUDGET_MS", "10000"),
        ],
        Some((49999, 3))
    )]
    fn a_valid_request_budget_is_read(
        #[case] vars: &[(&str, &str)],
        #[case] expected: Option<(u64, u32)>,
    ) {
        let expected = expected.map(|(budget_ms, attempts)| RequestBudget {
            soft_budget: Duration::from_millis(budget_ms),
            attempts: NonZeroU32::new(attempts).expect("nonzero attempts"),
        });
        assert_eq!(config(vars).request_budget(), Ok(expected));
    }

    #[rstest]
    #[case::below_the_floor(&[("INGESTION_REQUEST_SOFT_BUDGET_MS", "99")])]
    #[case::longer_than_the_worker_honors(&[
        ("INGESTION_REQUEST_SOFT_BUDGET_MS", "2147483648"),
        ("INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS", "4294967296"),
        ("CONSUMER_DEFERRED_FLUSH_TIMEOUT_MS", "4294967296"),
    ])]
    #[case::at_the_ack_timeout_across_every_frame_in_flight(&[
        ("INGESTION_REQUEST_SOFT_BUDGET_MS", "15000"),
        ("INGESTION_WORKER_CONCURRENT_BATCHES", "4"),
    ])]
    #[case::at_the_stall_timeout_with_the_pack_latency(&[
        ("INGESTION_REQUEST_SOFT_BUDGET_MS", "50000"),
        ("INGESTION_PACK_LATENCY_BUDGET_MS", "10000"),
        ("INGESTION_WORKER_STREAM_ACK_TIMEOUT_MS", "120000"),
    ])]
    #[case::with_no_budgeted_attempt(&[
        ("INGESTION_REQUEST_SOFT_BUDGET_MS", "250"),
        ("INGESTION_REQUEST_BUDGET_ATTEMPTS", "0"),
    ])]
    fn an_invalid_request_budget_is_rejected(#[case] vars: &[(&str, &str)]) {
        assert!(config(vars).request_budget().is_err());
    }

    #[rstest]
    #[case::unset(&[], false)]
    #[case::events_only(&[("CONSUMER_PARTITION_BUDGET_EVENTS", "5000")], true)]
    #[case::bytes_only(&[("CONSUMER_PARTITION_BUDGET_BYTES", "1048576")], true)]
    fn a_valid_partition_budget_is_read(#[case] vars: &[(&str, &str)], #[case] is_set: bool) {
        assert_eq!(config(vars).partition_budget().unwrap().is_set(), is_set);
    }

    #[test]
    fn a_partition_budget_with_an_invalid_watermark_is_rejected() {
        let vars = &[
            ("CONSUMER_PARTITION_BUDGET_EVENTS", "5000"),
            ("CONSUMER_PARTITION_BUDGET_LOW_WATERMARK", "1.2"),
        ];
        assert!(config(vars).partition_budget().is_err());
    }

    #[rstest]
    #[case::unset(&[], GovernorSettings::observing())]
    #[case::a_budget_with_adaptation_off(
        &[("INGESTION_GOVERNOR_LATENCY_BUDGET_MS", "3000")],
        GovernorSettings {
            latency_budget: Some(Duration::from_millis(3000)),
            ..GovernorSettings::observing()
        }
    )]
    #[case::adaptation_on(
        &[
            ("INGESTION_GOVERNOR_ADAPTATION", "on"),
            ("INGESTION_GOVERNOR_LATENCY_BUDGET_MS", "3000"),
            ("INGESTION_GOVERNOR_MIN_PERMITS_PER_WORKER", "2"),
            ("INGESTION_GOVERNOR_STEP_INTERVAL_MS", "100"),
            ("INGESTION_WORKER_CONCURRENT_BATCHES", "4"),
            ("INGESTION_REQUEST_SOFT_BUDGET_MS", "3001"),
        ],
        GovernorSettings {
            adaptation: Adaptation::On,
            latency_budget: Some(Duration::from_millis(3000)),
            min_permits_per_worker: 2,
            step_interval: Duration::from_millis(100),
        }
    )]
    fn valid_governor_settings_are_read(
        #[case] vars: &[(&str, &str)],
        #[case] expected: GovernorSettings,
    ) {
        assert_eq!(config(vars).governor_settings(), Ok(expected));
    }

    #[rstest]
    #[case::adaptation_on_without_a_budget(&[("INGESTION_GOVERNOR_ADAPTATION", "on")])]
    #[case::a_budget_at_the_soft_budget(&[
        ("INGESTION_GOVERNOR_LATENCY_BUDGET_MS", "3000"),
        ("INGESTION_REQUEST_SOFT_BUDGET_MS", "3000"),
    ])]
    #[case::a_budget_at_the_ack_timeout(&[("INGESTION_GOVERNOR_LATENCY_BUDGET_MS", "60000")])]
    #[case::no_floor(&[("INGESTION_GOVERNOR_MIN_PERMITS_PER_WORKER", "0")])]
    #[case::a_floor_above_the_per_worker_cap(&[
        ("INGESTION_GOVERNOR_MIN_PERMITS_PER_WORKER", "2"),
        ("INGESTION_WORKER_CONCURRENT_BATCHES", "1"),
    ])]
    #[case::a_step_interval_below_the_floor(&[("INGESTION_GOVERNOR_STEP_INTERVAL_MS", "99")])]
    #[case::adaptation_on_with_the_floor_at_the_cap(&[
        ("INGESTION_GOVERNOR_ADAPTATION", "on"),
        ("INGESTION_GOVERNOR_LATENCY_BUDGET_MS", "3000"),
    ])]
    fn invalid_governor_settings_are_rejected(#[case] vars: &[(&str, &str)]) {
        assert!(config(vars).governor_settings().is_err());
    }

    #[test]
    fn governor_adaptation_parses_on_and_off() {
        assert_eq!(Adaptation::from_str(" ON "), Ok(Adaptation::On));
        assert_eq!(Adaptation::from_str("off"), Ok(Adaptation::Off));
        assert!(Adaptation::from_str("true").is_err());
    }

    #[test]
    fn completion_granularity_parses_known_values() {
        assert_eq!(
            CompletionGranularity::from_str(" POLL "),
            Ok(CompletionGranularity::Poll)
        );
        assert_eq!(
            CompletionGranularity::from_str("group"),
            Ok(CompletionGranularity::Group)
        );
        assert!(CompletionGranularity::from_str("batch").is_err());
    }
}
