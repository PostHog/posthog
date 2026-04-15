use std::sync::Arc;
use std::time::Duration;

use axum::Router;
use common_redis::RedisClient;
use tracing::{info, warn};

use crate::ai_s3::AiBlobStorage;
use crate::config::{CaptureMode, Config};
use crate::event_restrictions::{EventRestrictionService, RedisRestrictionsRepository};
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
use crate::sinks::Event;
use limiters::overflow::OverflowLimiter;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, OVERFLOW_LIMITER_CACHE_KEY};
use limiters::token_dropper::TokenDropper;

pub struct LifecycleHandles {
    pub server: lifecycle::Handle,
    pub sink: Option<lifecycle::Handle>,
    pub advisory: Option<lifecycle::Handle>,
    pub event_restrictions: Option<lifecycle::Handle>,
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
        let s3 = manager.register("s3-sink", sink_opts);
        (Some(s3), Some(kafka))
    } else {
        (Some(manager.register("kafka-sink", sink_opts)), None)
    };

    let event_restrictions =
        if config.event_restrictions_enabled && config.event_restrictions_redis_url.is_some() {
            Some(manager.register("event-restrictions", lifecycle::ComponentOptions::new()))
        } else {
            None
        };

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    LifecycleHandles {
        server,
        sink,
        advisory,
        event_restrictions,
        readiness,
        liveness,
    }
}

pub struct CaptureComponents {
    pub app: Router,
    pub server_handle: lifecycle::Handle,
    pub sink: Arc<dyn Event + Send + Sync>,
    pub http1_header_read_timeout_ms: Option<u64>,
}

pub async fn build_components(config: Config, handles: LifecycleHandles) -> CaptureComponents {
    let LifecycleHandles {
        server,
        sink: sink_handle,
        advisory: advisory_handle,
        event_restrictions: event_restrictions_handle,
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

    let sink: Arc<dyn Event + Send + Sync> = Arc::from(
        create_sink(&config, redis_client.clone(), sink_handle, advisory_handle)
            .await
            .expect("failed to create sink"),
    );
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
        create_event_restriction_service(&config, handle)
    } else {
        None
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
        config.request_timeout_seconds,
        config.body_chunk_read_timeout_ms,
        config.body_read_chunk_size_kb,
    );

    info!(
        "config: is_mirror_deploy == {:?} ; log_level == {:?}",
        config.is_mirror_deploy, config.log_level
    );

    CaptureComponents {
        app,
        server_handle: server,
        sink: sink_for_flush,
        http1_header_read_timeout_ms: config.http1_header_read_timeout_ms,
    }
}

async fn create_sink(
    config: &Config,
    redis_client: Arc<RedisClient>,
    sink_handle: Option<lifecycle::Handle>,
    advisory_handle: Option<lifecycle::Handle>,
) -> anyhow::Result<Box<dyn Event + Send + Sync>> {
    if config.print_sink {
        Ok(Box::new(PrintSink {}))
    } else if config.noop_sink {
        info!("NoOpSink enabled, events will be silently dropped");
        Ok(Box::new(NoOpSink::new()))
    } else {
        let sink_handle = sink_handle.expect("sink lifecycle handle required for Kafka/S3 sinks");
        let partition = match config.overflow_enabled {
            false => None,
            true => {
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
                    // Ensure that the rate limiter state does not grow unbounded
                    let partition = partition.clone();
                    tokio::spawn(async move {
                        partition.clean_state().await;
                    });
                }
                Some(partition)
            }
        };

        let replay_overflow_limiter = match config.capture_mode {
            CaptureMode::Recordings => Some(
                RedisLimiter::new(
                    Duration::from_secs(5),
                    redis_client.clone(),
                    OVERFLOW_LIMITER_CACHE_KEY.to_string(),
                    config.redis_key_prefix.clone(),
                    QuotaResource::Replay,
                    ServiceName::Capture,
                )
                .expect("failed to start replay overflow limiter"),
            ),
            _ => None,
        };

        if config.s3_fallback_enabled {
            let kafka_handle =
                advisory_handle.expect("kafka advisory handle required for fallback");
            let s3_handle = sink_handle;

            let kafka_sink = KafkaSink::new(
                config.kafka.clone(),
                kafka_handle.clone(),
                partition,
                replay_overflow_limiter,
            )
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
            let kafka_sink = KafkaSink::new(
                config.kafka.clone(),
                sink_handle,
                partition,
                replay_overflow_limiter,
            )
            .await
            .expect("failed to start Kafka sink");

            Ok(Box::new(kafka_sink))
        }
    }
}

fn create_event_restriction_service(
    config: &Config,
    handle: lifecycle::Handle,
) -> Option<EventRestrictionService> {
    if !config.event_restrictions_enabled {
        return None;
    }

    let Some(ref redis_url) = config.event_restrictions_redis_url else {
        warn!("Event restrictions enabled but EVENT_RESTRICTIONS_REDIS_URL not set");
        return None;
    };

    let service = EventRestrictionService::new(
        config.capture_mode,
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
        pipeline = %config.capture_mode.as_pipeline_name(),
        refresh_interval_secs = config.event_restrictions_refresh_interval_secs,
        fail_open_after_secs = config.event_restrictions_fail_open_after_secs,
        "Event restrictions enabled"
    );

    Some(service)
}
