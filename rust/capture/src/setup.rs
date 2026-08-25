use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use axum::Router;
use common_ingestion_warnings::{
    observe_delivery, KafkaWarningEmitter, WarningEmitter, INGESTION_WARNINGS_EMITTER_ENABLED,
};
use common_kafka::config::KafkaConfig as WarningsKafkaConfig;
use common_kafka::kafka_producer::create_threaded_kafka_producer_no_ping;
use common_redis::RedisClient;
use metrics::gauge;
use tracing::{info, warn};

use crate::config::{CaptureMode, Config};
use crate::event_restrictions::{EventRestrictionService, Pipeline, RedisRestrictionsRepository};
use crate::global_rate_limiter::GlobalRateLimiter;
use crate::prometheus::setup_metrics_recorder;
use crate::quota_limiters::{
    is_exception_event, is_llm_event, is_survey_event, CaptureQuotaLimiter,
};
use crate::router;
use crate::router::BATCH_BODY_SIZE;
use crate::sinks::fallback::FallbackSink;
use crate::sinks::kafka::KafkaSink;
use crate::sinks::noop::NoOpSink;
use crate::sinks::print::PrintSink;
use crate::sinks::s3::S3Sink;
use crate::sinks::Event;
use limiters::overflow::OverflowLimiter;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, OVERFLOW_LIMITER_CACHE_KEY};
use limiters::token_dropper::TokenDropper;

pub struct LifecycleHandles {
    pub server: lifecycle::Handle,
    pub sink: Option<lifecycle::Handle>,
    pub advisory: Option<lifecycle::Handle>,
    pub event_restrictions: Option<lifecycle::Handle>,
    pub ingestion_warnings: Option<lifecycle::Handle>,
    pub v1_sinks: HashMap<crate::v1::sinks::SinkName, lifecycle::Handle>,
    pub readiness: lifecycle::ReadinessHandler,
    pub liveness: lifecycle::LivenessHandler,
}

pub fn register_components(manager: &mut lifecycle::Manager, config: &Config) -> LifecycleHandles {
    let server = manager.register(
        "server",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(60)),
    );

    let sink_opts =
        lifecycle::ComponentOptions::new().with_liveness_deadline(Duration::from_secs(30));

    let (sink, advisory) = if config.print_sink || config.noop_sink {
        (None, None)
    } else if config.s3_fallback_enabled {
        let kafka = manager.register("kafka-sink", sink_opts.clone().is_advisory(true));
        let s3 = manager.register("s3-sink", sink_opts.clone());
        (Some(s3), Some(kafka))
    } else {
        (
            Some(manager.register("kafka-sink", sink_opts.clone())),
            None,
        )
    };

    let event_restrictions =
        if config.event_restrictions_enabled && config.event_restrictions_redis_url.is_some() {
            Some(manager.register("event-restrictions", lifecycle::ComponentOptions::new()))
        } else {
            None
        };

    // Advisory: the warnings producer is best-effort, so a stalled or dead
    // producer must never gate pod liveness/readiness or trigger shutdown.
    let ingestion_warnings = if config.capture_ingestion_warnings_enabled {
        Some(
            manager.register(
                "ingestion-warnings",
                lifecycle::ComponentOptions::new()
                    .with_liveness_deadline(Duration::from_secs(30))
                    .is_advisory(true),
            ),
        )
    } else {
        None
    };

    let v1_sinks: HashMap<crate::v1::sinks::SinkName, lifecycle::Handle> =
        if !config.capture_v1_sinks.is_empty() {
            crate::v1::sinks::parse_sink_names(&config.capture_v1_sinks)
                .unwrap_or_else(|e| {
                    panic!(
                        "fatal: failed to parse CAPTURE_V1_SINKS='{}': {e:#}",
                        config.capture_v1_sinks
                    )
                })
                .into_iter()
                .map(|name| {
                    (
                        name,
                        manager.register(name.lifecycle_tag(), sink_opts.clone()),
                    )
                })
                .collect()
        } else {
            HashMap::new()
        };

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    LifecycleHandles {
        server,
        sink,
        advisory,
        event_restrictions,
        ingestion_warnings,
        v1_sinks,
        readiness,
        liveness,
    }
}

pub struct CaptureComponents {
    pub app: Router,
    pub server_handle: lifecycle::Handle,
    pub sink: Arc<dyn Event + Send + Sync>,
    pub v1_sink_router: Option<Arc<crate::v1::sinks::Router>>,
    pub event_restriction_service: Option<EventRestrictionService>,
    pub http1_header_read_timeout_ms: Option<u64>,
}

