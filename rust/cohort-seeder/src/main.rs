//! Binary entry point: parses `Config`, builds the infra clients, and hands the wired orchestrator to
//! the `lifecycle::Manager`. Depends on `app`, `clickhouse`, `kafka`, `config`, and `observability` —
//! the composition root at the top of the stack.

use std::num::NonZeroUsize;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use common_database::get_pool_with_config;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use tokio::net::TcpListener;
use tracing::info;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter, Layer};

use cohort_seeder::app::completion::verify_marker_topic;
use cohort_seeder::app::{
    AutoDispatchPolicy, CompletionDriver, KafkaCommittedOffsets, KafkaTopicOffsets,
    MarkerWatchTask, ObservePolicy, OrchestratorSettings, PersonComponents, PgMarkerFlush,
    SeederOrchestrator, WatchDirectives, MARKER_WATCH_LIVENESS_DEADLINE,
    ORCHESTRATOR_LIVENESS_DEADLINE,
};
use cohort_seeder::clickhouse::client::build_client;
use cohort_seeder::clickhouse::person_scanner::PersonScanner;
use cohort_seeder::clickhouse::scanner::ChunkScanner;
use cohort_seeder::config::Config;
use cohort_seeder::kafka::committed::SeedGroupOffsetReader;
use cohort_seeder::kafka::markers::MarkerWatcher;
use cohort_seeder::kafka::pacing::TilePacer;
use cohort_seeder::kafka::producer::SeedTileProducer;
use cohort_seeder::observability;
use cohort_seeder::store::runs::RunKind;

common_alloc::used!();

const SERVICE_NAME: &str = "cohort-seeder";
const PARTITION_VERIFY_TIMEOUT: Duration = Duration::from_secs(10);

fn main() -> Result<()> {
    let config = Config::init_from_env().context("loading cohort-seeder configuration")?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("building tokio runtime")?;
    runtime.block_on(async_main(config))
}

async fn async_main(config: Config) -> Result<()> {
    init_tracing();
    log_startup(&config);

    let observe_policy =
        ObservePolicy::from_config(&config).context("validating reconcile observer policy")?;

    let mut manager = Manager::builder(SERVICE_NAME)
        .with_global_shutdown_timeout(Duration::from_secs(30))
        .build();
    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));
    let seeder_handle = manager.register(
        "seeder",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(30))
            .with_liveness_deadline(ORCHESTRATOR_LIVENESS_DEADLINE)
            .with_stall_threshold(3),
    );
    // The marker-watch task is the binary's second lifecycle component, registered only when the
    // observer gate is on.
    let watch_handle = match observe_policy {
        ObservePolicy::Enabled => Some(
            manager.register(
                "marker-watch",
                ComponentOptions::new()
                    .with_graceful_shutdown(Duration::from_secs(30))
                    .with_liveness_deadline(MARKER_WATCH_LIVENESS_DEADLINE)
                    .with_stall_threshold(3),
            ),
        ),
        ObservePolicy::Disabled => None,
    };
    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let recorder = config
        .export_prometheus
        .then(observability::metrics::install_recorder)
        .transpose()
        .context("installing Prometheus recorder")?;

    let pool = get_pool_with_config(&config.database_url, config.pool_config())
        .context("creating cohort-seeder PostgreSQL pool")?;
    let clickhouse_client = build_client(&config).context("building ClickHouse client")?;
    let scanner = ChunkScanner::new(clickhouse_client.clone());
    let producer = SeedTileProducer::new(
        &config.build_kafka_config(),
        config.seed_events_topic.clone(),
    )
    .await
    .context("creating seed tile producer")?;
    let verify_producer = producer.clone();
    let expected_partitions = config.cohort_partition_count;
    tokio::task::spawn_blocking(move || {
        verify_producer.verify_partition_count(expected_partitions, PARTITION_VERIFY_TIMEOUT)
    })
    .await
    .context("joining seed topic verification task")?
    .context("verifying seed topic partition count")?;
    let pacer = TilePacer::new(
        config
            .tiles_per_second()
            .context("validating seed tile rate")?,
    );
    let settings =
        OrchestratorSettings::try_from(&config).context("validating orchestrator settings")?;
    // Shares the built ClickHouse client with the behavioral scanner.
    let person = settings.person().map(|person_settings| PersonComponents {
        scanner: PersonScanner::new(clickhouse_client),
        pacer: TilePacer::new(person_settings.seeds_per_sec),
    });
    let completion = build_completion(
        &config,
        settings.completion_kinds(),
        &pool,
        &producer,
        observe_policy,
        watch_handle,
    )
    .await
    .context("validating completion driver policies")?;
    let claimed_by = format!("cohort-seeder:{}", uuid::Uuid::now_v7());
    let orchestrator = SeederOrchestrator::new(
        pool,
        scanner,
        producer,
        pacer,
        config.team_allowlist.clone(),
        settings,
        seeder_handle,
        claimed_by,
        completion.driver,
        person,
    );

    let guard = manager.monitor_background();
    tokio::spawn(orchestrator.process());
    if let Some(watch_task) = completion.watch_task {
        tokio::spawn(watch_task.run());
    }

    let app = observability::health::router(SERVICE_NAME, readiness, liveness, recorder);
    let bind = config.bind_address();
    info!(address = %bind, "observability server starting");
    let listener = TcpListener::bind(&bind)
        .await
        .with_context(|| format!("binding observability server to {bind}"))?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await
        .context("serving observability endpoints")?;
    metrics_handle.work_completed();

    guard.wait().await?;
    info!(service = SERVICE_NAME, "service stopped");
    Ok(())
}

