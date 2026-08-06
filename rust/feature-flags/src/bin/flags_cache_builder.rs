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

use std::collections::hash_map::Entry;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use axum::{routing::get, Router};
use chrono::{DateTime, Utc};
use common_database::{get_pool, PostgresReader};
use common_hypercache::writer::HyperCacheWriter;
use common_hypercache::HyperCacheError;
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
use feature_flags::flags::cache_writer::{self, persist_flags_cache, PersistOutcome};
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
const BUILD_DURATION_BUCKETS: &[f64] = &[
    0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0,
];

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

/// All offsets and timing for a single team's coalesced invalidations. Generic
/// over the offset type so the coalescing logic stays testable without
/// constructing `Offset` values (which have no public constructor).
struct TeamBatch<O = Offset> {
    offsets: Vec<O>,
    /// Oldest `emitted_at` across the coalesced messages — the worst-case
    /// staleness the build resolves, which is what end-to-end latency measures.
    /// Also stamps the DLQ message if the build ultimately fails.
    oldest_emitted_at: DateTime<Utc>,
}

impl<O> TeamBatch<O> {
    /// Fold one coalesced message into the per-team map: append its offset and
    /// keep the oldest `emitted_at` seen for the team, regardless of arrival order.
    fn fold_into(
        by_team: &mut HashMap<TeamId, TeamBatch<O>>,
        team_id: TeamId,
        emitted_at: DateTime<Utc>,
        offset: O,
    ) {
        let entry = by_team.entry(team_id).or_insert_with(|| TeamBatch {
            offsets: Vec::new(),
            oldest_emitted_at: emitted_at,
        });
        if emitted_at < entry.oldest_emitted_at {
            entry.oldest_emitted_at = emitted_at;
        }
        entry.offsets.push(offset);
    }
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
        // Collect every processed offset and store the per-partition max once, at
        // the end of the batch. `by_team` is a HashMap, so we build teams in
        // arbitrary order; storing each team's offsets as we go could check-point a
        // partition *backwards* (one partition carries many teams' interleaved
        // messages), needlessly reprocessing on the next restart. See
        // `store_max_offsets_per_partition`.
        let mut batch_offsets: Vec<Offset> = Vec::new();
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
            let offsets = process_team(
                &pg_reader,
                &writer,
                &dlq_producer,
                &cfg,
                team_id,
                team_batch,
            )
            .await;
            batch_offsets.extend(offsets);
        }

        if interrupted {
            // Don't store or commit a partially processed batch. Kafka commits a
            // single per-partition high-water mark, and one partition holds many
            // teams' messages interleaved (each team is keyed to a partition, but a
            // partition carries many teams). Advancing the commit point now would
            // move it past the offsets of teams we haven't built yet — including
            // any with a *lower* offset than a team we did build — dropping their
            // invalidations for good: the cache keeps serving the stale entry, and
            // the lazy request-path fill only rebuilds on a miss. Leaving
            // `batch_offsets` unstored means the whole batch re-delivers on
            // restart; builds are idempotent, so reprocessing finished teams is
            // cheap.
            break;
        }

        store_max_offsets_per_partition(batch_offsets);
        commit_offsets(&consumer);
    }

    // On a mid-batch interrupt we break *before* committing, so the commit point
    // is the last fully processed batch — not necessarily the last one fetched.
    tracing::info!("Consumer loop draining; offsets committed up to last fully processed batch");
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
                TeamBatch::fold_into(&mut by_team, msg.team_id, msg.emitted_at, offset);
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

/// Build one team's cache, routing to the DLQ on terminal failure, and return the
/// team's offsets for the caller to store. Offsets are returned (and later stored)
/// regardless of build/DLQ outcome — a poison message must not wedge the partition
/// forever; the DLQ is the durable record for triage.
async fn process_team(
    pg_reader: &PostgresReader,
    writer: &HyperCacheWriter,
    dlq_producer: &FutureProducer<KafkaContext>,
    cfg: &BuilderConfig,
    team_id: TeamId,
    team_batch: TeamBatch,
) -> Vec<Offset> {
    match build_with_retry(pg_reader, writer, team_id, cfg).await {
        Ok(()) => {
            metrics::counter!(BUILDS_TOTAL, "result" => "success").increment(1);
            let latency = (Utc::now() - team_batch.oldest_emitted_at)
                .num_milliseconds()
                .max(0) as f64
                / 1000.0;
            metrics::histogram!(E2E_LATENCY_SECONDS).record(latency);
        }
        Err(failure) => {
            metrics::counter!(BUILDS_TOTAL, "result" => "failure", "reason" => failure.category)
                .increment(1);
            tracing::error!(team_id, category = failure.category, error = %failure.message, "Cache build failed after retries; routing to DLQ");
            // The message is a trigger, not a payload, so reconstruct it for the
            // DLQ from the team and its oldest coalesced timestamp.
            let dlq_message = FlagsCacheInvalidation::new(team_id, team_batch.oldest_emitted_at);
            dlq_produce(dlq_producer, &cfg.dlq_topic, &dlq_message, &failure).await;
        }
    }

    // Return offsets regardless of build/DLQ outcome. Kafka commits a single
    // per-partition high-water mark, not a set, so we can't selectively skip one
    // failed message's offset while committing later ones from the same partition
    // — the later commit subsumes it. A DLQ-produce failure (rare; same cluster
    // as the source topic) therefore loses the triage record, but never flag data:
    // the lazy request-path fill rebuilds on the next /flags request. That failure
    // is surfaced loudly via the error log above and the DLQ_PRODUCED{result=failure}
    // counter — alert on it rather than wedging the partition.
    team_batch.offsets
}