pub async fn build_components(
    config: Config,
    sink_env: HashMap<String, String>,
    handles: LifecycleHandles,
) -> CaptureComponents {
    let LifecycleHandles {
        server,
        sink: sink_handle,
        advisory: advisory_handle,
        event_restrictions: event_restrictions_handle,
        ingestion_warnings: ingestion_warnings_handle,
        v1_sinks: v1_sink_handles,
        readiness,
        liveness,
    } = handles;

    // Must come first: metrics emitted before the global recorder exists are
    // silently dropped, and its `role`/`capture_mode` labels are fixed here.
    let recorder_handle = config.export_prometheus.then(|| {
        setup_metrics_recorder(
            config.otel_service_name.clone(),
            config.capture_mode.as_tag(),
        )
    });

    let redis_client = Arc::new(
        RedisClient::with_config(
            config.redis_url.clone(),
            common_redis::CompressionConfig::disabled(),
            common_redis::RedisValueFormat::default(),
            if config.redis_response_timeout_ms == 0 {
                None
            } else {
                Some(Duration::from_millis(config.redis_response_timeout_ms))
            },
            if config.redis_connection_timeout_ms == 0 {
                None
            } else {
                Some(Duration::from_millis(config.redis_connection_timeout_ms))
            },
        )
        .await
        .expect("failed to create redis client"),
    );

    // Each global limiter gets its own Redis client, from the same source: the
    // dedicated rate-limiter Redis when GLOBAL_RATE_LIMIT_REDIS_URL is set,
    // otherwise the shared one. A client owns one MultiplexedConnection, and
    // each limiter drives its own tick loop against it under a per-command
    // timeout, so sharing one would let a slow drain on either limiter eat the
    // other's budget. Key prefixes already keep their counts apart; this keeps
    // their pipelines apart too. Neither is built unless its limiter is on, so
    // a deployment running neither opens no connection.
    let ai_byte_limit_enabled = ai_byte_limit_per_second(&config) > 0;
    let rate_limiter_redis = if config.global_rate_limit_enabled {
        Some(
            GlobalRateLimiter::build_redis_client(&config, redis_client.clone())
                .await
                .expect("failed to create rate limiter redis client"),
        )
    } else {
        None
    };
    let ai_byte_limiter_redis = if ai_byte_limit_enabled {
        Some(
            GlobalRateLimiter::build_redis_client(&config, redis_client.clone())
                .await
                .expect("failed to create AI byte limiter redis client"),
        )
    } else {
        None
    };

    // The dynamic custom-threshold refresh loop is owned by the common limiter:
    // when GLOBAL_RATE_LIMIT_CUSTOM_THRESHOLD_KEY is set, `build()` wires a Redis
    // source into the limiter, which spawns and manages the refresh task itself.
    let global_rate_limiter_token_distinctid = rate_limiter_redis.as_ref().map(|redis| {
        Arc::new(
            GlobalRateLimiter::new_token_distinct_id(&config, vec![redis.clone()])
                .expect("failed to create global rate limiter"),
        )
    });

    // add new "scoped" quota limiters here as new quota tracking buckets are added
    // to PostHog! Here a "scoped" limiter is one that should be INDEPENDENT of the
    // global billing limiter applied here to every event batch. You must supply the
    // QuotaResource type and a predicate function that will match events to be limited
    let quota_limiter =
        CaptureQuotaLimiter::new(&config, redis_client.clone(), Duration::from_secs(5))
            .add_scoped_limiter(QuotaResource::Exceptions, is_exception_event)
            .add_scoped_limiter(QuotaResource::Surveys, is_survey_event)
            .add_scoped_limiter(QuotaResource::LLMEvents, is_llm_event);

    // TODO: remove this once we have a billing limiter
    let token_dropper = config
        .drop_events_by_token_distinct_id
        .clone()
        .map(|k| TokenDropper::new(&k))
        .unwrap_or_default();

    // In Recordings capture mode, we unpack a batch of events, and then pack them back up into
    // a big blob and send to kafka all at once - so we should abort unpacking a batch if the data
    // size crosses the kafka limit. In the Events mode, we can unpack the batch and send each
    // event individually, so we should instead allow for some small multiple of our max compressed
    // body size to be unpacked. If a single event is still too big, we'll drop it at kafka send time.
    let event_payload_max_bytes = match config.capture_mode {
        CaptureMode::Events | CaptureMode::Ai | CaptureMode::Import => BATCH_BODY_SIZE * 5,
        CaptureMode::Recordings => config.kafka.kafka_producer_message_max_bytes as usize,
    };

    // Build the overflow limiters here (not inside the sink) so routing
    // policy lives in `router::State` alongside every other pipeline-level
    // decision. The kafka sink used to own these; after the refactor it is
    // a pure mechanism layer and reads `metadata.overflow_reason` that the
    // pipeline stamps upstream. See `router::State::overflow_limiter` and
    // `router::State::replay_overflow_limiter`.
    let overflow_limiter: Option<Arc<OverflowLimiter>> = if config.overflow_enabled {
        let partition = OverflowLimiter::new(
            config.overflow_per_second_limit,
            config.overflow_burst_limit,
            config.ingestion_force_overflow_by_token_distinct_id.clone(),
            config.overflow_preserve_partition_locality,
        );

        if config.export_prometheus {
            let partition = partition.clone();
            tokio::spawn(async move {
                partition.report_metrics("analytics").await;
            });
        }

        {
            // Keep the governor's per-key state from growing unbounded.
            let partition = partition.clone();
            tokio::spawn(async move {
                partition.clean_state().await;
            });
        }

        Some(Arc::new(partition))
    } else {
        None
    };

    let replay_overflow_limiter: Option<Arc<RedisLimiter>> = match config.capture_mode {
        CaptureMode::Recordings => Some(Arc::new(
            RedisLimiter::new(
                Duration::from_secs(5),
                redis_client.clone(),
                OVERFLOW_LIMITER_CACHE_KEY.to_string(),
                config.redis_key_prefix.clone(),
                QuotaResource::Replay,
                ServiceName::Capture,
            )
            .expect("failed to start replay overflow limiter"),
        )),
        _ => None,
    };

    let sink: Arc<dyn Event + Send + Sync> = Arc::from(
        create_sink(&config, sink_handle, advisory_handle)
            .await
            .expect("failed to create sink"),
    );
    let sink_for_flush = sink.clone();

    let event_restriction_service = if let Some(handle) = event_restrictions_handle {
        create_event_restriction_service(
            &config,
            handle,
            Pipeline::for_capture_mode(config.capture_mode),
        )
    } else {
        None
    };

    assert!(
        !config.kafka.capture_analytics_ai_events_topic.is_empty(),
        "invalid configuration: CAPTURE_ANALYTICS_AI_EVENTS_TOPIC must not be empty",
    );
    let ai_events_overflow_enabled = ai_events_overflow_valve(&config);
    info!(
        capture_analytics_ai_events_topic = %config.kafka.capture_analytics_ai_events_topic,
        capture_analytics_ai_events_overflow_topic = ?config.kafka.capture_analytics_ai_events_overflow_topic,
        ai_events_overflow_enabled,
        "AI events topic routing"
    );

    // The AI lane gets its own limiter instance with the same knobs: the
    // governor state (per-`token:distinct_id` budgets) is what must stay
    // isolated, so analytics volume can never push a key's AI events into
    // AI overflow and AI volume never burns the analytics budget.
    let ai_events_overflow_limiter: Option<Arc<OverflowLimiter>> =
        if config.overflow_enabled && ai_events_overflow_enabled {
            let limiter = OverflowLimiter::new(
                config.overflow_per_second_limit,
                config.overflow_burst_limit,
                config.ingestion_force_overflow_by_token_distinct_id.clone(),
                config.overflow_preserve_partition_locality,
            );

            if config.export_prometheus {
                let limiter = limiter.clone();
                tokio::spawn(async move {
                    limiter.report_metrics("ai").await;
                });
            }

            {
                // Keep the governor's per-key state from growing unbounded.
                let limiter = limiter.clone();
                tokio::spawn(async move {
                    limiter.clean_state().await;
                });
            }

            Some(Arc::new(limiter))
        } else {
            None
        };

    // Unlike the governor-backed overflow limiters above, this one needs no
    // metrics or state-cleanup tasks of its own: the global rate limiter owns
    // its background tick loop, its cache eviction, and its own metric series
    // (scoped `<mode>_ai_bytes`).
    if ai_byte_limit_enabled {
        warn_if_ai_byte_budget_below_max_event(&config);
    }
    warn_if_ai_ceiling_exceeds_producer_cap(&config);
    let ai_byte_rate_limiter = ai_byte_limiter_redis.as_ref().map(|redis| {
        Arc::new(
            GlobalRateLimiter::new_ai_bytes(&config, vec![redis.clone()])
                .expect("failed to create AI byte rate limiter"),
        )
    });

    let v1_sink_router = if !config.capture_v1_sinks.is_empty() {
        Some(
            create_v1_sink_router(&config, &sink_env, v1_sink_handles)
                .unwrap_or_else(|e| panic!("fatal: v1 sink router creation failed: {e:#}")),
        )
    } else {
        None
    };

    let ingestion_warning_emitter =
        create_ingestion_warning_emitter(&config, ingestion_warnings_handle).await;

    let app = router::router(
        crate::time::SystemTime {},
        readiness,
        liveness,
        sink,
        redis_client,
        global_rate_limiter_token_distinctid,
        quota_limiter,
        token_dropper,
        event_restriction_service.clone(),
        recorder_handle,
        config.capture_mode,
        config.concurrency_limit,
        event_payload_max_bytes,
        config.enable_historical_rerouting,
        config.historical_rerouting_threshold_days,
        config.is_mirror_deploy,
        config.verbose_sample_percent,
        config.ai_max_sum_of_parts_bytes,
        config.ai_max_event_bytes,
        config.body_chunk_read_timeout_ms,
        config.body_read_chunk_size_kb,
        config.capture_v1_max_compressed_body_bytes,
        config.capture_v1_max_decompressed_body_bytes,
        overflow_limiter,
        ai_events_overflow_limiter,
        ai_byte_rate_limiter,
        replay_overflow_limiter,
        v1_sink_router.clone(),
        config.capture_v1_scatter_gather_min_batch,
        config.ai_gateway_signing_secret.clone(),
        ai_events_overflow_enabled,
        ingestion_warning_emitter,
    );

    info!(
        "config: is_mirror_deploy == {:?} ; log_level == {:?}",
        config.is_mirror_deploy, config.log_level
    );

    CaptureComponents {
        app,
        server_handle: server,
        sink: sink_for_flush,
        v1_sink_router,
        event_restriction_service,
        http1_header_read_timeout_ms: config.http1_header_read_timeout_ms,
    }
}