/// The wired completion components: the driver ticked from the orchestrator (with whichever halves
/// the policies armed) and the marker-watch task to spawn when the observer is on.
struct WiredCompletion {
    driver: Option<CompletionDriver>,
    watch_task: Option<MarkerWatchTask<MarkerWatcher, PgMarkerFlush>>,
}

/// Build the completion driver from the two independent gates. Auto-dispatch arms the dispatch half
/// (CAS + tile produce + record); the observer arms the observation half (marker-watch directives +
/// the observation pass) and its dedicated watch task. Either half alone is valid; both off leaves the
/// dark path with no extra queries. A misconfigured policy (dispatch enabled without attestation, or a
/// non-contract partition count) is a startup error, as is an unreachable marker topic — a typo'd
/// name would otherwise surface only as runs stuck re-dispatching forever.
async fn build_completion(
    config: &Config,
    kinds: &'static [RunKind],
    pool: &sqlx::PgPool,
    producer: &SeedTileProducer,
    observe_policy: ObservePolicy,
    watch_handle: Option<lifecycle::Handle>,
) -> Result<WiredCompletion> {
    let dispatch_policy = AutoDispatchPolicy::from_config(config)
        .context("validating auto reconcile dispatch policy")?;
    if matches!(dispatch_policy, AutoDispatchPolicy::Disabled)
        && observe_policy == ObservePolicy::Disabled
    {
        return Ok(WiredCompletion {
            driver: None,
            watch_task: None,
        });
    }

    // Both halves anchor on the marker topic — dispatch captures its watermarks, the observer watches
    // it for markers — so prove it is reachable before either arms.
    verify_marker_topic(producer, &config.cohort_reconcile_markers_topic).await?;

    let mut driver = CompletionDriver::new(
        pool.clone(),
        config.team_allowlist.clone(),
        kinds,
        config.cohort_reconcile_markers_topic.clone(),
    );

    if let AutoDispatchPolicy::Enabled(register_backfill) = dispatch_policy {
        let max_inflight = NonZeroUsize::new(config.seeder_max_inflight_tiles)
            .context("SEEDER_MAX_INFLIGHT_TILES must be greater than zero")?;
        let max_concurrent_dispatches =
            NonZeroUsize::new(config.seeder_reconcile_max_concurrent_dispatches)
                .context("SEEDER_RECONCILE_MAX_CONCURRENT_DISPATCHES must be greater than zero")?;
        driver = driver.with_dispatch(
            producer.clone(),
            max_inflight,
            max_concurrent_dispatches,
            register_backfill,
        );
    }

    let watch_task = match observe_policy {
        ObservePolicy::Disabled => None,
        ObservePolicy::Enabled => {
            let handle = watch_handle
                .context("the marker-watch component must be registered when the observer is on")?;
            // A zero interval would panic tokio's interval timer; a zero batch would flush per message.
            if config.seeder_reconcile_persist_interval_ms == 0 {
                anyhow::bail!("SEEDER_RECONCILE_PERSIST_INTERVAL_MS must be greater than zero");
            }
            if config.seeder_reconcile_persist_max_batch == 0 {
                anyhow::bail!("SEEDER_RECONCILE_PERSIST_MAX_BATCH must be greater than zero");
            }
            // The flush tick is the watch task's only heartbeat while the topic is idle, so too long
            // an interval gets a healthy-but-idle task killed as stalled.
            let persist_interval =
                Duration::from_millis(config.seeder_reconcile_persist_interval_ms);
            if persist_interval > MARKER_WATCH_LIVENESS_DEADLINE / 2 {
                anyhow::bail!(
                    "SEEDER_RECONCILE_PERSIST_INTERVAL_MS must be at most half the marker-watch \
                     liveness deadline ({}ms)",
                    MARKER_WATCH_LIVENESS_DEADLINE.as_millis() / 2
                );
            }
            // A zero timeout fails every OffsetFetch and watermark call rather than disabling the
            // timeout, silently dropping the liveness signal.
            if config.seeder_reconcile_offsets_timeout_ms == 0 {
                anyhow::bail!("SEEDER_RECONCILE_OFFSETS_TIMEOUT_MS must be greater than zero");
            }
            let offsets_timeout = Duration::from_millis(config.seeder_reconcile_offsets_timeout_ms);
            let reader = SeedGroupOffsetReader::new(
                config.build_kafka_config(),
                config.kafka_seed_consumer_group.clone(),
                config.seed_events_topic.clone(),
                config.cohort_partition_count,
                offsets_timeout,
            );
            let topic_ends = KafkaTopicOffsets::new(
                producer.clone(),
                config.cohort_reconcile_markers_topic.clone(),
                offsets_timeout,
            );
            // Unique group id: the watcher never commits or joins a group, but a distinct id keeps it
            // out of any real group's coordinator state.
            let watch_group = format!("cohort-seeder-marker-watch-{}", uuid::Uuid::now_v7());
            let watcher = MarkerWatcher::new(
                &config.build_kafka_config(),
                config.cohort_reconcile_markers_topic.clone(),
                &watch_group,
                offsets_timeout,
            )
            .context("creating the marker-watch consumer")?;
            let (directives_tx, directives_rx) =
                tokio::sync::watch::channel(WatchDirectives::default());
            driver = driver.with_observe(
                Arc::new(KafkaCommittedOffsets::new(reader)),
                Arc::new(topic_ends),
                directives_tx,
            );
            Some(MarkerWatchTask::new(
                watcher,
                PgMarkerFlush::new(pool.clone(), config.cohort_reconcile_markers_topic.clone()),
                directives_rx,
                handle,
                persist_interval,
                config.seeder_reconcile_persist_max_batch,
            ))
        }
    };

    Ok(WiredCompletion {
        driver: Some(driver),
        watch_task,
    })
}

