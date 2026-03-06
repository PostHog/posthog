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
use lifecycle::{ComponentOptions, Handle as LifecycleHandle, Manager};
use limiters::redis::ServiceName;
use tokio::net::{TcpListener, TcpStream};
use tokio_util::sync::CancellationToken;
use tower::Service;
use tracing::{debug, error, info, warn};

use crate::ai_s3::AiBlobStorage;
use crate::config::CaptureMode;
use crate::config::Config;
use crate::event_restrictions::{EventRestrictionService, RedisRestrictionsRepository};
use crate::global_rate_limiter::GlobalRateLimiter;
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

fn create_event_restriction_service(
    config: &Config,
    handle: LifecycleHandle,
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

    let cancel_token = CancellationToken::new();
    let task_cancel_token = cancel_token.clone();

    // Bridge lifecycle shutdown to the CancellationToken that start_refresh_task expects
    let shutdown_bridge = handle.clone();
    tokio::spawn(async move {
        shutdown_bridge.shutdown_recv().await;
        cancel_token.cancel();
    });

    tokio::spawn(async move {
        let _guard = handle.process_scope();
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
                task_cancel_token,
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

async fn create_sink(
    config: &Config,
    redis_client: Arc<RedisClient>,
    kafka_handle: LifecycleHandle,
    s3_handle: Option<LifecycleHandle>,
    noop_handle: Option<LifecycleHandle>,
    shutdown_handle: LifecycleHandle,
) -> anyhow::Result<Box<dyn Event + Send + Sync>> {
    if config.print_sink {
        Ok(Box::new(PrintSink {}))
    } else if config.noop_sink {
        info!("NoOpSink enabled, events will be silently dropped");
        let handle = noop_handle.expect("noop_handle required when noop_sink enabled");
        Ok(Box::new(NoOpSink::new(handle)))
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
                    let sh = shutdown_handle.clone();
                    tokio::spawn(async move {
                        tokio::select! {
                            _ = partition.report_metrics() => {}
                            _ = sh.shutdown_recv() => {}
                        }
                    });
                }

                {
                    let partition = partition.clone();
                    let sh = shutdown_handle.clone();
                    tokio::spawn(async move {
                        tokio::select! {
                            _ = partition.clean_state() => {}
                            _ = sh.shutdown_recv() => {}
                        }
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

        let fallback_handle = kafka_handle.clone();
        let kafka_sink = KafkaSink::new(
            config.kafka.clone(),
            kafka_handle,
            partition,
            replay_overflow_limiter,
        )
        .await
        .expect("failed to start Kafka sink");

        if config.s3_fallback_enabled {
            let s3_liveness = s3_handle.expect("s3_handle required when s3_fallback_enabled");

            let s3_sink = S3Sink::new(
                config
                    .s3_fallback_bucket
                    .clone()
                    .expect("S3 bucket required when fallback enabled"),
                config.s3_fallback_prefix.clone(),
                config.s3_fallback_endpoint.clone(),
                s3_liveness,
            )
            .await
            .expect("failed to create S3 sink");

            Ok(Box::new(FallbackSink::new_with_health(
                kafka_sink,
                s3_sink,
                fallback_handle,
            )))
        } else {
            Ok(Box::new(kafka_sink))
        }
    }
}

pub async fn serve(config: Config, listener: TcpListener, mut manager: Manager) {
    // --- Register lifecycle components ---
    let server_handle = manager.register(
        "server",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );

    let kafka_handle = manager.register(
        "kafka",
        ComponentOptions::new()
            .with_liveness_deadline(Duration::from_secs(30))
            .with_stall_threshold(2),
    );

    let s3_handle = if config.s3_fallback_enabled {
        Some(
            manager.register(
                "s3-fallback",
                ComponentOptions::new()
                    .with_liveness_deadline(Duration::from_secs(30))
                    .with_stall_threshold(2),
            ),
        )
    } else {
        None
    };

    let noop_handle = if config.noop_sink {
        Some(manager.register("noop-sink", ComponentOptions::new()))
    } else {
        None
    };

    let ai_s3_handle = if config.ai_s3_bucket.is_some() {
        Some(
            manager.register(
                "ai-s3",
                ComponentOptions::new()
                    .with_liveness_deadline(Duration::from_secs(60))
                    .with_stall_threshold(2),
            ),
        )
    } else {
        None
    };

    let event_restrictions_handle = if config.event_restrictions_enabled {
        Some(manager.register(
            "event-restrictions",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
        ))
    } else {
        None
    };

    let obs_handle = manager.register(
        "observability",
        ComponentOptions::new().is_observability(true),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let guard = manager.monitor_background();

    // --- Build infrastructure ---
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

    let quota_limiter =
        CaptureQuotaLimiter::new(&config, redis_client.clone(), Duration::from_secs(5))
            .add_scoped_limiter(QuotaResource::Exceptions, is_exception_event)
            .add_scoped_limiter(QuotaResource::Surveys, is_survey_event)
            .add_scoped_limiter(QuotaResource::LLMEvents, is_llm_event);

    let token_dropper = config
        .drop_events_by_token_distinct_id
        .clone()
        .map(|k| TokenDropper::new(&k))
        .unwrap_or_default();

    let event_payload_max_bytes = match config.capture_mode {
        CaptureMode::Events | CaptureMode::Ai => BATCH_BODY_SIZE * 5,
        CaptureMode::Recordings => config.kafka.kafka_producer_message_max_bytes as usize,
    };

    let sink = create_sink(
        &config,
        redis_client.clone(),
        kafka_handle.clone(),
        s3_handle,
        noop_handle,
        server_handle.clone(),
    )
    .await
    .expect("failed to create sink");

    // --- AI blob storage ---
    let ai_blob_storage: Option<Arc<dyn crate::ai_s3::BlobStorage>> =
        if let (Some(bucket), Some(ai_handle)) = (&config.ai_s3_bucket, ai_s3_handle) {
            let s3_config = S3Config {
                bucket: bucket.clone(),
                region: config.ai_s3_region.clone(),
                endpoint: config.ai_s3_endpoint.clone(),
                access_key_id: config.ai_s3_access_key_id.clone(),
                secret_access_key: config.ai_s3_secret_access_key.clone(),
            };
            let s3_client = S3Client::new(s3_config).await;

            if s3_client.check_health().await {
                ai_handle.report_healthy();
                tracing::info!(bucket = bucket.as_str(), "AI S3 bucket verified");
            } else {
                ai_handle.report_unhealthy();
                tracing::error!(bucket = bucket.as_str(), "AI S3 bucket not accessible");
            }

            let s3_client_clone = s3_client.clone();
            let ai_health = ai_handle.clone();
            tokio::spawn(async move {
                let _guard = ai_health.process_scope();
                let mut interval = tokio::time::interval(Duration::from_secs(30));
                loop {
                    tokio::select! {
                        _ = interval.tick() => {
                            if s3_client_clone.check_health().await {
                                ai_health.report_healthy();
                            } else {
                                ai_health.report_unhealthy();
                            }
                        }
                        _ = ai_health.shutdown_recv() => break,
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

    // --- Event restrictions ---
    let event_restriction_service = if let Some(er_handle) = event_restrictions_handle {
        create_event_restriction_service(&config, er_handle)
    } else {
        None
    };

    // --- Observability server (separate listener for metrics, readiness, liveness) ---
    {
        let obs_addr = config.observability_address;
        let export_prometheus = config.export_prometheus;
        let deploy_role = config.otel_service_name.clone();
        let capture_mode_tag = config.capture_mode.as_tag();

        let obs_listener = tokio::net::TcpListener::bind(obs_addr)
            .await
            .expect("could not bind observability port");
        info!("observability server listening on {:?}", obs_addr);

        tokio::spawn(async move {
            let mut obs_app = Router::new()
                .route(
                    "/_readiness",
                    axum::routing::get(move || {
                        let r = readiness.clone();
                        async move { r.check().await }
                    }),
                )
                .route(
                    "/_liveness",
                    axum::routing::get(move || async move { liveness.check() }),
                );

            if export_prometheus {
                let recorder_handle =
                    crate::prometheus::setup_metrics_recorder(deploy_role, capture_mode_tag);
                obs_app = obs_app.route(
                    "/metrics",
                    axum::routing::get(move || {
                        let h = recorder_handle.clone();
                        async move { h.render() }
                    }),
                );
            }

            axum::serve(obs_listener, obs_app.into_make_service())
                .with_graceful_shutdown(obs_handle.shutdown_signal())
                .await
                .expect("observability server failed");

            obs_handle.work_completed();
        });
    }

    // --- Build main capture router ---
    let app = router::router(
        crate::time::SystemTime {},
        sink,
        redis_client,
        global_rate_limiter_token_distinctid,
        global_rate_limiter_token,
        quota_limiter,
        token_dropper,
        event_restriction_service,
        config.capture_mode,
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
        Some(server_handle.clone()),
    );

    info!("listening on {:?}", listener.local_addr().unwrap());
    info!(
        "config: is_mirror_deploy == {:?} ; log_level == {:?}",
        config.is_mirror_deploy, config.log_level
    );

    // --- HTTP accept loop ---
    let mut builder = AutoBuilder::new(TokioExecutor::new());

    if let Some(timeout_ms) = config.http1_header_read_timeout_ms {
        builder
            .http1()
            .timer(TokioTimer::new())
            .header_read_timeout(Duration::from_millis(timeout_ms));
        info!("HTTP/1 header read timeout configured: {timeout_ms}ms");
    }

    let graceful = GracefulShutdown::new();

    {
        let _scope = server_handle.process_scope();

        loop {
            tokio::select! {
                result = listener.accept() => {
                    let (socket, remote_addr) = match result {
                        Ok(conn) => {
                            metrics::counter!(METRIC_CAPTURE_HYPER_ACCEPTED_CONNECTIONS, "stage" => "accept").increment(1);
                            conn
                        },
                        Err(e) => {
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
                    break;
                }
            }
        }

        // Drain queued connections from the TCP accept backlog
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
                    break;
                }
            }
        }
        info!(
            drained_connections = drained_count,
            "Hyper accept loop (shutdown): drained queued connections"
        );

        info!(
            "Hyper accept loop (shutdown): waiting for in-flight request handlers to complete..."
        );
        graceful.shutdown().await;
        info!("Hyper accept loop (shutdown): graceful shutdown completed");

        // _scope drops here, signaling server completion to lifecycle manager
    }

    // Wait for lifecycle monitor to complete (all components drained)
    if let Err(e) = guard.wait().await {
        error!("Lifecycle shutdown error: {e}");
    }
}
