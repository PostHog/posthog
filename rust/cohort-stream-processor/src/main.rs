use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use common_database::get_pool_with_config;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Handle, Manager};
use rdkafka::consumer::{Consumer, ConsumerContext, StreamConsumer};
use tokio::net::TcpListener;
use tokio::sync::mpsc;
use tracing::{info, warn};
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter, Layer};

use cohort_stream_processor::config::Config;
use cohort_stream_processor::consumers::{
    CohortStreamEventsConsumer, EventDispatcher, FollowerConsumer, FollowerRoute, MergeRoute,
    TransferRoute,
};
use cohort_stream_processor::filters::{run_refresh_loop, CatalogHandle};
use cohort_stream_processor::merge::redrive::RedriveSweeper;
use cohort_stream_processor::observability;
use cohort_stream_processor::partitions::{
    run_rebalance_worker, CohortConsumerContext, MergeFollowers, OffsetTracker, PartitionRouter,
};
use cohort_stream_processor::producer::{
    KafkaMembershipSink, KafkaStreamEventSink, KafkaTransferSink, MembershipSink, StreamEventSink,
    TransferSink,
};
use cohort_stream_processor::store::CohortStore;
use cohort_stream_processor::sweep::{run_sweep_loop, DispatchSweeper};
use cohort_stream_processor::workers::MergeWorkerDeps;

common_alloc::used!();

const SERVICE_NAME: &str = "cohort-stream-processor";

fn main() -> Result<()> {
    let config = Config::init_from_env()
        .context("Failed to load configuration from environment variables")?;

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("Failed to build tokio runtime")?;

    runtime.block_on(async_main(config))
}

