use std::future::Future;
use std::sync::Arc;
use std::time::Duration;

use axum::extract::ConnectInfo;
use common_redis::RedisClient;
use health::{ComponentStatus, HealthRegistry};
use hyper_util::rt::{TokioExecutor, TokioIo};
use hyper_util::server::conn::auto::Builder as AutoBuilder;
use hyper_util::server::graceful::GracefulShutdown;
use limiters::redis::ServiceName;
use tokio::net::TcpListener;
use tower::Service;

use crate::config::CaptureMode;
use crate::config::Config;
use crate::limiters::{is_exception_event, is_llm_event, is_survey_event};

use limiters::overflow::OverflowLimiter;
use limiters::redis::{QuotaResource, RedisLimiter, OVERFLOW_LIMITER_CACHE_KEY};

use crate::limiters::CaptureQuotaLimiter;
use crate::router;
use crate::router::BATCH_BODY_SIZE;
use crate::sinks::fallback::FallbackSink;
use crate::sinks::kafka::KafkaSink;
use crate::sinks::print::PrintSink;
use crate::sinks::s3::S3Sink;
use crate::sinks::Event;
use limiters::token_dropper::TokenDropper;

async fn create_sink(
    config: &Config,
    redis_client: Arc<RedisClient>,
    liveness: &HealthRegistry,
) -> anyhow::Result<Box<dyn Event + Send + Sync>> {
    if config.print_sink {
        // Print sink is only used for local debug, don't allow a container with it to run on prod
        liveness
            .register("print_sink".to_string(), Duration::from_secs(30))
            .await
            .report_status(ComponentStatus::Unhealthy)
            .await;

        Ok(Box::new(PrintSink {}))
    } else {
        let sink_liveness = liveness
            .register("rdkafka".to_string(), Duration::from_secs(30))
            .await;

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

        let kafka_sink = KafkaSink::new(
            config.kafka.clone(),
            sink_liveness,
            partition,
            replay_overflow_limiter,
        )
        .await
        .expect("failed to start Kafka sink");

        if config.s3_fallback_enabled {
            let sink_liveness = liveness
                .register("s3".to_string(), Duration::from_secs(30))
                .await;

            let s3_sink = S3Sink::new(
                config
                    .s3_fallback_bucket
                    .clone()
                    .expect("S3 bucket required when fallback enabled"),
                config.s3_fallback_prefix.clone(),
                config.s3_fallback_endpoint.clone(),
                sink_liveness,
            )
            .await
            .expect("failed to create S3 sink");

            Ok(Box::new(FallbackSink::new_with_health(
                kafka_sink,
                s3_sink,
                liveness.clone(),
                "rdkafka".to_string(),
            )))
        } else {
            Ok(Box::new(kafka_sink))
        }
    }
}

pub async fn serve<F>(config: Config, listener: TcpListener, shutdown: F)
where
    F: Future<Output = ()> + Send + 'static,
{
    let liveness =
        HealthRegistry::new_with_strategy("liveness", config.healthcheck_strategy.clone());

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

    // add new "scoped" quota limiters here as new quota tracking buckets are added
    // to PostHog! Here a "scoped" limiter is one that should be INDEPENDENT of the
    // global billing limiter applied here to every event batch. You must supply the
    // QuotaResource type and a predicate function that will match events to be limited
    let quota_limiter =
        CaptureQuotaLimiter::new(&config, redis_client.clone(), Duration::from_secs(5))
            .add_scoped_limiter(QuotaResource::Exceptions, Box::new(is_exception_event))
            .add_scoped_limiter(QuotaResource::Surveys, Box::new(is_survey_event))
            .add_scoped_limiter(QuotaResource::LLMEvents, Box::new(is_llm_event));

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
    let event_max_bytes = match config.capture_mode {
        CaptureMode::Events => BATCH_BODY_SIZE * 5,
        CaptureMode::Recordings => config.kafka.kafka_producer_message_max_bytes as usize,
    };

    let sink = create_sink(&config, redis_client.clone(), &liveness)
        .await
        .expect("failed to create sink");

    let app = router::router(
        crate::time::SystemTime {},
        liveness,
        sink,
        redis_client,
        quota_limiter,
        token_dropper,
        config.export_prometheus,
        config.capture_mode,
        config.otel_service_name.clone(), // this matches k8s role label in prod deploy envs
        config.concurrency_limit,
        event_max_bytes,
        config.enable_historical_rerouting,
        config.historical_rerouting_threshold_days,
        config.is_mirror_deploy,
        config.verbose_sample_percent,
        config.ai_max_sum_of_parts_bytes,
        config.request_timeout_seconds,
    );

    tracing::info!("listening on {:?}", listener.local_addr().unwrap());
    tracing::info!(
        "config: is_mirror_deploy == {:?} ; log_level == {:?}",
        config.is_mirror_deploy,
        config.log_level
    );

    // Set up hyper server with manual connection handling and graceful shutdown
    let builder = AutoBuilder::new(TokioExecutor::new());
    let graceful = GracefulShutdown::new();

    // Pin the shutdown future so we can poll it in the select loop
    tokio::pin!(shutdown);

    loop {
        tokio::select! {
            result = listener.accept() => {
                let (socket, remote_addr) = match result {
                    Ok(conn) => conn,
                    Err(e) => {
                        tracing::error!("failed to accept connection: {}", e);
                        continue;
                    }
                };

                // Match axum default: set TCP_NODELAY for low-latency
                if let Err(e) = socket.set_nodelay(true) {
                    tracing::warn!("failed to set TCP_NODELAY: {}", e);
                }

                // Create a service for this connection that injects ConnectInfo
                let app = app.clone();
                let service = hyper::service::service_fn(move |req: hyper::Request<hyper::body::Incoming>| {
                    let mut app = app.clone();
                    let mut req = req.map(axum::body::Body::new);
                    req.extensions_mut().insert(ConnectInfo(remote_addr));
                    async move { app.call(req).await }
                });

                // Serve the connection with HTTP/1 + HTTP/2 auto-detection and upgrade support
                let conn = builder.serve_connection_with_upgrades(
                    TokioIo::new(socket),
                    service,
                );

                // Register connection with graceful shutdown handler
                let conn = graceful.watch(conn.into_owned());

                tokio::spawn(async move {
                    if let Err(e) = conn.await {
                        tracing::debug!("connection closed: {}", e);
                    }
                });
            }
            _ = &mut shutdown => {
                tracing::info!("shutdown signal received, stopping accept loop");
                break;
            }
        }
    }

    // Wait for all in-flight connections to complete
    graceful.shutdown().await;

    tracing::info!("HTTP server graceful shutdown completed");
}
