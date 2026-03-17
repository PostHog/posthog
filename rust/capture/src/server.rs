use std::io;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use axum::extract::ConnectInfo;
use axum::Router;
use common_redis::RedisClient;
use hyper_util::rt::{TokioExecutor, TokioIo, TokioTimer};
use hyper_util::server::conn::auto::Builder as AutoBuilder;
use hyper_util::server::graceful::GracefulShutdown;
use limiters::redis::ServiceName;
use tokio::net::{TcpListener, TcpStream};
use tower::Service;
use tracing::{debug, error, info, warn};

use crate::ai_s3::AiBlobStorage;
use crate::config::CaptureMode;
use crate::config::Config;
use crate::event_restrictions::{EventRestrictionService, RedisRestrictionsRepository};
use crate::global_rate_limiter::GlobalRateLimiter;
use crate::metrics_middleware::{set_global_shutdown_flag, ShutdownFlag};
use crate::quota_limiters::{is_exception_event, is_llm_event, is_survey_event};
use crate::s3_client::{S3Client, S3Config};

use limiters::overflow::OverflowLimiter;
use limiters::redis::{QuotaResource, RedisLimiter, OVERFLOW_LIMITER_CACHE_KEY};

use crate::quota_limiters::CaptureQuotaLimiter;
use crate::router;
use crate::router::BATCH_BODY_SIZE;
use crate::sinks::fallback::FallbackSink;
use crate::sinks::kafka::KafkaSink;
use crate::sinks::noop::NoOpSink;
use crate::sinks::print::PrintSink;
use crate::sinks::s3::S3Sink;
use crate::sinks::Event;
use limiters::token_dropper::TokenDropper;

// failsafe to prevent infinite loop if k8s endpoint removal is not working in prod
const MAX_DRAINABLE_CONNECTIONS: u64 = 1000;

const METRIC_CAPTURE_HYPER_ACCEPTED_CONNECTIONS: &str = "capture_hyper_accepted_connections";
const METRIC_CAPTURE_HYPER_ACCEPT_ERROR: &str = "capture_hyper_accept_error";
const METRIC_CAPTURE_HYPER_HEADER_READ_TIMEOUT: &str = "capture_hyper_header_read_timeout";

/// Returns true for errors that commonly occur during accept and don't indicate
/// a problem with the listener itself. These are silently retried without logging.
/// Matches axum::serve behavior.
fn is_connection_error(e: &io::Error) -> bool {
    matches!(
        e.kind(),
        io::ErrorKind::ConnectionRefused
            | io::ErrorKind::ConnectionAborted
            | io::ErrorKind::ConnectionReset
    )
}

/// Configures and spawns a connection handler for an accepted TCP connection.
/// Sets TCP_NODELAY, creates the hyper service with ConnectInfo, registers with
/// graceful shutdown, and spawns the connection handler task.
fn spawn_connection_handler(
    socket: TcpStream,
    remote_addr: SocketAddr,
    app: Router,
    builder: &AutoBuilder<TokioExecutor>,
    graceful: &GracefulShutdown,
    stage: &'static str,
) {
    if let Err(e) = socket.set_nodelay(true) {
        metrics::counter!(
            METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
            "err_type" => "set_tcp_nodelay",
            "stage" => stage,
        )
        .increment(1);
        warn!("Hyper accept loop ({stage}): error setting TCP_NODELAY: {e:#}");
    }

    let service = hyper::service::service_fn(move |req: hyper::Request<hyper::body::Incoming>| {
        let mut app = app.clone();
        let mut req = req.map(axum::body::Body::new);
        req.extensions_mut().insert(ConnectInfo(remote_addr));
        async move { app.call(req).await }
    });

    let conn = builder.serve_connection_with_upgrades(TokioIo::new(socket), service);
    let conn = graceful.watch(conn.into_owned());

    tokio::spawn(async move {
        if let Err(e) = conn.await {
            let err_str = e.to_string();
            let is_header_timeout = err_str.contains("timeout") && err_str.contains("header");

            if is_header_timeout {
                metrics::counter!(
                    METRIC_CAPTURE_HYPER_HEADER_READ_TIMEOUT,
                    "stage" => stage,
                )
                .increment(1);
                debug!("Hyper accept loop ({}): header read timeout: {}", stage, e);
            } else {
                metrics::counter!(
                    METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
                    "err_type" => "conn_closed",
                    "stage" => stage,
                )
                .increment(1);
                debug!("Hyper accept loop ({}): connection closed: {}", stage, e);
            }
        }
    });
}