async fn async_main(config: Config) -> Result<()> {
    init_tracing();
    log_startup(&config);

    // The generous shutdown timeout leaves room for the final RocksDB checkpoint flush.
    let mut manager = Manager::builder(SERVICE_NAME)
        .with_global_shutdown_timeout(Duration::from_secs(90))
        .build();

    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));
    // Monitored for clean shutdown, not liveness: a refresh outage must not kill the service, which
    // keeps serving the last good snapshot.
    let catalog_handle_lifecycle = manager.register(
        "filter-catalog",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    // The consumer owns the liveness deadline: a wedged consume loop or sustained broker outage
    // trips coordinated shutdown. Its graceful window covers draining worker channels and the
    // final commit.
    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(30))
            .with_liveness_deadline(Duration::from_secs(60))
            .with_stall_threshold(3),
    );
    // The merge-protocol followers stop on the same coordinated signal; their graceful window
    // covers the final sync commit. Deliberately no liveness deadline — a follower's health signal
    // is consumer-group lag on its merge group, and the events consumer above already owns
    // process-level liveness.
    let merge_follower_handle = manager.register(
        "merge-follower",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );
    let transfer_follower_handle = manager.register(
        "transfer-follower",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let recorder_handle = if config.export_prometheus {
        Some(observability::metrics::install_recorder())
    } else {
        None
    };

    // Build all infrastructure before starting the monitor: a failure here returns before the
    // monitor thread runs, so the dropped handles are harmless no-ops and the process exits non-zero.
    let pool = get_pool_with_config(&config.database_url, config.pool_config())
        .context("creating posthog_cohort database pool")?;

    let catalog = Arc::new(CatalogHandle::with_allowlist(config.team_allowlist.clone()));
    match catalog.refresh(&pool).await {
        Ok(stats) => info!(
            teams = stats.teams,
            unique_conditions = stats.unique_conditions,
            "initial filter catalog loaded",
        ),
        Err(err) => warn!(
            error = %err,
            "initial filter catalog load failed; catalog is empty until the refresh task succeeds",
        ),
    }

    // The `StreamConsumer` subscribes here but does not fetch until `process()` polls it after the
    // monitor starts, so building it now keeps the fail-fast discipline above. `wipe_store_on_start`
    // makes `open` destroy any on-disk state first, so a restart never serves a previous owner's
    // per-partition state.
    let store = CohortStore::open(&config.store_config()).context("opening RocksDB state store")?;
    let router = PartitionRouter::new(config.partition_channel_buffer);
    let offset_tracker = Arc::new(OffsetTracker::new());

    // `KafkaMembershipSink::new` pings broker metadata, so a bad Kafka config fails fast here.
    let kafka_config = config.build_kafka_config();
    let sink: Arc<dyn MembershipSink> = Arc::new(
        KafkaMembershipSink::new(
            &kafka_config,
            config.cohort_membership_changed_topic.clone(),
        )
        .await
        .context("creating shadow producer")?,
    );

    // Merge-protocol sinks + trackers (TDD §4.5.1). The trackers are shared three ways: workers
    // mark processed offsets, the dispatcher marks dispatch ceilings and forgets revoked
    // partitions, and the follower consumers commit from them through the dispatcher (D7).
    let transfer_sink: Arc<dyn TransferSink> = Arc::new(
        KafkaTransferSink::new(
            &kafka_config,
            config.cohort_merge_state_transfer_topic.clone(),
        )
        .await
        .context("creating merge state transfer producer")?,
    );
    let stream_event_sink: Arc<dyn StreamEventSink> = Arc::new(
        KafkaStreamEventSink::new(&kafka_config, config.cohort_stream_events_topic.clone())
            .await
            .context("creating straggler re-key producer")?,
    );
    let merge_deps = Arc::new(MergeWorkerDeps {
        transfer_sink,
        stream_event_sink,
        merge_tracker: Arc::new(OffsetTracker::new()),
        transfer_tracker: Arc::new(OffsetTracker::new()),
        retry: config.transfer_retry_policy(),
    });

    // The dispatcher owns the shared router/workers/ownership state; the consume loop dispatches
    // through it while the rebalance context (and its async worker) drive the partition lifecycle
    // over the *same* state. It shares the catalog snapshot the refresh loop swaps, and hands the
    // sink + offset tracker + merge deps to each per-partition worker.
    let dispatcher = Arc::new(EventDispatcher::new(
        router,
        offset_tracker,
        store,
        catalog.clone(),
        sink,
        merge_deps,
    ));

    // The consumer carries the rebalance context, so `create_with_context` (which pings broker
    // metadata) still fails fast here on a bad Kafka config.
    let (context, rebalance_rx) = CohortConsumerContext::new(dispatcher.clone());
    let stream_consumer: StreamConsumer<CohortConsumerContext> = config
        .consumer_client_config()
        .create_with_context(context)
        .context("creating cohort_stream_events consumer")?;
    stream_consumer
        .subscribe(&[config.cohort_stream_events_topic.as_str()])
        .context("subscribing to cohort_stream_events")?;

    // The merge-protocol followers never `subscribe()` — the events group's rebalance mirrors
    // ownership onto them (D5). Client creation alone is lazy, so the co-partitioning check below
    // doubles as their fail-fast broker ping.
    let merges_follower_consumer: Arc<StreamConsumer> = Arc::new(
        config
            .follower_client_config(&config.kafka_merge_consumer_group)
            .create()
            .context("creating person_merge_events follower consumer")?,
    );
    let transfers_follower_consumer: Arc<StreamConsumer> = Arc::new(
        config
            .follower_client_config(&config.kafka_merge_apply_consumer_group)
            .create()
            .context("creating cohort_merge_state_transfer follower consumer")?,
    );

    // D14: the merge protocol's partition arithmetic — the keyed transfer produce, `partition_of`'s
    // same-vs-cross-partition split, assignment mirroring by partition number — assumes all three
    // topics are co-partitioned. A mismatch is silently wrong forever (drains land on workers that
    // don't own P_old), so fail fast on live broker metadata instead.
    let events_partitions =
        fetch_partition_count(&stream_consumer, &config.cohort_stream_events_topic)?;
    let merge_partitions =
        fetch_partition_count(&merges_follower_consumer, &config.person_merge_events_topic)?;
    let transfer_partitions = fetch_partition_count(
        &transfers_follower_consumer,
        &config.cohort_merge_state_transfer_topic,
    )?;
    anyhow::ensure!(
        merge_partitions == events_partitions && transfer_partitions == events_partitions,
        "merge topics must be co-partitioned with {} ({} partitions): {} has {}, {} has {}",
        config.cohort_stream_events_topic,
        events_partitions,
        config.person_merge_events_topic,
        merge_partitions,
        config.cohort_merge_state_transfer_topic,
        transfer_partitions,
    );

    let followers = Arc::new(MergeFollowers::new(
        merges_follower_consumer.clone(),
        config.person_merge_events_topic.clone(),
        transfers_follower_consumer.clone(),
        config.cohort_merge_state_transfer_topic.clone(),
    ));

    // Currently unused; wired through to the rebalance worker and the consume loop.
    let (consumer_command_tx, consumer_command_rx) = mpsc::unbounded_channel();

    let guard = manager.monitor_background();

    let refresh_catalog = catalog.clone();
    let refresh_pool = pool.clone();
    let refresh_interval = config.filter_catalog_refresh_interval();
    let refresh_jitter = config.filter_catalog_refresh_jitter();
    tokio::spawn(async move {
        run_refresh_loop(
            refresh_catalog,
            refresh_pool,
            refresh_interval,
            refresh_jitter,
            catalog_handle_lifecycle,
        )
        .await;
    });

    // The async half of rebalancing: mirror every (un)assignment onto the merge followers and
    // reclaim revoked partitions off the poll thread, exiting on the consumer's shutdown token.
    // Held so teardown can await it after the consume loop stops.
    let rebalance_worker = tokio::spawn(run_rebalance_worker(
        rebalance_rx,
        dispatcher.clone(),
        followers,
        consumer_command_tx,
        consumer_handle.shutdown_token(),
    ));

    // The time-driven eviction sweep: each tick routes a `Sweep` to every owned partition's worker,
    // which drains its own queue and emits any `left`. Shares the consumer's shutdown token so it
    // stops on coordinated shutdown. Grab the token + dispatcher clone before the consumer takes
    // ownership of both (mirrors the rebalance-worker spawn above).
    tokio::spawn(run_sweep_loop(
        DispatchSweeper::new(dispatcher.clone(), config.sweep_safety_margin_ms as i64),
        config.sweep_interval(),
        consumer_handle.shutdown_token(),
    ));

    // The pending-transfer redrive (TDD §4.5.1, D3): each tick routes a redrive to every owned
    // partition's worker, which re-produces any `cf_pending_transfers` entries stranded by
    // inline-retry exhaustion and finally lets the merge group's commit advance past them. Same
    // timer machinery and shutdown token as the eviction sweep above.
    tokio::spawn(run_sweep_loop(
        RedriveSweeper::new(dispatcher.clone()),
        config.merge_redrive_interval(),
        consumer_handle.shutdown_token(),
    ));

    // The two follower consume loops, gated on the first successful catalog load (D9): their
    // partitions are already mirrored, so until the gate opens librdkafka prefetches the assigned
    // partitions into its client-side buffer (bounded by `queued.max.messages.kbytes`) with nothing
    // `recv()`ing it — harmless at merge-topic rates, and visible as lag on the two merge groups.
    let merge_follower = FollowerConsumer::<MergeRoute>::new(
        merges_follower_consumer,
        config.person_merge_events_topic.clone(),
        dispatcher.clone(),
        merge_follower_handle.clone(),
        config.recv_batch_size,
        config.recv_batch_timeout(),
        config.offset_commit_interval(),
    );
    spawn_follower_after_catalog_load(catalog.clone(), merge_follower, merge_follower_handle);

    let transfer_follower = FollowerConsumer::<TransferRoute>::new(
        transfers_follower_consumer,
        config.cohort_merge_state_transfer_topic.clone(),
        dispatcher.clone(),
        transfer_follower_handle.clone(),
        config.recv_batch_size,
        config.recv_batch_timeout(),
        config.offset_commit_interval(),
    );
    spawn_follower_after_catalog_load(catalog.clone(), transfer_follower, transfer_follower_handle);

    let events_consumer = CohortStreamEventsConsumer::new(
        stream_consumer,
        config.cohort_stream_events_topic.clone(),
        dispatcher,
        consumer_handle,
        config.recv_batch_size,
        config.recv_batch_timeout(),
        config.offset_commit_interval(),
        consumer_command_rx,
    );
    tokio::spawn(events_consumer.process());

    let app = observability::health::router(SERVICE_NAME, readiness, liveness, recorder_handle);
    let bind = config.bind_address();
    info!(address = %bind, "observability server starting");

    let listener = TcpListener::bind(&bind)
        .await
        .with_context(|| format!("failed to bind observability server to {bind}"))?;
    axum::serve(listener, app)
        .with_graceful_shutdown(metrics_handle.shutdown_signal())
        .await
        .context("observability server error")?;
    metrics_handle.work_completed();

    guard.wait().await?;

    // The consume loop has stopped and drained its workers; wait for the rebalance worker to finish
    // any in-flight revoke cleanup before exiting.
    if let Err(err) = rebalance_worker.await {
        warn!(error = %err, "rebalance worker task did not exit cleanly");
    }

    info!(service = SERVICE_NAME, "service stopped");
    Ok(())
}

