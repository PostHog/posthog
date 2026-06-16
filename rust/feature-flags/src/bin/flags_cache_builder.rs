//! `flags-cache-builder` — long-running Kafka consumer that rebuilds per-team
//! feature-flag caches off `flags_cache_invalidation` messages.
//!
//! Replaces the Django signal → Celery → Python build hot path with
//! Django signal → Kafka → Rust build. The producer (merged in PR #62817) is a
//! dumb "team X changed, rebuild it" trigger; this consumer reads fresh DB state
//! at build time, so out-of-order delivery can never stamp stale content.
//!
//! Loop shape (architecture doc, "coalesce within a small window"):
//!   1. Batch-fetch up to N messages, bounded by a ~500ms coalesce window.
//!   2. Dedupe by `team_id` — an edit session firing 20 saves becomes one build.
//!   3. Build each unique team once, with bounded retries.
//!   4. Route teams that exhaust their retry budget to the DLQ.
//!   5. Commit offsets as a batch (only after the build outcome is decided).
//!
//! The lazy request-path fill stays as the final safety net: a stuck consumer
//! degrades latency, not correctness.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use axum::{routing::get, Router};
use chrono::{DateTime, Utc};
use common_database::{get_pool, PostgresReader};
use common_hypercache::writer::HyperCacheWriter;
use common_kafka::config::{ConsumerConfig, KafkaConfig};
use common_kafka::kafka_consumer::{Offset, RecvErr, SingleTopicConsumer};
use common_kafka::kafka_producer::{
    create_kafka_producer, send_keyed_iter_to_kafka_with_headers, KafkaContext,
};
use common_metrics::{setup_metrics_routes_for_product_with_overrides, Matcher};
use common_redis::CompressionConfig;
use common_types::TeamId;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Handle, Manager};
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::FutureProducer;
use tokio_util::sync::CancellationToken;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::EnvFilter;

use feature_flags::flags::cache_builder::build_flags_cache;
use feature_flags::flags::cache_invalidation::FlagsCacheInvalidation;
use feature_flags::flags::cache_writer::{self, persist_flags_cache};
use feature_flags::server::create_redis_client;

common_alloc::used!();

const SERVICE_NAME: &str = "flags-cache-builder";

/// Defaults used when `KAFKA_CONSUMER_GROUP` / `KAFKA_CONSUMER_TOPIC` are unset.
/// The charts deployment sets both explicitly; these keep local dev runnable.
const DEFAULT_CONSUMER_GROUP: &str = "flags-cache-builder";
const DEFAULT_CONSUMER_TOPIC: &str = "flags_cache_invalidation";

/// Logging tag passed to `create_redis_client`; appears in connection-retry logs.
const REDIS_CLIENT_TYPE: &str = "flags-cache-builder";
const REDIS_CONNECT_RETRIES: u32 = 3;

/// Backoff base for build retries. Attempts sleep base·4^(n-1): 200ms, 800ms.
const RETRY_BASE_MS: u64 = 200;
const RETRY_BACKOFF_MULTIPLIER: u64 = 4;

/// Pause after a batch that yielded only Kafka receive errors, to avoid hot-looping
/// (and log/CPU spam) while the broker is unreachable.
const KAFKA_RECV_ERROR_BACKOFF: Duration = Duration::from_millis(500);

/// Cap on the `x-dlq-error` header so an unusually long error can't blow Kafka's
/// header/message size limit and fail the DLQ produce. The full error is logged.
const DLQ_ERROR_HEADER_MAX: usize = 1024;

// Metric names. End-to-end latency buckets follow the architecture doc.
const MESSAGES_RECEIVED: &str = "flags_cache_builder_messages_received_total";
const BUILDS_TOTAL: &str = "flags_cache_builder_builds_total";
const BUILD_RETRIES: &str = "flags_cache_builder_build_retries_total";
const BUILD_DURATION_SECONDS: &str = "flags_cache_builder_build_duration_seconds";
const E2E_LATENCY_SECONDS: &str = "flags_cache_builder_end_to_end_latency_seconds";
const PARSE_ERRORS: &str = "flags_cache_builder_parse_errors_total";
const KAFKA_RECV_ERRORS: &str = "flags_cache_builder_kafka_recv_errors_total";
const DLQ_PRODUCED: &str = "flags_cache_builder_dlq_produced_total";
const COALESCED_TEAMS: &str = "flags_cache_builder_coalesced_teams";