async fn create_sink(
    config: &Config,
    redis_client: Arc<RedisClient>,
    sink_handle: lifecycle::Handle,
    advisory_handle: Option<lifecycle::Handle>,
) -> anyhow::Result<Box<dyn Event + Send + Sync>> {
    if config.print_sink {
        Ok(Box::new(PrintSink {}))
    } else if config.noop_sink {
        info!("NoOpSink enabled, events will be silently dropped");
        Ok(Box::new(NoOpSink::new()))
    } else {
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
            sink_handle,
            advisory_handle.clone(),
            partition,
            replay_overflow_limiter,
        )
        .await
        .expect("failed to start Kafka sink");

        if config.s3_fallback_enabled {
            let s3_liveness_handle = advisory_handle
                .as_ref()
                .expect("advisory handle required for S3 fallback")
                .clone();

            let s3_sink = S3Sink::new(
                config
                    .s3_fallback_bucket
                    .clone()
                    .expect("S3 bucket required when fallback enabled"),
                config.s3_fallback_prefix.clone(),
                config.s3_fallback_endpoint.clone(),
                s3_liveness_handle,
            )
            .await
            .expect("failed to create S3 sink");

            Ok(Box::new(FallbackSink::new_with_advisory(
                kafka_sink,
                s3_sink,
                advisory_handle.expect("advisory handle required for fallback"),
            )))
        } else {
            Ok(Box::new(kafka_sink))
        }
    }
}