/// One topic's partition count from live broker metadata — D14's input. Fails on a missing topic,
/// a broker-reported topic error, or an empty partition set.
fn fetch_partition_count<C: ConsumerContext>(
    consumer: &StreamConsumer<C>,
    topic: &str,
) -> Result<usize> {
    let metadata = consumer
        .fetch_metadata(Some(topic), Duration::from_secs(10))
        .with_context(|| format!("fetching broker metadata for {topic}"))?;
    let topic_metadata = metadata
        .topics()
        .iter()
        .find(|candidate| candidate.name() == topic)
        .with_context(|| format!("topic {topic} missing from broker metadata"))?;
    if let Some(err) = topic_metadata.error() {
        anyhow::bail!("broker reports an error for topic {topic}: {err:?}");
    }
    let count = topic_metadata.partitions().len();
    anyhow::ensure!(
        count > 0,
        "topic {topic} has no partitions in broker metadata"
    );
    Ok(count)
}

/// Spawn a merge-protocol follower's consume loop, gated on the first successful filter-catalog
/// load (D9): before it, every team reads as absent, and a drain/apply against that false-empty
/// view would silently drop a real team's leaves as drift. Shutdown can preempt the gate — the
/// task then drops the never-started follower, and the handle's drop-during-shutdown reports
/// completion to the manager (nothing was consumed, so there is nothing to commit).
fn spawn_follower_after_catalog_load<R: FollowerRoute>(
    catalog: Arc<CatalogHandle>,
    follower: FollowerConsumer<R>,
    handle: Handle,
) {
    tokio::spawn(async move {
        tokio::select! {
            biased;
            _ = handle.shutdown_recv() => {}
            _ = catalog.wait_until_loaded() => follower.process().await,
        }
    });
}