/// The AI overflow valve: an unset or empty
/// `CAPTURE_ANALYTICS_AI_EVENTS_OVERFLOW_TOPIC` means AI events never
/// overflow. Import mode refuses an armed valve at boot: non-AI import events
/// can't overflow because historical rerouting takes precedence no matter how
/// the deployment is configured, but nothing structural protects AI
/// imports, so an armed valve would silently break the imports-never-overflow
/// guarantee.
fn ai_events_overflow_valve(config: &Config) -> bool {
    let armed = config
        .kafka
        .capture_analytics_ai_events_overflow_topic
        .as_deref()
        .is_some_and(|topic| !topic.is_empty());
    assert!(
        !(armed && matches!(config.capture_mode, CaptureMode::Import)),
        "invalid configuration: CAPTURE_ANALYTICS_AI_EVENTS_OVERFLOW_TOPIC must be unset in import mode; imports must never overflow"
    );
    armed
}

/// The AI byte budget this deployment enforces, or `0` to skip building the
/// limiter entirely. Import is exempt — backfills are never throttled, matching
/// the other limiters — and not building the limiter is the whole exemption, so
/// neither pipeline's charge step needs capture-mode awareness of its own.
fn ai_byte_limit_per_second(config: &Config) -> u64 {
    if matches!(config.capture_mode, CaptureMode::Import) {
        return 0;
    }
    config.ai_byte_limit_per_second
}

/// Warns when the per-event ceiling is at or above what the producer will
/// send. Above the cap the ceiling stops being a guard: capture reads the
/// body, builds the event, and the producer refuses it anyway, so the only
/// thing the higher ceiling buys is a later failure. Both sides come from
/// config, so the check stays correct when either knob moves.
fn ai_ceiling_exceeds_producer_cap(config: &Config) -> bool {
    let ceiling = config.ai_max_event_bytes;
    // `0` disables the ceiling, so there is no ordering to be wrong about.
    ceiling != 0 && ceiling >= config.kafka.kafka_producer_message_max_bytes as u64
}

fn warn_if_ai_ceiling_exceeds_producer_cap(config: &Config) {
    if ai_ceiling_exceeds_producer_cap(config) {
        warn!(
            ai_max_event_bytes = config.ai_max_event_bytes,
            kafka_producer_message_max_bytes = config.kafka.kafka_producer_message_max_bytes,
            "AI_MAX_EVENT_BYTES is at or above KAFKA_PRODUCER_MESSAGE_MAX_BYTES; \
             events between the producer cap and the ceiling are built and then \
             refused by the producer"
        );
    }
}

/// Warns when a token sending full-size AI events would be limited on nearly
/// every one of them, because the window budget cannot fit even a single event
/// at the deployment's ceiling. Both sides come from config, so the check stays
/// correct when either knob moves.
fn warn_if_ai_byte_budget_below_max_event(config: &Config) {
    let max_event_bytes = config.ai_max_event_bytes;
    if max_event_bytes == 0 {
        return;
    }
    let window_secs = config.global_rate_limit_window_interval_secs;
    let window_budget = ai_byte_limit_per_second(config).saturating_mul(window_secs);
    if window_budget < max_event_bytes {
        warn!(
            ai_byte_limit_per_second = config.ai_byte_limit_per_second,
            window_secs,
            window_budget,
            max_event_bytes,
            "AI_BYTE_LIMIT_PER_SECOND yields a window budget below AI_MAX_EVENT_BYTES; \
             a token sending full-size events will be limited on nearly every event"
        );
    }
}