const E2E_LATENCY_BUCKETS: &[f64] = &[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0];
/// Seconds buckets for the build-duration histogram. Our histograms are
/// seconds-shaped, so both are overridden off `common_metrics`' ms-shaped default.
const BUILD_DURATION_BUCKETS: &[f64] = &[0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0];

/// `product` global label for per-product metric cost attribution.
const METRICS_PRODUCT: &str = "feature_flags";

#[derive(Envconfig)]
struct InfraConfig {
    #[envconfig(
        from = "READ_DATABASE_URL",
        default = "postgres://posthog:posthog@localhost:5432/posthog"
    )]
    read_database_url: String,

    /// Dedicated flags Redis tier. Required: refusing to fall back to the shared
    /// `REDIS_URL` matches the warmer's `check_dedicated_cache_configured()` guard
    /// so we never write flags-cache entries into the wrong Redis.
    #[envconfig(from = "FLAGS_REDIS_URL", default = "")]
    flags_redis_url: String,

    #[envconfig(from = "OBJECT_STORAGE_BUCKET", default = "posthog")]
    object_storage_bucket: String,

    #[envconfig(from = "OBJECT_STORAGE_REGION", default = "us-east-1")]
    object_storage_region: String,

    #[envconfig(from = "OBJECT_STORAGE_ENDPOINT", default = "")]
    object_storage_endpoint: String,

    #[envconfig(from = "DATABASE_MAX_CONNECTIONS", default = "10")]
    database_max_connections: u32,

    #[envconfig(from = "FLAGS_REDIS_RESPONSE_TIMEOUT_MS", default = "1000")]
    redis_response_timeout_ms: u64,

    #[envconfig(from = "FLAGS_REDIS_CONNECTION_TIMEOUT_MS", default = "5000")]
    redis_connection_timeout_ms: u64,
}

#[derive(Envconfig, Clone)]
struct BuilderConfig {
    #[envconfig(from = "METRICS_PORT", default = "9090")]
    metrics_port: u16,

    /// Coalesce window: the longest we wait to fill a batch before building.
    #[envconfig(from = "FLAGS_CACHE_COALESCE_WINDOW_MS", default = "500")]
    coalesce_window_ms: u64,

    #[envconfig(from = "FLAGS_CACHE_MAX_BATCH", default = "256")]
    max_batch: usize,

    #[envconfig(from = "FLAGS_CACHE_BUILD_MAX_ATTEMPTS", default = "3")]
    build_max_attempts: u32,

    /// Cache TTL on write. Matches Django's `FLAGS_CACHE_TTL` default (7 days).
    #[envconfig(from = "FLAGS_CACHE_TTL", default = "604800")]
    cache_ttl_seconds: u64,

    #[envconfig(from = "KAFKA_DLQ_TOPIC", default = "flags_cache_invalidation_dlq")]
    dlq_topic: String,
}

/// All offsets and timing for a single team's coalesced invalidations.
struct TeamBatch {
    offsets: Vec<Offset>,
    /// Oldest `emitted_at` across the coalesced messages — the worst-case
    /// staleness the build resolves, which is what end-to-end latency measures.
    /// Also stamps the DLQ message if the build ultimately fails.
    oldest_emitted_at: DateTime<Utc>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    init_tracing();

    let infra = InfraConfig::init_from_env().expect("Invalid infrastructure configuration");
    let builder_cfg = BuilderConfig::init_from_env().expect("Invalid builder configuration");
    let kafka_cfg = KafkaConfig::init_from_env().expect("Invalid Kafka configuration");
    ConsumerConfig::set_defaults(DEFAULT_CONSUMER_GROUP, DEFAULT_CONSUMER_TOPIC, false);
    let consumer_cfg = ConsumerConfig::init_from_env().expect("Invalid consumer configuration");