fn create_event_restriction_service(
    config: &Config,
    handle: lifecycle::Handle,
) -> (
    Option<EventRestrictionService>,
    Option<tokio::task::JoinHandle<()>>,
) {
    if !config.event_restrictions_enabled {
        return (None, None);
    }

    let Some(ref redis_url) = config.event_restrictions_redis_url else {
        warn!("Event restrictions enabled but EVENT_RESTRICTIONS_REDIS_URL not set");
        return (None, None);
    };

    let service = EventRestrictionService::new(
        config.capture_mode,
        Duration::from_secs(config.event_restrictions_fail_open_after_secs),
    );

    let service_clone = service.clone();
    let refresh_interval = Duration::from_secs(config.event_restrictions_refresh_interval_secs);

    // Capture values needed by the repository factory
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

    let task_handle = tokio::spawn(async move {
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

    (Some(service), Some(task_handle))
}

pub async fn serve(config: Config, listener: TcpListener, mut manager: lifecycle::Manager) {
    // --- Registration phase ---
    let server_handle = manager.register(
        "server",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(60)),
    );

    let sink_handle = manager.register(
        "sink",
        lifecycle::ComponentOptions::new()
            .with_liveness_deadline(Duration::from_secs(45))
            .with_stall_threshold(4),
    );

    let advisory_handle = if config.s3_fallback_enabled {
        Some(
            manager.register(
                "sink-advisory",
                lifecycle::ComponentOptions::new()
                    .is_advisory(true)
                    .with_liveness_deadline(Duration::from_secs(45))
                    .with_stall_threshold(4),
            ),
        )
    } else {
        None
    };

    let event_restrictions_handle =
        if config.event_restrictions_enabled && config.event_restrictions_redis_url.is_some() {
            Some(manager.register(
                "event-restrictions",
                lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
            ))
        } else {
            None
        };

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let guard = manager.monitor_background();

    // --- Setup phase ---
    let shutdown_flag = ShutdownFlag::new();
    set_global_shutdown_flag(shutdown_flag.clone());

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

    let (global_rate_limiter_token_distinctid, global_rate_limiter_token) =
        if config.global_rate_limit_enabled {
            let (td_limiter, token_limiter) =
                GlobalRateLimiter::try_from_config(&config, redis_client.clone())
                    .await
                    .expect("failed to create global rate limiters");
            (Some(Arc::new(td_limiter)), Some(Arc::new(token_limiter)))
        } else {
            (None, None)
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

            // Verify bucket exists on startup
            if s3_client.check_health().await {
                tracing::info!(bucket = bucket, "AI S3 bucket verified");
            } else {
                tracing::error!(bucket = bucket, "AI S3 bucket not accessible");
            }

            // Spawn background health check task (shutdown-aware via server handle)
            let s3_client_clone = s3_client.clone();
            let ai_shutdown = server_handle.clone();
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

    let (event_restriction_service, event_restrictions_join_handle) =
        if let Some(handle) = event_restrictions_handle {
            create_event_restriction_service(&config, handle)
        } else {
            (None, None)
        };

    let app = router::router(
        crate::time::SystemTime {},
        readiness,
        liveness,
        sink,
        redis_client,
        global_rate_limiter_token_distinctid,
        global_rate_limiter_token,
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

    info!("listening on {:?}", listener.local_addr().unwrap());
    info!(
        "config: is_mirror_deploy == {:?} ; log_level == {:?}",
        config.is_mirror_deploy, config.log_level
    );

    // --- Server block with process_scope ---
    {
        let _scope = server_handle.process_scope();

        // Set up hyper server with manual connection handling and graceful shutdown
        let mut builder = AutoBuilder::new(TokioExecutor::new());

        // Configure HTTP/1 header read timeout for slow loris protection
        if let Some(timeout_ms) = config.http1_header_read_timeout_ms {
            builder
                .http1()
                .timer(TokioTimer::new())
                .header_read_timeout(Duration::from_millis(timeout_ms));
            info!("HTTP/1 header read timeout configured: {timeout_ms}ms");
        }

        let graceful = GracefulShutdown::new();

        loop {
            tokio::select! {
                result = listener.accept() => {
                    let (socket, remote_addr) = match result {
                        Ok(conn) => {
                            metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPTED_CONNECTIONS, "stage" => "accept").increment(1);
                            conn
                        },
                        Err(e) => {
                            // Match axum::serve behavior:
                            // - Connection errors (reset, aborted, refused) are silently retried
                            // - Other errors (EMFILE, etc.) are logged and we back off 1s to avoid
                            //   tight loops under resource exhaustion
                            if is_connection_error(&e) {
                                metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
                                    "err_type" => "connection",
                                    "stage" => "accept",
                                ).increment(1);
                                error!("Hyper accept loop: connection error: {e:#}");
                            } else {
                                metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
                                    "err_type" => "resources",
                                    "stage" => "accept",
                                ).increment(1);
                                error!("Hyper accept loop: resource error: {e:#}");
                                tokio::time::sleep(Duration::from_secs(1)).await;
                            }
                            continue;
                        }
                    };

                    spawn_connection_handler(
                        socket,
                        remote_addr,
                        app.clone(),
                        &builder,
                        &graceful,
                        "accept",
                    );
                }
                _ = server_handle.shutdown_recv() => {
                    info!("Hyper accept loop: shutdown signal received");
                    shutdown_flag.set_shutting_down();
                    break;
                }
            }
        }

        // Drain any connections already queued in the TCP accept backlog.
        // These connections are already established at the TCP level, so we should
        // serve them rather than let them see connection reset.
        info!("Hyper accept loop (draining): checking for queued connections...");
        let mut drained_count: u64 = 0;
        loop {
            if drained_count > MAX_DRAINABLE_CONNECTIONS {
                error!(
                    "Hyper accept loop (draining): reached loop limit of {} connections",
                    MAX_DRAINABLE_CONNECTIONS
                );
                break;
            }
            // Use a minimal timeout to check if there are queued connections
            match tokio::time::timeout(Duration::from_millis(1), listener.accept()).await {
                Ok(Ok((socket, remote_addr))) => {
                    metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPTED_CONNECTIONS, "stage" => "drain")
                        .increment(1);
                    drained_count += 1;

                    spawn_connection_handler(
                        socket,
                        remote_addr,
                        app.clone(),
                        &builder,
                        &graceful,
                        "drain",
                    );
                }
                Ok(Err(e)) => {
                    // Accept error during drain - log but don't sleep, we're draining
                    if is_connection_error(&e) {
                        metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
                            "err_type" => "connection",
                            "stage" => "drain",
                        )
                        .increment(1);
                        error!(
                            error_type = "connection",
                            pause = "none",
                            "Hyper accept loop (draining): {e:#}"
                        );
                    } else {
                        metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPT_ERROR,
                            "err_type" => "resources",
                            "stage" => "drain",
                        )
                        .increment(1);
                        error!(
                            error_type = "resources",
                            pause = "none",
                            "Hyper accept loop (draining): {e:#}"
                        );
                    }
                }
                Err(_) => {
                    // Timeout - accept queue is empty, done draining
                    break;
                }
            }
        }
        info!(
            drained_connections = drained_count,
            "Hyper accept loop (shutdown): drained queued connections"
        );

        // Wait for all in-flight connections to complete
        info!(
            "Hyper accept loop (shutdown): waiting for in-flight request handlers to complete..."
        );
        graceful.shutdown().await;
        info!("Hyper accept loop (shutdown): graceful shutdown completed");

        // Flush the Kafka producer queue. Events from in-flight handlers may still
        // be in rdkafka's internal buffer. flush() blocks until the queue drains or
        // times out (default 30s from rdkafka config).
        info!("Flushing sink...");
        if let Err(e) = sink_for_flush.flush() {
            error!("Sink flush failed: {e:#}");
        }
        info!("Sink flush complete");

        // _scope drops here -> ProcessScopeGuard signals WorkCompleted
    }

    // Drop app to release sink Arc and trigger sink handle completion
    drop(app);

    // Wait for event restrictions task if running
    if let Some(handle) = event_restrictions_join_handle {
        info!("Waiting for event restrictions refresh task...");
        if let Err(e) = handle.await {
            warn!("Event restrictions refresh task failed: {e:#}");
        }
        info!("Event restrictions refresh task stopped");
    }

    // Wait for all lifecycle components to complete
    match guard.wait().await {
        Ok(()) => info!("All lifecycle components completed cleanly"),
        Err(e) => warn!("Lifecycle monitor reported: {e}"),
    }
}