/// Builds the v1 sink router. The dedicated AI topics are
/// deployment-level config (`CAPTURE_ANALYTICS_AI_EVENTS_TOPIC` and `CAPTURE_ANALYTICS_AI_EVENTS_OVERFLOW_TOPIC`),
/// so they are injected into every sink config here; the overwrite is
/// unconditional so a stray per-sink `TOPIC_AI`/`TOPIC_AI_OVERFLOW` env var
/// cannot diverge from the shared policy.
fn create_v1_sink_router(
    config: &Config,
    sink_env: &HashMap<String, String>,
    handles: HashMap<crate::v1::sinks::SinkName, lifecycle::Handle>,
) -> anyhow::Result<Arc<crate::v1::sinks::Router>> {
    let mut sinks_cfg = crate::v1::sinks::load_sinks_from(&config.capture_v1_sinks, sink_env)
        .context("failed to parse CAPTURE_V1_SINKS")?;
    sinks_cfg
        .validate()
        .context("v1 sink config validation failed")?;

    for cfg in sinks_cfg.configs.values_mut() {
        cfg.kafka.topic_ai = config.kafka.capture_analytics_ai_events_topic.clone();
        cfg.kafka.topic_ai_overflow = config
            .kafka
            .capture_analytics_ai_events_overflow_topic
            .clone();
    }

    let mut sink_map: HashMap<crate::v1::sinks::SinkName, Box<dyn crate::v1::sinks::sink::Sink>> =
        HashMap::new();

    for (name, cfg) in sinks_cfg.configs {
        let handle = handles
            .get(&name)
            .cloned()
            .with_context(|| format!("missing lifecycle handle for v1 sink '{name}'"))?;

        let producer = crate::v1::sinks::kafka::producer::KafkaProducer::new(
            name,
            &cfg.kafka,
            handle.clone(),
            config.capture_mode.as_tag(),
        )
        .with_context(|| format!("failed to create v1 kafka producer for sink '{name}'"))?;

        let kafka_sink = crate::v1::sinks::kafka::sink::KafkaSink::new(
            name,
            Arc::new(producer),
            cfg,
            config.capture_mode,
            handle,
        );
        sink_map.insert(name, Box::new(kafka_sink));
    }

    let router = crate::v1::sinks::Router::new(sinks_cfg.default, sink_map);
    info!(
        sinks = config.capture_v1_sinks.as_str(),
        "V1 sink router initialized"
    );
    Ok(Arc::new(router))
}

async fn create_sink(
    config: &Config,
    sink_handle: Option<lifecycle::Handle>,
    advisory_handle: Option<lifecycle::Handle>,
) -> anyhow::Result<Box<dyn Event + Send + Sync>> {
    if config.print_sink {
        Ok(Box::new(PrintSink {}))
    } else if config.noop_sink {
        info!("NoOpSink enabled, events will be silently dropped");
        Ok(Box::new(NoOpSink::new()))
    } else if config.s3_fallback_enabled {
        let s3_handle = sink_handle.expect("sink lifecycle handle required for S3 fallback");
        let kafka_handle = advisory_handle.expect("kafka advisory handle required for fallback");

        let kafka_sink = KafkaSink::new(config.kafka.clone(), Some(kafka_handle.clone()))
            .await
            .context("failed to start Kafka sink")?;

        let s3_sink = S3Sink::new(
            config
                .s3_fallback_bucket
                .clone()
                .expect("S3 bucket required when fallback enabled"),
            config.s3_fallback_prefix.clone(),
            config.s3_fallback_endpoint.clone(),
            s3_handle,
        )
        .await
        .expect("failed to create S3 sink");

        Ok(Box::new(FallbackSink::new_with_advisory(
            kafka_sink,
            s3_sink,
            kafka_handle,
        )))
    } else {
        let kafka_sink = KafkaSink::new(config.kafka.clone(), sink_handle)
            .await
            .context("failed to start Kafka sink")?;

        Ok(Box::new(kafka_sink))
    }
}

// Fixed fire-and-forget tuning for the warnings producer. These are
// deliberately not env-configurable: they define the "a warning is worth less
// than the cost of retrying it" contract, not knobs an operator should turn.
// (Queue size in MiB and the per-message byte ceiling stay env-configurable in
// `Config` because they're capacity/safety limits, not the delivery policy.)
const WARNINGS_KAFKA_CLIENT_ID: &str = "capture-ingestion-warnings";
// rdkafka "acks": leader ack only, trading durability for latency.
const WARNINGS_KAFKA_ACKS: &str = "1";
// rdkafka "retries": never retry a dropped warning.
const WARNINGS_KAFKA_RETRIES: u32 = 0;
// Small batching window, in ms.
const WARNINGS_KAFKA_LINGER_MS: u32 = 100;
// Bound the in-flight local backlog by message count.
const WARNINGS_KAFKA_QUEUE_MESSAGES: u32 = 10_000;
// Drop a message not delivered within this many ms.
const WARNINGS_KAFKA_MESSAGE_TIMEOUT_MS: u32 = 5_000;

/// Build the dedicated, warnings-only Kafka config. Reuses only the
/// destination cluster (`hosts`/`tls`) from capture's main Kafka config;
/// everything else is the fixed fire-and-forget policy (client id, acks,
/// retries, linger, queue depth, message timeout) plus the two tunable limits
/// (`queue_mib`, `message_max_bytes`). `..Default::default()` supplies the
/// shared-crate defaults (compression codec, empty client rack) and — critically
/// — leaves every opt-in producer tuning knob at `None`, so warnings never
/// inherit the main event producer's batching/idempotence tuning.
fn build_warnings_kafka_config(
    kafka_hosts: String,
    kafka_tls: bool,
    queue_mib: u32,
    message_max_bytes: u32,
) -> WarningsKafkaConfig {
    WarningsKafkaConfig {
        kafka_hosts,
        kafka_tls,
        kafka_client_id: WARNINGS_KAFKA_CLIENT_ID.to_string(),
        kafka_producer_acks: Some(WARNINGS_KAFKA_ACKS.to_string()),
        kafka_producer_retries: Some(WARNINGS_KAFKA_RETRIES),
        kafka_producer_linger_ms: WARNINGS_KAFKA_LINGER_MS,
        kafka_producer_queue_messages: WARNINGS_KAFKA_QUEUE_MESSAGES,
        kafka_message_timeout_ms: WARNINGS_KAFKA_MESSAGE_TIMEOUT_MS,
        kafka_producer_queue_mib: queue_mib,
        kafka_producer_message_max_bytes: Some(message_max_bytes),
        ..Default::default()
    }
}