    if infra.flags_redis_url.is_empty() {
        tracing::error!(
            "FLAGS_REDIS_URL is not set. Refusing to start — that would risk writing \
             flags-cache entries into the shared Redis tier. Set FLAGS_REDIS_URL."
        );
        std::process::exit(1);
    }

    tracing::info!(
        consumer_group = consumer_cfg.kafka_consumer_group,
        topic = consumer_cfg.kafka_consumer_topic,
        dlq_topic = builder_cfg.dlq_topic,
        coalesce_window_ms = builder_cfg.coalesce_window_ms,
        max_batch = builder_cfg.max_batch,
        build_max_attempts = builder_cfg.build_max_attempts,
        cache_ttl_seconds = builder_cfg.cache_ttl_seconds,
        "Starting {SERVICE_NAME}"
    );

    let mut manager = Manager::builder(SERVICE_NAME).build();
    let metrics_handle = manager.register(
        "metrics_server",
        ComponentOptions::new().is_observability(true),
    );
    let main_handle = manager.register(
        "main",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(15))
            .with_liveness_deadline(Duration::from_secs(60)),
    );
    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let monitor = manager.monitor_background();

    spawn_metrics_server(
        metrics_handle,
        readiness,
        liveness,
        builder_cfg.metrics_port,
    );

    let pg_pool = get_pool(&infra.read_database_url, infra.database_max_connections)
        .expect("Failed to create database pool");
    let pg_reader: PostgresReader = Arc::new(pg_pool);

    let writer = Arc::new(build_writer(&infra).await);

    let consumer = SingleTopicConsumer::new(kafka_cfg.clone(), consumer_cfg)
        .expect("Failed to create Kafka consumer");
    let dlq_producer = create_kafka_producer(&kafka_cfg, main_handle.clone())
        .await
        .expect("Failed to create DLQ Kafka producer");

    let loop_handle = main_handle.clone();
    // Drive the loop off the lifecycle manager's own shutdown token so SIGTERM
    // reaches the consumer directly. A private token would only be cancelled
    // after `monitor.wait()` returns — i.e. after the graceful window already
    // timed out — leaving the loop to be dropped mid-batch.
    let loop_shutdown = loop_handle.shutdown_token();
    tokio::spawn(async move {
        let _guard = loop_handle.process_scope();
        consume_loop(
            consumer,
            pg_reader,
            writer,
            dlq_producer,
            builder_cfg,
            loop_handle.clone(),
            loop_shutdown,
        )
        .await;
    });

    monitor.wait().await?;
    Ok(())
}

async fn build_writer(infra: &InfraConfig) -> HyperCacheWriter {
    tracing::info!("Connecting to Redis");
    let Some(redis_client) = create_redis_client(
        &infra.flags_redis_url,
        REDIS_CLIENT_TYPE,
        CompressionConfig::default(),
        infra.redis_response_timeout_ms,
        infra.redis_connection_timeout_ms,
        REDIS_CONNECT_RETRIES,
    )
    .await
    else {
        // create_redis_client logs the underlying error before returning None.
        std::process::exit(1);
    };
    let redis_client: Arc<dyn common_redis::Client + Send + Sync> = redis_client;

    cache_writer::build_writer(
        redis_client,
        &infra.object_storage_region,
        &infra.object_storage_bucket,
        Some(infra.object_storage_endpoint.as_str()),
    )
    .await
}

