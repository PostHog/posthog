use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use axum::Router;
use common_redis::RedisClient;
use tracing::{info, warn};

use crate::ai_s3::AiBlobStorage;
use crate::config::{AiRouting, AiSinkMode, CaptureMode, Config, KafkaConfig};
use crate::event_restrictions::{EventRestrictionService, Pipeline, RedisRestrictionsRepository};
use crate::global_rate_limiter::GlobalRateLimiter;
use crate::quota_limiters::{
    is_exception_event, is_llm_event, is_survey_event, CaptureQuotaLimiter,
};
use crate::router;
use crate::router::BATCH_BODY_SIZE;
use crate::s3_client::{S3Client, S3Config};
use crate::sinks::fallback::FallbackSink;
use crate::sinks::kafka::KafkaSink;
use crate::sinks::noop::NoOpSink;
use crate::sinks::print::PrintSink;
use crate::sinks::s3::S3Sink;
use crate::sinks::split::SplitKafkaSink;
use crate::sinks::Event;
use limiters::overflow::OverflowLimiter;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, OVERFLOW_LIMITER_CACHE_KEY};
use limiters::token_dropper::TokenDropper;

pub struct LifecycleHandles {
    pub server: lifecycle::Handle,
    pub sink: Option<lifecycle::Handle>,
    pub advisory: Option<lifecycle::Handle>,
    pub event_restrictions: Option<lifecycle::Handle>,
    pub v1_sinks: HashMap<crate::v1::sinks::SinkName, lifecycle::Handle>,
    pub readiness: lifecycle::ReadinessHandler,
    pub liveness: lifecycle::LivenessHandler,
}