/// Build the optional v2 ingestion warnings emitter. Best-effort by contract:
/// any misconfiguration or producer-creation failure logs and returns `None`
/// (capture runs without warnings) instead of failing startup. The producer
/// is a `common_kafka` `ThreadedProducer`, built via
/// `common_kafka::kafka_producer::create_threaded_kafka_producer_no_ping` from a
/// dedicated, warnings-only `common_kafka::config::KafkaConfig` (fire-and-forget
/// acks/retries, a small queue) with `observe_delivery` as its delivery
/// callback. Its destination (hosts/TLS/topic) comes entirely from
/// `CAPTURE_INGESTION_WARNINGS_KAFKA_{HOSTS,TLS,TOPIC}`; it no longer borrows
/// anything from capture's main event config (the v0 `KAFKA_*` block), so
/// retiring that block cannot silently misroute or mute it. When built, a
/// background task heartbeats the advisory lifecycle handle, sweeps the
/// throttle's per-key state, and flushes the producer once at shutdown.
///
/// Uses the no-ping constructor so an unreachable warnings cluster costs
/// capture nothing at boot: no 15s metadata fetch on the startup path, and no
/// pod that serves events for hours with warnings permanently off because the
/// cluster happened to be down the moment it started. librdkafka reconnects on
/// its own, so read `delivered`/`delivery_failed` to judge whether warnings are
/// landing — the enabled gauge only reports that the emitter exists.
async fn create_ingestion_warning_emitter(
    config: &Config,
    handle: Option<lifecycle::Handle>,
) -> Option<Arc<dyn WarningEmitter>> {
    if !config.capture_ingestion_warnings_enabled {
        return None;
    }

    // Past this point the operator asked for warnings, so every exit reports
    // through the gauge with the reason it bailed. Leaving it unset above keeps
    // "disabled" distinct from "enabled but broken".
    let report_disabled = |reason: &'static str| {
        gauge!(INGESTION_WARNINGS_EMITTER_ENABLED, "reason" => reason).set(0.0)
    };

    let hosts = config.capture_ingestion_warnings_kafka_hosts.clone();
    let topic = config.capture_ingestion_warnings_kafka_topic.clone();
    let tls = config.capture_ingestion_warnings_kafka_tls;

    if hosts.is_empty() {
        warn!(
            "ingestion warnings enabled but CAPTURE_INGESTION_WARNINGS_KAFKA_HOSTS is unset; \
             emitter disabled"
        );
        report_disabled("hosts_unset");
        return None;
    }

    if topic.is_empty() {
        warn!(
            "ingestion warnings enabled but CAPTURE_INGESTION_WARNINGS_KAFKA_TOPIC is unset; \
             emitter disabled"
        );
        report_disabled("topic_unset");
        return None;
    }

    let Some(handle) = handle else {
        warn!(
            "ingestion warnings enabled but no lifecycle handle was registered; emitter disabled"
        );
        report_disabled("no_handle");
        return None;
    };

    let warnings_kafka_config = build_warnings_kafka_config(
        hosts,
        tls,
        config.capture_ingestion_warnings_kafka_queue_mib,
        config.capture_ingestion_warnings_kafka_message_max_bytes,
    );

    let producer = match create_threaded_kafka_producer_no_ping(
        &warnings_kafka_config,
        handle.clone(),
        observe_delivery,
    ) {
        Ok(producer) => producer,
        Err(e) => {
            tracing::error!(
                "failed to create ingestion warnings producer, emitter disabled: {e:#}"
            );
            report_disabled("producer_create_failed");
            return None;
        }
    };

    let emitter = Arc::new(KafkaWarningEmitter::new(producer, topic.clone()));

    let emitter_bg = emitter.clone();
    tokio::spawn(async move {
        let mut heartbeat = tokio::time::interval(Duration::from_secs(10));
        let mut sweep = tokio::time::interval(Duration::from_secs(60));
        loop {
            tokio::select! {
                _ = heartbeat.tick() => handle.report_healthy(),
                _ = sweep.tick() => emitter_bg.sweep_throttle(),
                _ = handle.shutdown_recv() => break,
            }
        }
        // Advisory flush: rdkafka flush blocks, so keep it off the async
        // workers. Dropping the handle after shutdown signals completion.
        let flush_result = tokio::task::spawn_blocking(move || {
            emitter_bg.flush(Duration::from_secs(2));
        })
        .await;
        if let Err(e) = flush_result {
            warn!("ingestion warnings flush task panicked: {e}");
        }
    });

    gauge!(INGESTION_WARNINGS_EMITTER_ENABLED, "reason" => "ok").set(1.0);
    info!(topic = topic.as_str(), "ingestion warnings emitter enabled");
    Some(emitter)
}

fn create_event_restriction_service(
    config: &Config,
    handle: lifecycle::Handle,
    pipelines: Vec<Pipeline>,
) -> Option<EventRestrictionService> {
    if !config.event_restrictions_enabled {
        return None;
    }

    let Some(ref redis_url) = config.event_restrictions_redis_url else {
        warn!("Event restrictions enabled but EVENT_RESTRICTIONS_REDIS_URL not set");
        return None;
    };

    let pipelines_for_log = pipelines.clone();
    let service = EventRestrictionService::new(
        pipelines,
        Duration::from_secs(config.event_restrictions_fail_open_after_secs),
    );

    let service_clone = service.clone();
    let refresh_interval = Duration::from_secs(config.event_restrictions_refresh_interval_secs);

    let redis_url = redis_url.clone();
    let response_timeout = if config.redis_response_timeout_ms == 0 {
        None
    } else {
        Some(Duration::from_millis(config.redis_response_timeout_ms))
    };
    let connection_timeout = if config.redis_connection_timeout_ms == 0 {
        None
    } else {
        Some(Duration::from_millis(config.redis_connection_timeout_ms))
    };

    tokio::spawn(async move {
        service_clone
            .start_refresh_task(
                || {
                    let url = redis_url.clone();
                    async move {
                        let repo = RedisRestrictionsRepository::new(
                            url,
                            response_timeout,
                            connection_timeout,
                        )
                        .await?;
                        let result: Arc<
                            dyn crate::event_restrictions::EventRestrictionsRepository,
                        > = Arc::new(repo);
                        Ok(result)
                    }
                },
                refresh_interval,
                handle,
            )
            .await;
    });

    info!(
        pipelines = ?pipelines_for_log,
        refresh_interval_secs = config.event_restrictions_refresh_interval_secs,
        fail_open_after_secs = config.event_restrictions_fail_open_after_secs,
        "Event restrictions enabled"
    );

    Some(service)
}