/// The consumer hot loop. Returns when `shutdown` is cancelled (graceful drain).
async fn consume_loop(
    consumer: SingleTopicConsumer,
    pg_reader: PostgresReader,
    writer: Arc<HyperCacheWriter>,
    dlq_producer: FutureProducer<KafkaContext>,
    cfg: BuilderConfig,
    health: Handle,
    shutdown: CancellationToken,
) {
    let coalesce = Duration::from_millis(cfg.coalesce_window_ms);

    loop {
        // Reporting healthy each iteration covers the idle case: with no traffic
        // the batch fetch returns empty after the coalesce window, so we still
        // tick well inside the liveness deadline.
        health.report_healthy();

        let batch = tokio::select! {
            _ = shutdown.cancelled() => break,
            batch = consumer.json_recv_batch::<FlagsCacheInvalidation>(cfg.max_batch, coalesce) => batch,
        };

        if batch.is_empty() {
            continue;
        }

        let (by_team, had_kafka_error) = coalesce_batch(batch);
        if by_team.is_empty() {
            // Batch held only poison pills or receive errors. Poison offsets were
            // auto-stored by json_recv, so commit to avoid reprocessing them.
            commit_offsets(&consumer);
            if had_kafka_error {
                // A receive error stores no offset, so there's nothing to make
                // progress on until the broker recovers — back off rather than
                // hot-loop on immediate errors.
                tokio::time::sleep(KAFKA_RECV_ERROR_BACKOFF).await;
            }
            continue;
        }

        metrics::histogram!(COALESCED_TEAMS).record(by_team.len() as f64);

        let mut interrupted = false;
        for (team_id, team_batch) in by_team {
            // Stop between teams once shutdown is signalled: a large batch (up to
            // max_batch unique teams, each with retry backoff) could otherwise
            // outrun the graceful-shutdown budget and be killed mid-build.
            if shutdown.is_cancelled() {
                interrupted = true;
                break;
            }
            // Also tick per team: a large batch of unique teams (with retry
            // backoff) could otherwise outlast the liveness deadline mid-batch.
            health.report_healthy();
            process_team(
                &pg_reader,
                &writer,
                &dlq_producer,
                &cfg,
                team_id,
                team_batch,
            )
            .await;
        }

        if interrupted {
            // Don't commit a partially processed batch. Kafka commits a single
            // per-partition high-water mark, and one partition holds many teams'
            // messages interleaved (each team is keyed to a partition, but a
            // partition carries many teams). Committing now would advance the
            // commit point past the offsets of teams we haven't built yet —
            // including any with a *lower* offset than a team we did build —
            // dropping their invalidations for good: the cache keeps serving the
            // stale entry, and the lazy request-path fill only rebuilds on a miss.
            // Leave the whole batch uncommitted so it re-delivers on restart;
            // builds are idempotent, so reprocessing the finished teams is cheap.
            break;
        }

        commit_offsets(&consumer);
    }

    tracing::info!("Consumer loop draining; offsets committed up to last batch");
}

/// Dedupe a fetched batch by `team_id`, counting received messages and errors.
/// Poison pills (parse failures) already had their offsets stored by `json_recv`;
/// Kafka receive errors stored nothing. Returns the per-team work plus whether a
/// Kafka receive error occurred, so the caller can back off instead of hot-looping
/// while the broker is unreachable.
fn coalesce_batch(
    batch: Vec<Result<(FlagsCacheInvalidation, Offset), RecvErr>>,
) -> (HashMap<TeamId, TeamBatch>, bool) {
    let mut by_team: HashMap<TeamId, TeamBatch> = HashMap::new();
    let mut received: u64 = 0;
    let mut had_kafka_error = false;

    for result in batch {
        match result {
            Ok((msg, offset)) => {
                received += 1;
                let entry = by_team.entry(msg.team_id).or_insert_with(|| TeamBatch {
                    offsets: Vec::new(),
                    oldest_emitted_at: msg.emitted_at,
                });
                if msg.emitted_at < entry.oldest_emitted_at {
                    entry.oldest_emitted_at = msg.emitted_at;
                }
                entry.offsets.push(offset);
            }
            // A receive error is a broker/transport problem, not a bad message:
            // nothing was consumed and no offset was stored. Track it apart from
            // poison pills so `parse_errors` stays meaningful.
            Err(RecvErr::Kafka(e)) => {
                had_kafka_error = true;
                metrics::counter!(KAFKA_RECV_ERRORS).increment(1);
                tracing::warn!(error = %e, "Kafka receive error");
            }
            Err(e) => {
                metrics::counter!(PARSE_ERRORS).increment(1);
                tracing::warn!(error = %e, "Skipping unparseable invalidation (offset auto-stored)");
            }
        }
    }

    metrics::counter!(MESSAGES_RECEIVED).increment(received);
    (by_team, had_kafka_error)
}