pub fn register_components(manager: &mut lifecycle::Manager, config: &Config) -> LifecycleHandles {
    // S3 fallback and AI secondary routing both contend for the single gating
    // sink handle, and only one can own it. Enabling both leaves one cluster's
    // producer unmonitored while the pod's liveness gates on an idle sink — refuse
    // to start rather than silently watch the wrong cluster.
    let ai_secondary_routing =
        config.capture_mode == CaptureMode::Ai && config.ai_sink_mode != AiSinkMode::Primary;
    assert!(
        !(config.s3_fallback_enabled && ai_secondary_routing),
        "invalid configuration: S3_FALLBACK_ENABLED cannot be combined with AI secondary routing (AI_SINK_MODE={:?}); enable at most one",
        config.ai_sink_mode,
    );

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
        v1_sinks: v1_sink_handles,
        readiness,
        liveness,
    } = handles;

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

    let global_rate_limiter_token_distinctid = if config.global_rate_limit_enabled {
        let limiter = GlobalRateLimiter::try_from_config(&config, redis_client.clone())
            .await
            .expect("failed to create global rate limiter");
        Some(Arc::new(limiter))
    } else {
        None
    };

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
        CaptureMode::Events | CaptureMode::Ai => BATCH_BODY_SIZE * 5,
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
                partition.report_metrics().await;
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

    // The capture sink is a single lifecycle component: `register_components`
    // mints exactly one gating sink handle. When AI secondary routing is on we
    // wrap the primary in a `SplitKafkaSink` that diverts events (all, or an
    // allowlisted subset) to a second producer pointing at the secondary cluster
    // (e.g. WarpStream). The KafkaSink layer is unchanged, so overflow/DLQ/redirect
    // stamping applies on either cluster.
    let build_secondary =
        config.capture_mode == CaptureMode::Ai && config.ai_sink_mode != AiSinkMode::Primary;

    // Decide which producer carries the single gating handle so the right
    // cluster's health gates the pod: the secondary when it is the sole
    // destination (full `Secondary` cutover), the primary otherwise. The
    // non-gating producer is built with no handle — it still produces and emits
    // metrics, it just doesn't drive a manager component. S3 fallback keeps the
    // handle on the primary path (it owns its own advisory wiring).
    let secondary_owns_liveness = build_secondary
        && config.ai_sink_mode == AiSinkMode::Secondary
        && !config.s3_fallback_enabled;
    let (primary_handle, secondary_handle) = if secondary_owns_liveness {
        (None, sink_handle)
    } else {
        (sink_handle, None)
    };

    let primary_sink: Arc<dyn Event + Send + Sync> = Arc::from(
        create_sink(&config, primary_handle, advisory_handle)
            .await
            .expect("failed to create sink"),
    );

    let sink: Arc<dyn Event + Send + Sync> = if build_secondary {
        let secondary: Arc<dyn Event + Send + Sync> = Arc::new(
            KafkaSink::new(build_ai_secondary_kafka_config(&config), secondary_handle)
                .await
                .expect("failed to start AI secondary Kafka sink"),
        );
        let routing = if config.ai_sink_mode == AiSinkMode::SecondaryAllowlist {
            let allowlist = config
                .ai_secondary_allowlist_tokens
                .as_deref()
                .map(parse_token_allowlist)
                .unwrap_or_default();
            AiRouting::SecondaryAllowlist(allowlist)
        } else {
            AiRouting::Secondary
        };
        info!(mode = ?config.ai_sink_mode, "AI secondary sink enabled");
        Arc::new(SplitKafkaSink::new(primary_sink, secondary, routing))
    } else {
        primary_sink
    };
    let sink_for_flush = sink.clone();

    // Create AI blob storage if S3 is configured
    let ai_blob_storage: Option<Arc<dyn crate::ai_s3::BlobStorage>> =
        if let Some(bucket) = &config.ai_s3_bucket {
            let s3_config = S3Config {
                bucket: bucket.clone(),
                region: config.ai_s3_region.clone(),
                endpoint: config.ai_s3_endpoint.clone(),
                access_key_id: config.ai_s3_access_key_id.clone(),
                secret_access_key: config.ai_s3_secret_access_key.clone(),
            };
            let s3_client = S3Client::new(s3_config).await;

            if s3_client.check_health().await {
                tracing::info!(bucket = bucket, "AI S3 bucket verified");
            } else {
                tracing::error!(bucket = bucket, "AI S3 bucket not accessible");
            }

            // Spawn background health check task (shutdown-aware via server handle)
            let s3_client_clone = s3_client.clone();
            let ai_shutdown = server.clone();
            tokio::spawn(async move {
                let mut interval = tokio::time::interval(Duration::from_secs(30));
                loop {
                    tokio::select! {
                        _ = interval.tick() => {
                            s3_client_clone.check_health().await;
                        }
                        _ = ai_shutdown.shutdown_recv() => {
                            break;
                        }
                    }
                }
            });

            Some(Arc::new(AiBlobStorage::new(
                s3_client,
                config.ai_s3_prefix.clone(),
            )))
        } else {
            None
        };

    let event_restriction_service = if let Some(handle) = event_restrictions_handle {
        create_event_restriction_service(
            &config,
            handle,
            Pipeline::for_capture_mode(config.capture_mode),
        )
    } else {
        None
    };

    let (v1_sink_router, route_ai_events) = if !config.capture_v1_sinks.is_empty() {
        let (router, route_ai_events) = create_v1_sink_router(&config, &sink_env, v1_sink_handles)
            .unwrap_or_else(|e| panic!("fatal: v1 sink router creation failed: {e:#}"));
        (Some(router), route_ai_events)
    } else {
        (None, false)
    };

    let app = router::router(
        crate::time::SystemTime {},
        readiness,
        liveness,
        sink,
        redis_client,
        global_rate_limiter_token_distinctid,
        quota_limiter,
        token_dropper,
        event_restriction_service,
        config.export_prometheus,
        config.capture_mode,
        config.otel_service_name.clone(),
        config.concurrency_limit,
        event_payload_max_bytes,
        config.enable_historical_rerouting,
        config.historical_rerouting_threshold_days,
        config.is_mirror_deploy,
        config.verbose_sample_percent,
        config.ai_max_sum_of_parts_bytes,
        ai_blob_storage,
        config.body_chunk_read_timeout_ms,
        config.body_read_chunk_size_kb,
        config.capture_v1_max_compressed_body_bytes,
        config.capture_v1_max_decompressed_body_bytes,
        overflow_limiter,
        replay_overflow_limiter,
        v1_sink_router.clone(),
        config.capture_v1_scatter_gather_min_batch,
        config.ai_gateway_signing_secret.clone(),
        route_ai_events,
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
        http1_header_read_timeout_ms: config.http1_header_read_timeout_ms,
    }
}