#[cfg(test)]
mod tests {
    use super::*;
    use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};
    use rstest::rstest;
    use std::collections::HashMap;

    fn warnings_config(enabled: bool, hosts: &str, topic: &str) -> Config {
        let cfg_env: HashMap<String, String> = [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", "events"),
            ("KAFKA_HOSTS", "v0-broker:9092"),
            ("KAFKA_TOPIC", "events_plugin_ingestion"),
            (
                "CAPTURE_INGESTION_WARNINGS_ENABLED",
                if enabled { "true" } else { "false" },
            ),
            ("CAPTURE_INGESTION_WARNINGS_KAFKA_HOSTS", hosts),
            ("CAPTURE_INGESTION_WARNINGS_KAFKA_TOPIC", topic),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        envconfig::Envconfig::init_from_hashmap(&cfg_env).expect("test config")
    }

    /// The emitter gauge as `(reason, value)`, or `None` if never emitted.
    fn emitter_enabled_gauge(snapshotter: &Snapshotter) -> Option<(String, f64)> {
        snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .find(|(ckey, _, _, _)| ckey.key().name() == INGESTION_WARNINGS_EMITTER_ENABLED)
            .map(|(ckey, _, _, value)| {
                let reason = ckey
                    .key()
                    .labels()
                    .find(|label| label.key() == "reason")
                    .map(|label| label.value().to_string())
                    .expect("every emission must carry a reason label");
                match value {
                    DebugValue::Gauge(v) => (reason, v.into_inner()),
                    other => panic!("expected a gauge, got {other:?}"),
                }
            })
    }

    /// Run `f` with metrics captured locally. The recorder is thread-scoped, so
    /// callers drive futures on this thread via `current_thread_runtime`.
    fn capture_metrics<T>(f: impl FnOnce() -> T) -> (T, Snapshotter) {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let out = metrics::with_local_recorder(&recorder, f);
        (out, snapshotter)
    }

    fn current_thread_runtime() -> tokio::runtime::Runtime {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("runtime")
    }

    struct AiValveInput {
        capture_mode: &'static str,
        overflow_topic: Option<&'static str>,
    }

    fn ai_valve_config(input: &AiValveInput) -> Config {
        let mut cfg_env: HashMap<String, String> = [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", input.capture_mode),
            ("KAFKA_HOSTS", "localhost:9092"),
            ("KAFKA_TOPIC", "events_plugin_ingestion"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        if let Some(topic) = input.overflow_topic {
            cfg_env.insert(
                "CAPTURE_ANALYTICS_AI_EVENTS_OVERFLOW_TOPIC".to_string(),
                topic.to_string(),
            );
        }
        envconfig::Envconfig::init_from_hashmap(&cfg_env).expect("test config")
    }

    #[rstest]
    #[case::events_set(
        AiValveInput {
            capture_mode: "events",
            overflow_topic: Some("events_plugin_ingestion_ai_overflow"),
        },
        true
    )]
    #[case::events_unset(
        AiValveInput {
            capture_mode: "events",
            overflow_topic: None,
        },
        false
    )]
    #[case::import_unset(
        AiValveInput {
            capture_mode: "import",
            overflow_topic: None,
        },
        false
    )]
    #[case::import_empty(
        AiValveInput {
            capture_mode: "import",
            overflow_topic: Some(""),
        },
        false
    )]
    fn ai_events_overflow_valve_arms_only_on_a_set_topic(
        #[case] input: AiValveInput,
        #[case] expected_armed: bool,
    ) {
        assert_eq!(
            ai_events_overflow_valve(&ai_valve_config(&input)),
            expected_armed
        );
    }

    /// Signature shared by the limiter constructors under test.
    type LimiterBuilder = fn(
        &Config,
        Vec<Arc<dyn common_redis::Client + Send + Sync>>,
    ) -> anyhow::Result<GlobalRateLimiter>;

    /// A zero window gives every bucket an infinite leak rate, so the limiter
    /// admits everything. Building one must fail at boot rather than run as a
    /// limiter that never limits.
    #[rstest]
    #[case::ai_bytes(GlobalRateLimiter::new_ai_bytes)]
    #[case::token_distinct_id(GlobalRateLimiter::new_token_distinct_id)]
    fn limiters_reject_a_zero_window(#[case] build: LimiterBuilder) {
        let cfg_env: HashMap<String, String> = [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", "events"),
            ("KAFKA_HOSTS", "localhost:9092"),
            ("KAFKA_TOPIC", "events_plugin_ingestion"),
            ("GLOBAL_RATE_LIMIT_WINDOW_INTERVAL_SECS", "0"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        let config: Config =
            envconfig::Envconfig::init_from_hashmap(&cfg_env).expect("test config");

        // `GlobalRateLimiter` is not `Debug`, so unwrap the error by hand.
        let err = match build(&config, vec![]) {
            Ok(_) => panic!("a zero window must not build a limiter"),
            Err(err) => err,
        };
        assert!(
            err.to_string()
                .contains("GLOBAL_RATE_LIMIT_WINDOW_INTERVAL_SECS"),
            "the error must name the offending setting, got: {err}"
        );
    }

    #[test]
    #[should_panic(expected = "imports must never overflow")]
    fn ai_events_overflow_valve_rejects_armed_valve_in_import_mode() {
        ai_events_overflow_valve(&ai_valve_config(&AiValveInput {
            capture_mode: "import",
            overflow_topic: Some("events_plugin_ingestion_ai_overflow"),
        }));
    }

    #[test]
    fn create_v1_sink_router_fails_on_invalid_config() {
        let cfg_env: HashMap<String, String> = [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", "events"),
            ("KAFKA_HOSTS", "localhost:9092"),
            ("KAFKA_TOPIC", "events_plugin_ingestion"),
            ("CAPTURE_V1_SINKS", "msk"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        let config: Config =
            envconfig::Envconfig::init_from_hashmap(&cfg_env).expect("test config");

        let mut manager = lifecycle::Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .build();
        let handles: HashMap<crate::v1::sinks::SinkName, lifecycle::Handle> =
            crate::v1::sinks::parse_sink_names(&config.capture_v1_sinks)
                .unwrap()
                .into_iter()
                .map(|name| {
                    (
                        name,
                        manager.register(name.lifecycle_tag(), lifecycle::ComponentOptions::new()),
                    )
                })
                .collect();

        let err = create_v1_sink_router(&config, &HashMap::new(), handles)
            .err()
            .expect("should fail with invalid config");
        let msg = format!("{err:#}");
        assert!(
            msg.contains("msk"),
            "error should name the failing sink: {msg}"
        );
    }

    #[test]
    fn warnings_kafka_config_is_isolated_from_main_producer_tuning() {
        let cfg = build_warnings_kafka_config("broker:9092".to_string(), true, 16, 1_048_576);

        // Reuses only the destination cluster from the main config.
        assert_eq!(cfg.kafka_hosts, "broker:9092");
        assert!(cfg.kafka_tls);

        // Fixed fire-and-forget policy (not env-configurable).
        assert_eq!(cfg.kafka_client_id, WARNINGS_KAFKA_CLIENT_ID);
        assert_eq!(
            cfg.kafka_producer_acks.as_deref(),
            Some(WARNINGS_KAFKA_ACKS)
        );
        assert_eq!(cfg.kafka_producer_retries, Some(WARNINGS_KAFKA_RETRIES));
        assert_eq!(cfg.kafka_producer_linger_ms, WARNINGS_KAFKA_LINGER_MS);
        assert_eq!(
            cfg.kafka_producer_queue_messages,
            WARNINGS_KAFKA_QUEUE_MESSAGES
        );
        assert_eq!(
            cfg.kafka_message_timeout_ms,
            WARNINGS_KAFKA_MESSAGE_TIMEOUT_MS
        );

        // The two tunable capacity/safety limits pass through unchanged.
        assert_eq!(cfg.kafka_producer_queue_mib, 16);
        assert_eq!(cfg.kafka_producer_message_max_bytes, Some(1_048_576));

        // Critically: none of the main event producer's opt-in tuning leaks in
        // — `..Default::default()` must leave every WarpStream knob at `None`.
        assert_eq!(cfg.kafka_producer_batch_size, None);
        assert_eq!(cfg.kafka_producer_batch_num_messages, None);
        assert_eq!(cfg.kafka_producer_enable_idempotence, None);
        assert_eq!(
            cfg.kafka_producer_max_in_flight_requests_per_connection,
            None
        );
        assert_eq!(cfg.kafka_producer_topic_metadata_refresh_interval_ms, None);
        assert_eq!(cfg.kafka_producer_sticky_partitioning_linger_ms, None);
        assert_eq!(cfg.kafka_producer_partitioner, None);
    }

    #[tokio::test]
    async fn ingestion_warnings_emitter_does_not_consult_v0_kafka_block() {
        // Regression guard for the v0 fallback removal: with warnings enabled but
        // no dedicated hosts, the emitter must stay disabled rather than reuse the
        // v0 KAFKA_HOSTS / KAFKA_CLIENT_INGESTION_WARNING_TOPIC block. If the
        // fallback were still live, it would build a producer against v0-broker.
        let cfg_env: HashMap<String, String> = [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", "events"),
            ("KAFKA_HOSTS", "v0-broker:9092"),
            ("KAFKA_TOPIC", "events_plugin_ingestion"),
            ("KAFKA_CLIENT_INGESTION_WARNING_TOPIC", "v0-warnings-topic"),
            ("CAPTURE_INGESTION_WARNINGS_ENABLED", "true"),
            // CAPTURE_INGESTION_WARNINGS_KAFKA_HOSTS deliberately left unset.
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        let config: Config =
            envconfig::Envconfig::init_from_hashmap(&cfg_env).expect("test config");

        // The v0 block is populated, so a live fallback would have hosts to use;
        // the dedicated hosts are empty, which is the only thing that should count.
        assert_eq!(config.kafka.kafka_hosts, "v0-broker:9092");
        assert!(config.capture_ingestion_warnings_kafka_hosts.is_empty());

        let emitter = create_ingestion_warning_emitter(&config, None).await;
        assert!(
            emitter.is_none(),
            "emitter must stay disabled on empty dedicated hosts, not fall back to KAFKA_HOSTS"
        );
    }

    #[tokio::test]
    async fn disabled_emitter_with_live_handle_does_not_shut_capture_down() {
        // `register_components` moves the warnings handle in here and keeps no
        // clone, so bailing out early drops the last reference and fires
        // `ComponentEvent::Died`. Removing the v0 fallback is what makes that
        // reachable in production: a pod told to emit warnings but given no
        // dedicated hosts now takes this path on every start. Warnings are
        // best-effort, so it has to cost capture nothing.
        let cfg_env: HashMap<String, String> = [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", "events"),
            ("KAFKA_HOSTS", "v0-broker:9092"),
            ("KAFKA_TOPIC", "events_plugin_ingestion"),
            ("CAPTURE_INGESTION_WARNINGS_ENABLED", "true"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        let config: Config =
            envconfig::Envconfig::init_from_hashmap(&cfg_env).expect("test config");

        let shutdown = tokio_util::sync::CancellationToken::new();
        let mut manager = lifecycle::Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .with_shutdown_token(shutdown.clone())
            .build();
        // Mirrors the registration in `register_components`.
        let handle = manager.register(
            "ingestion-warnings",
            lifecycle::ComponentOptions::new()
                .with_liveness_deadline(Duration::from_secs(30))
                .is_advisory(true),
        );
        let server = manager.register("server", lifecycle::ComponentOptions::new());
        let _guard = manager.monitor_background();

        let emitter = create_ingestion_warning_emitter(&config, Some(handle)).await;
        assert!(emitter.is_none(), "emitter must stay disabled");

        // Long enough for a Died-driven cancel to have landed.
        tokio::time::sleep(Duration::from_millis(300)).await;
        assert!(
            !shutdown.is_cancelled(),
            "a disabled warnings emitter must not initiate capture shutdown"
        );
        assert!(!server.is_shutting_down(), "capture must still be serving");
    }

    /// A blank output topic makes `create_sink` refuse to boot in every capture
    /// mode — the misconfig fails fast at startup (via the `OutputRegistry`
    /// completeness check inside `KafkaSink::new`) rather than at first produce.
    #[rstest::rstest]
    #[case(CaptureMode::Events)]
    #[case(CaptureMode::Recordings)]
    #[case(CaptureMode::Ai)]
    #[case(CaptureMode::Import)]
    #[tokio::test]
    async fn create_sink_refuses_boot_on_missing_output_topic(#[case] mode: CaptureMode) {
        let cfg_env: HashMap<String, String> = [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", mode.as_tag()),
            ("KAFKA_HOSTS", "localhost:9092"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        let mut config: Config =
            envconfig::Envconfig::init_from_hashmap(&cfg_env).expect("test config");
        config.kafka.outputs_completeness_check_enabled = true;
        config.kafka.kafka_dlq_topic = String::new();

        let err = create_sink(&config, None, None)
            .await
            .err()
            .expect("boot must be refused when an output topic is empty");
        let msg = format!("{err:#}");
        assert!(
            msg.contains("dlq"),
            "error should name the missing output: {msg}"
        );

        // The default: with the check off, the same blank topic boots (and
        // would fail at first produce instead).
        config.kafka.outputs_completeness_check_enabled = false;
        create_sink(&config, None, None)
            .await
            .expect("boot must proceed when the completeness check is disabled");
    }

    /// The ceiling only guards anything while it sits under the producer's cap.
    /// A deployment that raises the producer keeps its headroom; one that never
    /// touched it gets told the default is too high for its broker.
    #[rstest::rstest]
    #[case::default_ceiling_on_a_default_producer(8_388_608, 1_000_000, true)]
    #[case::default_ceiling_under_a_raised_producer(8_388_608, 10_485_760, false)]
    #[case::equal_still_warns(1_000_000, 1_000_000, true)]
    #[case::disabled_ceiling_never_warns(0, 1_000_000, false)]
    fn ai_ceiling_is_checked_against_the_producer_cap(
        #[case] ceiling: u64,
        #[case] producer_cap: u32,
        #[case] expected: bool,
    ) {
        let cfg_env: HashMap<String, String> = [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", "ai"),
            ("KAFKA_HOSTS", "localhost:9092"),
            ("KAFKA_TOPIC", "events_plugin_ingestion_ai"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        let mut config: Config =
            envconfig::Envconfig::init_from_hashmap(&cfg_env).expect("test config");
        config.ai_max_event_bytes = ceiling;
        config.kafka.kafka_producer_message_max_bytes = producer_cap;

        assert_eq!(ai_ceiling_exceeds_producer_cap(&config), expected);
    }

    /// Import deployments never build the AI byte limiter, however the knob is
    /// set — that omission is the entire import exemption, so a rate leaking
    /// through here would start throttling backfills.
    #[rstest::rstest]
    #[case::events_keeps_the_configured_rate(CaptureMode::Events, 5_000, 5_000)]
    #[case::ai_keeps_the_configured_rate(CaptureMode::Ai, 5_000, 5_000)]
    #[case::import_is_exempt(CaptureMode::Import, 5_000, 0)]
    #[case::unset_stays_unset(CaptureMode::Events, 0, 0)]
    fn ai_byte_limit_per_second_by_mode(
        #[case] mode: CaptureMode,
        #[case] configured: u64,
        #[case] expected: u64,
    ) {
        let cfg_env: HashMap<String, String> = [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", mode.as_tag()),
            ("KAFKA_HOSTS", "localhost:9092"),
        ]
        .into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        let mut config: Config =
            envconfig::Envconfig::init_from_hashmap(&cfg_env).expect("test config");
        config.ai_byte_limit_per_second = configured;

        assert_eq!(ai_byte_limit_per_second(&config), expected);
    }

    /// Absent gauge means warnings are off on purpose; `0` means an operator
    /// asked for them and we could not build them. `reason` says which.
    #[rstest]
    #[case::off_on_purpose(false, "", "", None)]
    #[case::hosts_unset(true, "", "", Some("hosts_unset"))]
    #[case::topic_unset(true, "broker:9092", "", Some("topic_unset"))]
    #[case::no_handle(true, "broker:9092", "client_ingestion_warning", Some("no_handle"))]
    fn emitter_gauge_reports_why_warnings_are_off(
        #[case] enabled: bool,
        #[case] hosts: &str,
        #[case] topic: &str,
        #[case] expected_reason: Option<&str>,
    ) {
        let config = warnings_config(enabled, hosts, topic);
        let runtime = current_thread_runtime();

        let (emitter, snapshotter) =
            capture_metrics(|| runtime.block_on(create_ingestion_warning_emitter(&config, None)));

        assert!(emitter.is_none(), "no case here can build an emitter");
        match expected_reason {
            Some(reason) => assert_eq!(
                emitter_enabled_gauge(&snapshotter),
                Some((reason.to_string(), 0.0)),
            ),
            None => assert!(
                emitter_enabled_gauge(&snapshotter).is_none(),
                "disabled must stay unset, or it looks misconfigured",
            ),
        }
    }

    #[test]
    fn healthy_emitter_reports_ok() {
        // TEST-NET-1 host: the no-ping constructor never dials it, so the real
        // success path runs offline.
        let config = warnings_config(true, "192.0.2.1:9092", "client_ingestion_warning");
        let mut manager = lifecycle::Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .build();
        // Mirrors the registration in `register_components`.
        let handle = manager.register(
            "ingestion-warnings",
            lifecycle::ComponentOptions::new()
                .with_liveness_deadline(Duration::from_secs(30))
                .is_advisory(true),
        );
        let runtime = current_thread_runtime();

        let (emitter, snapshotter) = capture_metrics(|| {
            runtime.block_on(create_ingestion_warning_emitter(&config, Some(handle)))
        });

        assert!(emitter.is_some(), "emitter must be built");
        assert_eq!(
            emitter_enabled_gauge(&snapshotter),
            Some(("ok".to_string(), 1.0)),
            "healthy and failed emissions must share a label set",
        );
    }
}