/// A terminal build failure tagged with the tier that failed, so the error metric
/// and DLQ headers can attribute it — that tier (database / redis / s3 / serialize)
/// is the triage signal the DLQ exists to provide. `category` is a fixed set of
/// `&'static str`, safe to use as a metric label without cardinality risk.
struct BuildFailure {
    category: &'static str,
    message: String,
}

impl BuildFailure {
    /// A failure reading flag/cohort state from Postgres (the `build_flags_cache`
    /// step). The whole step is DB-bound on this path, so it's attributed wholesale.
    fn database(err: impl std::fmt::Display) -> Self {
        Self {
            category: "database",
            message: err.to_string(),
        }
    }

    /// A failure persisting the built cache, attributed to the HyperCache tier that
    /// failed. `Timeout`/`CacheMiss`/`Pickle` don't occur on the write path, so they
    /// fall through to `other`.
    fn from_persist(err: HyperCacheError) -> Self {
        let category = match err {
            HyperCacheError::Redis(_) => "redis",
            HyperCacheError::S3(_) => "s3",
            HyperCacheError::Json(_) => "serialize",
            _ => "other",
        };
        Self {
            category,
            message: err.to_string(),
        }
    }
}

async fn build_with_retry(
    pg_reader: &PostgresReader,
    writer: &HyperCacheWriter,
    team_id: TeamId,
    cfg: &BuilderConfig,
) -> Result<(), BuildFailure> {
    let mut attempt: u32 = 0;
    loop {
        attempt += 1;
        let start = Instant::now();
        match build_once(pg_reader, writer, team_id, cfg.cache_ttl_seconds).await {
            Ok(outcome) => {
                let elapsed = start.elapsed();
                metrics::histogram!(BUILD_DURATION_SECONDS).record(elapsed.as_secs_f64());
                tracing::info!(
                    team_id,
                    attempt,
                    duration_ms = elapsed.as_millis() as u64,
                    size_bytes = outcome.size_bytes,
                    etag = %outcome.etag,
                    "Built flags cache"
                );
                return Ok(());
            }
            Err(failure) => {
                if attempt >= cfg.build_max_attempts {
                    return Err(failure);
                }
                metrics::counter!(BUILD_RETRIES).increment(1);
                let backoff = retry_backoff(attempt);
                tracing::warn!(
                    team_id,
                    attempt,
                    category = failure.category,
                    error = %failure.message,
                    backoff_ms = backoff.as_millis() as u64,
                    "Cache build attempt failed; retrying"
                );
                tokio::time::sleep(backoff).await;
            }
        }
    }
}

/// Backoff before the `attempt`-th retry (1-indexed): `base · multiplier^(attempt-1)`,
/// i.e. 200ms, 800ms, … `saturating_pow`/`saturating_mul` keep an unusually high
/// `build_max_attempts` from overflowing rather than panicking in debug.
fn retry_backoff(attempt: u32) -> Duration {
    Duration::from_millis(
        RETRY_BASE_MS.saturating_mul(RETRY_BACKOFF_MULTIPLIER.saturating_pow(attempt - 1)),
    )
}

async fn build_once(
    pg_reader: &PostgresReader,
    writer: &HyperCacheWriter,
    team_id: TeamId,
    ttl_seconds: u64,
) -> Result<PersistOutcome, BuildFailure> {
    let cache = build_flags_cache(pg_reader.clone(), team_id)
        .await
        .map_err(BuildFailure::database)?;
    persist_flags_cache(writer, team_id, &cache, ttl_seconds)
        .await
        .map_err(BuildFailure::from_persist)
}

