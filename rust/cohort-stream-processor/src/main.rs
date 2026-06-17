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
    CascadeRoute, CohortStreamEventsConsumer, EventDispatcher, FollowerConsumer, FollowerRoute,
    MergeRoute, TransferRoute,
};
use cohort_stream_processor::filters::{run_refresh_loop, CatalogHandle};
use cohort_stream_processor::merge::gc::MergeGcSweeper;
use cohort_stream_processor::merge::redrive::RedriveSweeper;
use cohort_stream_processor::observability;
use cohort_stream_processor::partitions::{
    run_rebalance_worker, CohortConsumerContext, Follower, FollowerSet, OffsetTracker,
    PartitionRouter,
};
use cohort_stream_processor::producer::{
    CascadeSink, KafkaCascadeSink, KafkaMembershipSink, KafkaStreamEventSink, KafkaTransferSink,
    MembershipSink, NoopCascadeSink, StreamEventSink, TransferSink,
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

    let mut manager = Manager::builder(SERVICE_NAME)
        .with_global_shutdown_timeout(Duration::from_secs(90))
        .build();

    let metrics_handle =
        manager.register("metrics", ComponentOptions::new().is_observability(true));
    let catalog_handle_lifecycle = manager.register(
        "filter-catalog",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(30))
            .with_liveness_deadline(Duration::from_secs(60))
            .with_stall_threshold(3),
    );
    let merge_follower_handle = manager.register(
        "merge-follower",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );
    let transfer_follower_handle = manager.register(
        "transfer-follower",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
    );
    // Registered only when the gate is on — a dormant deploy must not wait on a component that never
    // starts.
    let cascade_follower_handle = config.cohort_cascade_enabled.then(|| {
        manager.register(
            "cascade-follower",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(30)),
        )
    });

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let recorder_handle = if config.export_prometheus {
        Some(observability::metrics::install_recorder())
    } else {
        None
    };

    let pool = get_pool_with_config(&config.database_url, config.pool_config())
        .context("creating posthog_cohort database pool")?;

    let catalog = Arc::new(CatalogHandle::with_allowlist(
        config.team_allowlist.clone(),
        config.cohort_cascade_enabled,
    ));
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

    let store = CohortStore::open(&config.store_config()).context("opening RocksDB state store")?;
    let router = PartitionRouter::new(config.partition_channel_buffer);
    let offset_tracker = Arc::new(OffsetTracker::new());

    let kafka_config = config.build_kafka_config();
    let sink: Arc<dyn MembershipSink> = Arc::new(
        KafkaMembershipSink::new(
            &kafka_config,
            config.cohort_membership_changed_topic.clone(),
        )
        .await
        .context("creating shadow producer")?,
    );

    // Only the transfer sink gets the shorter `message.timeout.ms`: its produce runs inline on a
    // partition worker under a bounded retry loop, so a long per-attempt timeout would multiply into
    // a worker hold past the 30 s graceful-shutdown window. The membership and re-key sinks keep the
    // shared 20 s — membership drops on fail (at-most-once) and the re-key produce rides the
    // events-path offset gate (held-then-redelivered), so neither blocks a worker for the full timeout.
    let transfer_kafka_config = config.build_transfer_kafka_config();
    let transfer_sink: Arc<dyn TransferSink> = Arc::new(
        KafkaTransferSink::new(
            &transfer_kafka_config,
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

    // Gate off: a no-op sink needs no producer or topic. Gate on: a real keyed producer.
    let cascade_sink: Arc<dyn CascadeSink> = if config.cohort_cascade_enabled {
        Arc::new(
            KafkaCascadeSink::new(&kafka_config, config.cohort_cascade_events_topic.clone())
                .await
                .context("creating cohort_cascade_events producer")?,
        )
    } else {
        Arc::new(NoopCascadeSink)
    };
    let merge_deps = Arc::new(MergeWorkerDeps {
        transfer_sink,
        stream_event_sink,
        merge_tracker: Arc::new(OffsetTracker::new()),
        transfer_tracker: Arc::new(OffsetTracker::new()),
        retry: config.transfer_retry_policy(),
        gc_scan_limit: config.merge_gc_scan_limit,
        cascade_sink,
        cascade_tracker: Arc::new(OffsetTracker::new()),
        cascade: config.cascade_config(),
    });

    let dispatcher = Arc::new(EventDispatcher::new(
        router,
        offset_tracker,
        store,
        catalog.clone(),
        sink,
        merge_deps,
    ));

    let (context, rebalance_rx) = CohortConsumerContext::new(dispatcher.clone());
    let stream_consumer: StreamConsumer<CohortConsumerContext> = config
        .consumer_client_config()
        .create_with_context(context)
        .context("creating cohort_stream_events consumer")?;
    stream_consumer
        .subscribe(&[config.cohort_stream_events_topic.as_str()])
        .context("subscribing to cohort_stream_events")?;

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
    // Built only when the gate is on, so a dormant deploy needs no `cohort_cascade_events` topic.
    let cascade_follower_consumer: Option<Arc<StreamConsumer>> = if config.cohort_cascade_enabled {
        Some(Arc::new(
            config
                .follower_client_config(&config.kafka_cascade_consumer_group)
                .create()
                .context("creating cohort_cascade_events follower consumer")?,
        ))
    } else {
        None
    };

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
    // A cascade for (team, person) must land on the partition owning that person's `cf_stage2` — the
    // same partition number as the events topic — so refuse to start co-partitioned at a different
    // count. Skipped when the gate is off (no cascade topic required).
    if let Some(cascade_consumer) = &cascade_follower_consumer {
        let cascade_partitions =
            fetch_partition_count(cascade_consumer, &config.cohort_cascade_events_topic)?;
        anyhow::ensure!(
            cascade_partitions == events_partitions,
            "cohort_cascade_events must be co-partitioned with {} ({} partitions): {} has {}",
            config.cohort_stream_events_topic,
            events_partitions,
            config.cohort_cascade_events_topic,
            cascade_partitions,
        );
    }

    let mut follower_mirrors = vec![
        Follower::new(
            merges_follower_consumer.clone(),
            config.person_merge_events_topic.clone(),
        ),
        Follower::new(
            transfers_follower_consumer.clone(),
            config.cohort_merge_state_transfer_topic.clone(),
        ),
    ];
    if let Some(cascade_consumer) = &cascade_follower_consumer {
        follower_mirrors.push(Follower::new(
            cascade_consumer.clone(),
            config.cohort_cascade_events_topic.clone(),
        ));
    }
    let followers = Arc::new(FollowerSet::new(follower_mirrors));

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

    let rebalance_worker = tokio::spawn(run_rebalance_worker(
        rebalance_rx,
        dispatcher.clone(),
        followers,
        consumer_command_tx,
        consumer_handle.shutdown_token(),
    ));

    tokio::spawn(run_sweep_loop(
        DispatchSweeper::new(dispatcher.clone(), config.sweep_safety_margin_ms as i64),
        config.sweep_interval(),
        "eviction",
        consumer_handle.shutdown_token(),
    ));

    tokio::spawn(run_sweep_loop(
        RedriveSweeper::new(dispatcher.clone()),
        config.merge_redrive_interval(),
        "redrive",
        consumer_handle.shutdown_token(),
    ));

    tokio::spawn(run_sweep_loop(
        MergeGcSweeper::new(
            dispatcher.clone(),
            config.merge_marker_retention_ms as i64,
            config.merge_tombstone_retention_ms as i64,
        ),
        config.merge_gc_interval(),
        "merge_gc",
        consumer_handle.shutdown_token(),
    ));

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

    // Spawned only when the gate is on (consumer and handle are `Some` together).
    if let (Some(cascade_consumer), Some(cascade_handle)) =
        (cascade_follower_consumer, cascade_follower_handle)
    {
        let cascade_follower = FollowerConsumer::<CascadeRoute>::new(
            cascade_consumer,
            config.cohort_cascade_events_topic.clone(),
            dispatcher.clone(),
            cascade_handle.clone(),
            config.recv_batch_size,
            config.recv_batch_timeout(),
            config.offset_commit_interval(),
        );
        spawn_follower_after_catalog_load(catalog.clone(), cascade_follower, cascade_handle);
    }

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

    if let Err(err) = rebalance_worker.await {
        warn!(error = %err, "rebalance worker task did not exit cleanly");
    }

    info!(service = SERVICE_NAME, "service stopped");
    Ok(())
}

/// Fetch one topic's partition count from live broker metadata.
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

/// Spawn a follower's consume loop after the first successful filter-catalog load.
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
        cohort_cascade_enabled = config.cohort_cascade_enabled,
        cascade_topic = %config.cohort_cascade_events_topic,
        cascade_consumer_group = %config.kafka_cascade_consumer_group,
        "starting cohort-stream-processor",
    );
}

/// JSON structured logging in production; human-readable when `RUST_LOG` requests debug.
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