fn log_startup(config: &Config) {
    info!(
        service = SERVICE_NAME,
        seed_topic = %config.seed_events_topic,
        partitioner = %config.kafka_producer_partitioner,
        partition_count = config.cohort_partition_count,
        team_allowlist = ?config.team_allowlist,
        run_poll_secs = config.seeder_run_poll_secs,
        max_concurrent_chunks = config.seeder_max_concurrent_chunks,
        max_lookback_days = config.seeder_max_lookback_days,
        bands_per_day = config.seeder_bands_per_day,
        tiles_per_second = config.seeder_tiles_per_sec,
        max_inflight_tiles = config.seeder_max_inflight_tiles,
        person_seeds_enabled = config.seeder_person_seeds_enabled,
        person_seeds_per_sec = config.seeder_person_seeds_per_sec,
        persons_per_chunk = config.seeder_persons_per_chunk,
        person_max_concurrent_chunks = config.seeder_person_max_concurrent_chunks,
        person_emit_nonmatchers = config.seeder_person_emit_nonmatchers,
        reconcile_auto_dispatch_enabled = config.seeder_reconcile_auto_dispatch_enabled,
        confirm_register_backfilled = config.seeder_confirm_register_backfilled,
        reconcile_max_concurrent_dispatches = config.seeder_reconcile_max_concurrent_dispatches,
        reconcile_markers_topic = %config.cohort_reconcile_markers_topic,
        reconcile_observer_enabled = config.seeder_reconcile_observer_enabled,
        seed_consumer_group = %config.kafka_seed_consumer_group,
        reconcile_offsets_timeout_ms = config.seeder_reconcile_offsets_timeout_ms,
        reconcile_persist_interval_ms = config.seeder_reconcile_persist_interval_ms,
        reconcile_persist_max_batch = config.seeder_reconcile_persist_max_batch,
        "starting cohort-seeder",
    );
}

fn init_tracing() {
    let is_debug = std::env::var("RUST_LOG").is_ok_and(|value| value.contains("debug"));
    let filter = || {
        EnvFilter::builder()
            .with_default_directive(tracing::level_filters::LevelFilter::INFO.into())
            .from_env_lossy()
    };
    let log_layer = if is_debug {
        fmt::layer()
            .with_target(true)
            .with_level(true)
            .with_ansi(true)
            .with_filter(filter())
            .boxed()
    } else {
        fmt::layer()
            .json()
            .flatten_event(true)
            .with_current_span(true)
            .with_filter(filter())
            .boxed()
    };
    tracing_subscriber::registry().with(log_layer).init();
}