/// Cap an error string to `DLQ_ERROR_HEADER_MAX` bytes for use as a Kafka header
/// value, truncating on a char boundary so the result stays valid UTF-8.
fn truncate_for_header(error: &str) -> String {
    const ELLIPSIS: &str = "…";
    const _: () = assert!(
        DLQ_ERROR_HEADER_MAX > ELLIPSIS.len(),
        "DLQ_ERROR_HEADER_MAX must be larger than the ellipsis marker"
    );
    if error.len() <= DLQ_ERROR_HEADER_MAX {
        return error.to_string();
    }
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
    failure: &BuildFailure,
) {
    let failed_at = Utc::now().to_rfc3339();
    let team_key = message.team_id.to_string();
    let error_header = truncate_for_header(&failure.message);
    let category = failure.category;
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
                    // The failed tier (database / redis / s3 / serialize / other),
                    // split out so triage can filter the DLQ by cause without parsing
                    // the free-form error message.
                    .insert(Header {
                        key: "x-dlq-error-category",
                        value: Some(category),
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
        Some(Ok(())) => metrics::counter!(DLQ_PRODUCED, "result" => "success").increment(1),
        Some(Err(e)) => {
            metrics::counter!(DLQ_PRODUCED, "result" => "failure").increment(1);
            tracing::error!(team_id = message.team_id, error = %e, "Failed to produce to DLQ");
        }
        None => {}
    }
}

/// Store the highest offset per partition and drop the rest. A committed offset N
/// implies every offset ≤ N on that partition is committed, so keeping only the max
/// is sufficient — and necessary: teams are processed in arbitrary `HashMap` order,
/// and rdkafka's `store_offset` overwrites the stored offset for a `(topic,
/// partition)` rather than keeping the max, so storing each offset blindly could
/// regress a partition's commit point. That only ever causes idempotent
/// reprocessing on the next restart (never dropped invalidations), but keeping the
/// commit point monotonic avoids it. Max-per-partition is safe because
/// `json_recv_batch` stops at the first receive error, so a batch is a contiguous
/// run of messages per partition with no gaps below the max.
///
/// This makes the *built teams'* offsets monotonic among themselves. Poison pills
/// auto-store their (possibly higher) offset inside `json_recv` and aren't visible
/// here, so absolute monotonicity across all messages isn't guaranteed — that
/// residual is pre-existing and benign (idempotent re-skip on replay).
fn store_max_offsets_per_partition(offsets: Vec<Offset>) {
    for offset in max_per_partition(offsets, Offset::partition, Offset::get_value) {
        if let Err(e) = offset.store() {
            tracing::warn!(error = %e, "Failed to store offset");
        }
    }
}

/// Reduce `items` to the single highest-`value` item per `partition`, dropping the
/// rest. Input order is irrelevant — the result holds one item per distinct
/// partition, each the max by `value`. Extracted from `store_max_offsets_per_partition`
/// so the selection logic is testable without constructing `Offset` values.
fn max_per_partition<T>(
    items: Vec<T>,
    partition: impl Fn(&T) -> i32,
    value: impl Fn(&T) -> i64,
) -> Vec<T> {
    let mut highest: HashMap<i32, T> = HashMap::new();
    for item in items {
        match highest.entry(partition(&item)) {
            Entry::Occupied(mut e) if value(&item) > value(e.get()) => {
                e.insert(item);
            }
            Entry::Occupied(_) => {}
            Entry::Vacant(e) => {
                e.insert(item);
            }
        }
    }
    highest.into_values().collect()
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

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use chrono::{DateTime, TimeZone, Utc};

    use super::{
        max_per_partition, retry_backoff, truncate_for_header, BuildFailure, TeamBatch,
        DLQ_ERROR_HEADER_MAX,
    };

    // (partition, offset) pairs; keyed and valued by the two fields.
    fn reduce(items: Vec<(i32, i64)>) -> Vec<(i32, i64)> {
        let mut out = max_per_partition(items, |&(p, _)| p, |&(_, o)| o);
        out.sort_unstable();
        out
    }

    fn ts(secs: i64) -> DateTime<Utc> {
        Utc.timestamp_opt(secs, 0)
            .single()
            .expect("valid timestamp")
    }

    /// Fold a list of (team_id, emitted_at, offset) into per-team batches via the
    /// same `TeamBatch::fold_into` the consumer uses. Offset type is `u64` here —
    /// the production `Offset` has no public constructor, which is why the helper
    /// is generic.
    fn coalesce(items: Vec<(i32, DateTime<Utc>, u64)>) -> HashMap<i32, (DateTime<Utc>, Vec<u64>)> {
        let mut by_team: HashMap<i32, TeamBatch<u64>> = HashMap::new();
        for (team_id, emitted_at, offset) in items {
            TeamBatch::fold_into(&mut by_team, team_id, emitted_at, offset);
        }
        by_team
            .into_iter()
            .map(|(team, batch)| (team, (batch.oldest_emitted_at, batch.offsets)))
            .collect()
    }

    #[test]
    fn coalesce_keeps_oldest_emitted_at_regardless_of_arrival_order() {
        // Same team, timestamps arriving newest-first: the oldest must still win,
        // since that worst-case staleness is what the e2e-latency metric measures.
        let got = coalesce(vec![(7, ts(300), 0), (7, ts(100), 1), (7, ts(200), 2)]);
        let (oldest, offsets) = &got[&7];
        assert_eq!(*oldest, ts(100));
        assert_eq!(offsets, &vec![0, 1, 2]);
    }

    #[test]
    fn coalesce_groups_offsets_per_team() {
        let got = coalesce(vec![(1, ts(50), 10), (2, ts(60), 20), (1, ts(40), 11)]);
        assert_eq!(got.len(), 2);
        assert_eq!(got[&1].0, ts(40));
        assert_eq!(got[&1].1, vec![10, 11]);
        assert_eq!(got[&2].0, ts(60));
        assert_eq!(got[&2].1, vec![20]);
    }

    #[test]
    fn retry_backoff_follows_documented_schedule() {
        // 200ms · 4^(n-1): the first two retries are the 200ms / 800ms the module
        // doc and PR describe.
        assert_eq!(retry_backoff(1).as_millis(), 200);
        assert_eq!(retry_backoff(2).as_millis(), 800);
        assert_eq!(retry_backoff(3).as_millis(), 3200);
    }

    #[test]
    fn retry_backoff_saturates_instead_of_overflowing() {
        // A large `build_max_attempts` must not panic on the exponent — the
        // multiplier saturates to u64::MAX, capping the sleep rather than wrapping.
        assert_eq!(retry_backoff(u32::MAX).as_millis(), u64::MAX as u128);
    }

    #[test]
    fn truncate_for_header_passes_short_errors_through() {
        assert_eq!(truncate_for_header("boom"), "boom");
    }

    #[test]
    fn build_failure_attributes_persist_errors_to_their_tier() {
        use common_hypercache::HyperCacheError;
        use common_redis::CustomRedisError;
        use common_s3::S3Error;

        // The category is the triage signal the DLQ exists for, so each HyperCache
        // tier must map to its own label; unexpected variants degrade to "other"
        // rather than being mislabelled.
        let cases = [
            (HyperCacheError::Redis(CustomRedisError::Timeout), "redis"),
            (
                HyperCacheError::S3(S3Error::OperationFailed("boom".into())),
                "s3",
            ),
            (
                HyperCacheError::Json(serde_json::from_str::<i32>("x").unwrap_err()),
                "serialize",
            ),
            (HyperCacheError::CacheMiss, "other"),
        ];
        for (err, expected) in cases {
            assert_eq!(BuildFailure::from_persist(err).category, expected);
        }
    }

    #[test]
    fn build_failure_attributes_build_step_to_database() {
        assert_eq!(
            BuildFailure::database("pg unreachable").category,
            "database"
        );
    }

    #[test]
    fn truncate_for_header_stays_within_cap_on_char_boundary() {
        // Multibyte chars (3 bytes each) so the cap lands mid-character: the
        // truncation must back up to a char boundary and stay valid UTF-8.
        let long = "✓".repeat(DLQ_ERROR_HEADER_MAX); // 3 · 1024 bytes, well over the cap
        let got = truncate_for_header(&long);
        assert!(got.len() <= DLQ_ERROR_HEADER_MAX, "exceeded byte cap");
        assert!(got.ends_with('…'), "missing truncation marker");
        // `String` is UTF-8 by construction; reaching here without a slice panic is
        // the real assertion.
    }

    #[test]
    fn keeps_highest_offset_per_partition() {
        // Interleaved, out-of-order input across two partitions.
        let got = reduce(vec![(0, 5), (1, 2), (0, 3), (1, 10), (0, 8)]);
        assert_eq!(got, vec![(0, 8), (1, 10)]);
    }

    #[test]
    fn ascending_input_keeps_last() {
        let got = reduce(vec![(0, 1), (0, 2), (0, 3)]);
        assert_eq!(got, vec![(0, 3)]);
    }

    #[test]
    fn descending_input_keeps_first() {
        // The max must win regardless of arrival order — a later lower offset
        // must not regress the partition's checkpoint.
        let got = reduce(vec![(0, 3), (0, 2), (0, 1)]);
        assert_eq!(got, vec![(0, 3)]);
    }

    #[test]
    fn empty_input_yields_empty() {
        assert!(reduce(vec![]).is_empty());
    }

    #[test]
    fn single_offset_per_partition_passes_through() {
        let got = reduce(vec![(0, 7), (1, 4), (2, 9)]);
        assert_eq!(got, vec![(0, 7), (1, 4), (2, 9)]);
    }
}