/// Build one team's cache, routing to the DLQ on terminal failure. Offsets are
/// stored either way — a poison message must not wedge the partition forever;
/// the DLQ is the durable record for triage.
async fn process_team(
    pg_reader: &PostgresReader,
    writer: &HyperCacheWriter,
    dlq_producer: &FutureProducer<KafkaContext>,
    cfg: &BuilderConfig,
    team_id: TeamId,
    team_batch: TeamBatch,
) {
    match build_with_retry(pg_reader, writer, team_id, cfg).await {
        Ok(()) => {
            metrics::counter!(BUILDS_TOTAL, "result" => "ok").increment(1);
            let latency = (Utc::now() - team_batch.oldest_emitted_at)
                .num_milliseconds()
                .max(0) as f64
                / 1000.0;
            metrics::histogram!(E2E_LATENCY_SECONDS).record(latency);
        }
        Err(err) => {
            metrics::counter!(BUILDS_TOTAL, "result" => "error").increment(1);
            tracing::error!(team_id, error = %err, "Cache build failed after retries; routing to DLQ");
            // The message is a trigger, not a payload, so reconstruct it for the
            // DLQ from the team and its oldest coalesced timestamp.
            let dlq_message = FlagsCacheInvalidation::new(team_id, team_batch.oldest_emitted_at);
            dlq_produce(dlq_producer, &cfg.dlq_topic, &dlq_message, &err).await;
        }
    }

    // Store offsets regardless of build/DLQ outcome. Kafka commits a single
    // per-partition high-water mark, not a set, so we can't selectively skip one
    // failed message's offset while committing later ones from the same partition
    // — the later commit subsumes it. A DLQ-produce failure (rare; same cluster
    // as the source topic) therefore loses the triage record, but never flag data:
    // the lazy request-path fill rebuilds on the next /flags request. That failure
    // is surfaced loudly via the error log above and the DLQ_PRODUCED{result=error}
    // counter — alert on it rather than wedging the partition.
    store_offsets(team_batch.offsets);
}

async fn build_with_retry(
    pg_reader: &PostgresReader,
    writer: &HyperCacheWriter,
    team_id: TeamId,
    cfg: &BuilderConfig,
) -> Result<(), String> {
    let mut attempt: u32 = 0;
    loop {
        attempt += 1;
        let start = Instant::now();
        match build_once(pg_reader, writer, team_id, cfg.cache_ttl_seconds).await {
            Ok(()) => {
                metrics::histogram!(BUILD_DURATION_SECONDS).record(start.elapsed().as_secs_f64());
                return Ok(());
            }
            Err(e) => {
                if attempt >= cfg.build_max_attempts {
                    return Err(e.to_string());
                }
                metrics::counter!(BUILD_RETRIES).increment(1);
                let backoff = Duration::from_millis(
                    RETRY_BASE_MS.saturating_mul(RETRY_BACKOFF_MULTIPLIER.pow(attempt - 1)),
                );
                tracing::warn!(
                    team_id,
                    attempt,
                    error = %e,
                    backoff_ms = backoff.as_millis() as u64,
                    "Cache build attempt failed; retrying"
                );
                tokio::time::sleep(backoff).await;
            }
        }
    }
}

async fn build_once(
    pg_reader: &PostgresReader,
    writer: &HyperCacheWriter,
    team_id: TeamId,
    ttl_seconds: u64,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let cache = build_flags_cache(pg_reader.clone(), team_id).await?;
    persist_flags_cache(writer, team_id, &cache, ttl_seconds).await
}