/// Build the secondary AI Kafka config by inheriting all producer tuning from
/// the primary `kafka` config and overriding only the destination cluster and
/// main topic. Panics with a clear message if the required secondary
/// connection settings are missing — callers only invoke this when the AI sink
/// mode requires a secondary, so missing config is a fatal misconfiguration.
fn build_ai_secondary_kafka_config(config: &Config) -> KafkaConfig {
    let mut kafka = config.kafka.clone();
    kafka.kafka_hosts = config
        .ai_secondary_kafka_hosts
        .clone()
        .filter(|h| !h.is_empty())
        .expect("AI_SECONDARY_KAFKA_HOSTS is required when AI_SINK_MODE != primary");
    kafka.kafka_topic = config
        .ai_secondary_kafka_topic
        .clone()
        .filter(|t| !t.is_empty())
        .expect("AI_SECONDARY_KAFKA_TOPIC is required when AI_SINK_MODE != primary");
    kafka.kafka_tls = config.ai_secondary_kafka_tls;
    if !config.ai_secondary_kafka_client_id.is_empty() {
        kafka.kafka_client_id = config.ai_secondary_kafka_client_id.clone();
    }
    kafka
}

/// Parse a comma-separated token allowlist into a set, trimming whitespace and
/// dropping empty entries.
fn parse_token_allowlist(csv: &str) -> HashSet<String> {
    csv.split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(String::from)
        .collect()
}

/// Builds the v1 sink router and reports whether the default sink diverts
/// `$ai_*` events to a dedicated topic (its kafka `topic_ai` is set). The flag
/// is surfaced here, alongside where the sink configs are built, so
/// `router::State` can gate AI routing without reaching back through the sink.
fn create_v1_sink_router(
    config: &Config,
    sink_env: &HashMap<String, String>,
    handles: HashMap<crate::v1::sinks::SinkName, lifecycle::Handle>,
) -> anyhow::Result<(Arc<crate::v1::sinks::Router>, bool)> {
    let sinks_cfg = crate::v1::sinks::load_sinks_from(&config.capture_v1_sinks, sink_env)
        .context("failed to parse CAPTURE_V1_SINKS")?;
    sinks_cfg
        .validate()
        .context("v1 sink config validation failed")?;

    // validate() guarantees the default sink is present in configs.
    let route_ai_events = sinks_cfg
        .configs
        .get(&sinks_cfg.default)
        .is_some_and(|cfg| cfg.kafka.topic_ai.is_some());

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
        route_ai_events, "V1 sink router initialized"
    );
    Ok((Arc::new(router), route_ai_events))
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
            .expect("failed to start Kafka sink");

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
        // `sink_handle` is `None` for a primary that must not gate the pod (a
        // full `Secondary` cutover hands the gating handle to the secondary).
        let kafka_sink = KafkaSink::new(config.kafka.clone(), sink_handle)
            .await
            .expect("failed to start Kafka sink");

        Ok(Box::new(kafka_sink))
    }
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
    use std::collections::HashMap;

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
    #[should_panic(expected = "S3_FALLBACK_ENABLED cannot be combined with AI secondary routing")]
    fn register_components_rejects_s3_fallback_with_ai_secondary() {
        let cfg_env: HashMap<String, String> = [
            ("REDIS_URL", "redis://localhost:6379/"),
            ("CAPTURE_MODE", "ai"),
            ("KAFKA_HOSTS", "localhost:9092"),
            ("KAFKA_TOPIC", "events_plugin_ingestion"),
            ("S3_FALLBACK_ENABLED", "true"),
            ("AI_SINK_MODE", "secondary"),
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
        register_components(&mut manager, &config);
    }

    #[test]
    fn parse_token_allowlist_trims_and_drops_empties() {
        // A stray space or trailing/double comma in AI_SECONDARY_ALLOWLIST_TOKENS
        // must not produce a mismatched or empty token that breaks routing.
        let set = super::parse_token_allowlist(" tok_a , tok_b ,,tok_c, ");
        assert_eq!(set.len(), 3);
        assert!(set.contains("tok_a"));
        assert!(set.contains("tok_b"));
        assert!(set.contains("tok_c"));
        assert!(!set.contains(""));

        assert!(super::parse_token_allowlist("  ,  , ").is_empty());
    }
}