/// Log a redacted startup summary. Deliberately omits `database_url` (carries credentials).
fn log_startup(config: &Config) {
    info!(
        service = SERVICE_NAME,
        bind_address = %config.bind_address(),
        kafka_hosts = %config.kafka_hosts,
        input_topic = %config.cohort_stream_events_topic,
        output_topic = %config.cohort_membership_changed_topic,
        consumer_group = %config.kafka_consumer_group,
        offset_reset = %config.kafka_consumer_offset_reset,
        merge_topic = %config.person_merge_events_topic,
        transfer_topic = %config.cohort_merge_state_transfer_topic,
        merge_consumer_group = %config.kafka_merge_consumer_group,
        merge_apply_consumer_group = %config.kafka_merge_apply_consumer_group,
        session_timeout_ms = config.kafka_session_timeout_ms,
        pod_identity = config.pod_identity().unwrap_or("<dynamic>"),
        recv_batch_size = config.recv_batch_size,
        partition_channel_buffer = config.partition_channel_buffer,
        store_path = %config.store_path,
        wipe_store_on_start = config.wipe_store_on_start,
        filter_catalog_refresh_secs = config.filter_catalog_refresh_secs,
        filter_catalog_refresh_jitter_secs = config.filter_catalog_refresh_jitter_secs,
        team_allowlist = ?config.team_allowlist,
        "starting cohort-stream-processor",
    );
}

/// JSON structured logging in production; human-readable when `RUST_LOG` requests debug.
/// Mirrors `rust/ingestion-consumer/src/main.rs`.
fn init_tracing() {
    let is_debug = std::env::var("RUST_LOG")
        .map(|v| v.contains("debug"))
        .unwrap_or(false);

    let log_layer = if is_debug {
        fmt::layer()
            .with_target(true)
            .with_level(true)
            .with_ansi(true)
            .with_filter(
                EnvFilter::builder()
                    .with_default_directive(tracing::level_filters::LevelFilter::INFO.into())
                    .from_env_lossy(),
            )
            .boxed()
    } else {
        fmt::layer()
            .json()
            .flatten_event(true)
            .with_current_span(true)
            .with_filter(
                EnvFilter::builder()
                    .with_default_directive(tracing::level_filters::LevelFilter::INFO.into())
                    .from_env_lossy(),
            )
            .boxed()
    };

    tracing_subscriber::registry().with(log_layer).init();
}