/// Cap an error string to `DLQ_ERROR_HEADER_MAX` bytes for use as a Kafka header
/// value, truncating on a char boundary so the result stays valid UTF-8.
fn truncate_for_header(error: &str) -> String {
    if error.len() <= DLQ_ERROR_HEADER_MAX {
        return error.to_string();
    }
    const ELLIPSIS: &str = "…";
    // Reserve room for the ellipsis so the result — marker included — stays within
    // the byte cap. The ellipsis is 3 bytes, so slicing to the cap and appending it
    // would otherwise overshoot.
    let mut end = DLQ_ERROR_HEADER_MAX - ELLIPSIS.len();
    while !error.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}{ELLIPSIS}", &error[..end])
}

/// Re-produce the failed invalidation to the DLQ verbatim (so it stays a valid
/// v1 message, replayable by this same consumer), with the failure reason in
/// headers. Keyed by `team_id` to preserve partition affinity.
async fn dlq_produce(
    dlq_producer: &FutureProducer<KafkaContext>,
    topic: &str,
    message: &FlagsCacheInvalidation,
    error: &str,
) {
    let failed_at = Utc::now().to_rfc3339();
    let team_key = message.team_id.to_string();
    let error_header = truncate_for_header(error);
    let results = send_keyed_iter_to_kafka_with_headers(
        dlq_producer,
        topic,
        |_: &FlagsCacheInvalidation| Some(team_key.clone()),
        |_: &FlagsCacheInvalidation| {
            Some(
                OwnedHeaders::new()
                    .insert(Header {
                        key: "x-dlq-error",
                        value: Some(error_header.as_str()),
                    })
                    .insert(Header {
                        key: "x-dlq-failed-at",
                        value: Some(failed_at.as_str()),
                    }),
            )
        },
        std::iter::once(message.clone()),
    )
    .await;

    match results.into_iter().next() {
        Some(Ok(())) => metrics::counter!(DLQ_PRODUCED, "result" => "ok").increment(1),
        Some(Err(e)) => {
            metrics::counter!(DLQ_PRODUCED, "result" => "error").increment(1);
            tracing::error!(team_id = message.team_id, error = %e, "Failed to produce to DLQ");
        }
        None => {}
    }
}

fn store_offsets(offsets: Vec<Offset>) {
    for offset in offsets {
        if let Err(e) = offset.store() {
            tracing::warn!(error = %e, "Failed to store offset");
        }
    }
}

fn commit_offsets(consumer: &SingleTopicConsumer) {
    if let Err(e) = consumer.commit() {
        tracing::warn!(error = %e, "Failed to commit offsets");
    }
}

fn init_tracing() {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .json()
        .init();
}

fn spawn_metrics_server(
    handle: lifecycle::Handle,
    readiness: lifecycle::ReadinessHandler,
    liveness: lifecycle::LivenessHandler,
    port: u16,
) {
    tokio::spawn(async move {
        let _guard = handle.process_scope();

        let health_router = Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let r = readiness.clone();
                    async move { r.check().await }
                }),
            )
            .route("/_liveness", get(move || async move { liveness.check() }));

        // Reuse the crate's shared recorder/router setup (prometheus install +
        // /metrics + product label + HTTP metrics middleware), overriding the two
        // seconds-shaped histograms off its ms-shaped default buckets.
        let overrides = [
            (
                Matcher::Full(BUILD_DURATION_SECONDS.to_string()),
                BUILD_DURATION_BUCKETS,
            ),
            (
                Matcher::Full(E2E_LATENCY_SECONDS.to_string()),
                E2E_LATENCY_BUCKETS,
            ),
        ];
        let router = setup_metrics_routes_for_product_with_overrides(
            health_router,
            METRICS_PRODUCT,
            &overrides,
        );

        let bind = format!("0.0.0.0:{port}");
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        tracing::info!("Metrics server listening on {}", bind);
        axum::serve(listener, router)
            .with_graceful_shutdown(handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });
}
