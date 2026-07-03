use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use common_database::get_pool_with_config;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Handle, Manager};
use rdkafka::consumer::{CommitMode, Consumer, ConsumerContext, StreamConsumer};
use rdkafka::{Offset, TopicPartitionList};
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
use cohort_stream_processor::observability::store_stats::StoreStatsSweeper;
use cohort_stream_processor::observability::tokio_monitor::TokioRuntimeMonitor;
use cohort_stream_processor::partitions::{
    run_rebalance_worker, CohortConsumerContext, Follower, FollowerSet, OffsetTracker,
    PartitionRouter,
};
use cohort_stream_processor::producer::{
    CascadeSink, KafkaCascadeSink, KafkaMembershipSink, KafkaStreamEventSink, KafkaTransferSink,
    MembershipSink, NoopCascadeSink, StreamEventSink, TransferSink,
};
use cohort_stream_processor::store::durability::{
    run_boot_restore, upload_cadence, CheckpointExporter, CheckpointSweeper, OffsetManifest,
    S3Uploader, TrackedTopic, CHECKPOINT_LOOP_NAME,
};
use cohort_stream_processor::store::{CohortStore, StoreHandle};
use cohort_stream_processor::sweep::{run_sweep_loop, run_sweep_loop_delayed, DispatchSweeper};
use cohort_stream_processor::workers::MergeWorkerDeps;

common_alloc::used!();

const SERVICE_NAME: &str = "cohort-stream-processor";

fn main() -> Result<()> {
    let config = Config::init_from_env()
        .context("Failed to load configuration from environment variables")?;

    let mut runtime_builder = tokio::runtime::Builder::new_multi_thread();
    runtime_builder.enable_all();
    if config.tokio_worker_threads > 0 {
        runtime_builder.worker_threads(config.tokio_worker_threads);
    }
    let runtime = runtime_builder
        .build()
        .context("Failed to build tokio runtime")?;

    runtime.block_on(async_main(config))
}

async fn async_main(config: Config) -> Result<()> {
    init_tracing();
    log_startup(&config);

    config.validate_durability_startup()?;

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
    // Short graceful window: it holds no state and its next tick is disposable.
    let tokio_monitor_handle = manager.register(
        "tokio-runtime-monitor",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(2)),
    );

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

    // Decide where the live store comes from and, on the disaster paths, materialize it at
    // `store_path` before the store is opened and before the checkpoint sweep loop is spawned (so no
    // TOCTOU with the sweeper's prune). A restored DB dropped at `store_path` makes the
    // `effective_wipe_on_start` logic below see `db_dir_exists == true` and keep it.
    let restore = run_boot_restore(&config, &PathBuf::from(&config.store_path)).await;
    info!(restore_source = ?restore.source, "boot restore complete");

    let store_config = config.store_config();
    info!(
        durable_restore_enabled = config.durable_restore_enabled,
        wipe_store_on_start = config.wipe_store_on_start,
        effective_wipe = store_config.wipe_on_start,
        store_path = %config.store_path,
        mode = if store_config.wipe_on_start { "wipe+replay" } else { "reopen-live" },
        "opening RocksDB state store",
    );
    let store = CohortStore::open(&store_config).context("opening RocksDB state store")?;
    let router = PartitionRouter::with_intake_cap(
        config.partition_channel_buffer,
        config.partition_intake_max_events,
    );
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
        stage2_orphan_gc_enabled: config.stage2_orphan_gc_enabled,
        cascade_sink,
        cascade_tracker: Arc::new(OffsetTracker::new()),
        cascade: config.cascade_config(),
        partition_count: config.cohort_partition_count,
    });

    // Cheap `Arc` clones taken before the originals move into the dispatcher: the checkpoint sweeper
    // needs its own raw-store handle and each per-topic tracker to capture the offset manifest.
    // Captured unconditionally to satisfy the borrow checker; consumed only when `checkpoint_enabled`.
    // The checkpoint sweeper keeps the raw `CohortStore` (it runs its own `spawn_blocking` under a
    // must-not-panic policy that conflicts with the facade's `resume_unwind` — see checkpoint.rs).
    let store_for_checkpoint = store.clone();
    let events_tracker_for_checkpoint = offset_tracker.clone();
    let merge_tracker_for_checkpoint = merge_deps.merge_tracker.clone();
    let transfer_tracker_for_checkpoint = merge_deps.transfer_tracker.clone();
    let cascade_tracker_for_checkpoint = merge_deps.cascade_tracker.clone();

    // The async facade over the store: the only store surface the dispatcher, its workers, and the
    // stats sweeper see. Cheap to clone (the inner store is `Arc`-backed).
    let handle = StoreHandle::new(store, config.offload_config());
    let handle_for_stats = handle.clone();

    let dispatcher = Arc::new(EventDispatcher::new(
        router,
        offset_tracker,
        handle,
        catalog.clone(),
        sink,
        merge_deps,
    ));
    // Set once, before the consume loop and any worker spawn. The fsync-before-commit invariant is
    // always on regardless — the gate only governs restore, not durability.
    if config.durable_restore_enabled {
        dispatcher.enable_durable_restore();
    }
    // Person-memo config, likewise set before any worker spawns.
    dispatcher.set_person_memo_config(config.person_memo_config());
    // Event-name fan-out gating, likewise set before any worker spawns.
    dispatcher.set_event_name_gating(config.event_name_gating());

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
    // The merge math hashes `(team, person)` against `config.cohort_partition_count`, so the topics
    // must not only be co-partitioned with each other but partitioned at exactly that count — a
    // deploy/lane at N != the configured count silently misroutes every merge.
    anyhow::ensure!(
        events_partitions as u32 == config.cohort_partition_count,
        "{} is partitioned at {} but COHORT_PARTITION_COUNT is {}: the merge partition arithmetic \
         would misroute. Re-partition the topic to {} or set COHORT_PARTITION_COUNT to {}.",
        config.cohort_stream_events_topic,
        events_partitions,
        config.cohort_partition_count,
        config.cohort_partition_count,
        events_partitions,
    );
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
            cascade_partitions as u32 == config.cohort_partition_count,
            "cohort_cascade_events must be co-partitioned with {} at COHORT_PARTITION_COUNT={}: {} has {}",
            config.cohort_stream_events_topic,
            config.cohort_partition_count,
            config.cohort_cascade_events_topic,
            cascade_partitions,
        );
    }

    if let Some(manifest) = restore.manifest.as_ref() {
        commit_follower_offsets_from_manifest(
            &merges_follower_consumer,
            &config.person_merge_events_topic,
            manifest,
        );
        commit_follower_offsets_from_manifest(
            &transfers_follower_consumer,
            &config.cohort_merge_state_transfer_topic,
            manifest,
        );
        if let Some(cascade_consumer) = &cascade_follower_consumer {
            commit_follower_offsets_from_manifest(
                cascade_consumer,
                &config.cohort_cascade_events_topic,
                manifest,
            );
        }
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

    // Hold the first eviction pass past the boot window so its read burst doesn't stack on backlog
    // catch-up; only the eviction sweep is delayed.
    tokio::spawn(run_sweep_loop_delayed(
        config.first_eviction_sweep_delay(),
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

    // Publish store cache/size metrics via the sweep machinery, and Tokio runtime metrics via a
    // separate monitor.
    tokio::spawn(run_sweep_loop(
        StoreStatsSweeper::new(handle_for_stats),
        config.stats_publish_interval(),
        "store_stats",
        consumer_handle.shutdown_token(),
    ));
    tokio::spawn(
        TokioRuntimeMonitor::new(
            &tokio::runtime::Handle::current(),
            config.stats_publish_interval(),
        )
        .start_monitoring(tokio_monitor_handle),
    );

    // Whole-DB checkpoint → PVC + incremental S3 sweep loop. Spawned only when the master gate is on,
    // so a default deploy starts no checkpoint task. The cascade tracker is included only when cascade
    // is on; otherwise it is idle and would contribute an empty manifest entry.
    if config.checkpoint_enabled {
        let uploader = S3Uploader::new(config.durability_config())
            .await
            .context("building checkpoint S3 uploader")?;
        let exporter = CheckpointExporter::new(Box::new(uploader));
        let upload_every_n = upload_cadence(
            config.checkpoint_interval_ms,
            config.checkpoint_s3_upload_interval_ms,
        );
        let mut trackers: Vec<TrackedTopic> = vec![
            (
                config.cohort_stream_events_topic.clone(),
                events_tracker_for_checkpoint,
            ),
            (
                config.person_merge_events_topic.clone(),
                merge_tracker_for_checkpoint,
            ),
            (
                config.cohort_merge_state_transfer_topic.clone(),
                transfer_tracker_for_checkpoint,
            ),
        ];
        if config.cohort_cascade_enabled {
            trackers.push((
                config.cohort_cascade_events_topic.clone(),
                cascade_tracker_for_checkpoint,
            ));
        }
        tokio::spawn(run_sweep_loop(
            CheckpointSweeper::new(
                store_for_checkpoint,
                dispatcher.clone(),
                trackers,
                exporter,
                config.durability_config(),
                PathBuf::from(&config.checkpoint_local_dir),
                upload_every_n,
            ),
            config.checkpoint_interval(),
            CHECKPOINT_LOOP_NAME,
            consumer_handle.shutdown_token(),
        ));
    }

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
        events_partitions,
        consumer_command_rx,
        // Events-topic seek positions for the restore-and-seek step; `None` on the no-seek paths
        // (reopen-live / cold-start).
        restore.manifest,
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

/// Seed a follower consumer group's committed offsets from the restore manifest, so its subsequent
/// `incremental_assign` at [`Offset::Stored`](rdkafka::Offset::Stored) resolves to the restored
/// position rather than the broker's last commit.
///
/// A strict no-op when the manifest has no entry for `topic` or that entry is empty. Commits one
/// `Offset::Offset(next)` per present partition; a commit error is logged and skipped, never fatal, so
/// it cannot delay or break the existing follower assignment. The manifest stores `committed_offset`
/// (next-offset-to-consume), exactly what a Kafka committed offset means, so committing it verbatim is
/// the correct resume point.
fn commit_follower_offsets_from_manifest(
    consumer: &StreamConsumer,
    topic: &str,
    manifest: &OffsetManifest,
) {
    let Some(tpl) = manifest_commit_tpl(topic, manifest) else {
        return;
    };
    match consumer.commit(&tpl, CommitMode::Sync) {
        Ok(()) => info!(
            topic,
            partitions = tpl.count(),
            "seeded follower group offsets from restore manifest",
        ),
        Err(err) => {
            warn!(topic, error = %err, "failed to seed follower offsets from manifest; falling back to broker-stored offsets")
        }
    }
}

/// Returns the `TopicPartitionList` to commit for `topic`, or `None` when the manifest has no entry,
/// the entry is empty, or no partition produced a valid offset. Pure (no I/O) so the behavior is
/// unit-testable without a broker. Each partition is committed at `Offset::Offset(next_offset)` —
/// the next-to-consume value Kafka committed offsets denote — so `Offset::Stored` resolves to it.
fn manifest_commit_tpl(topic: &str, manifest: &OffsetManifest) -> Option<TopicPartitionList> {
    let partitions = manifest.topics.get(topic)?;
    if partitions.is_empty() {
        return None;
    }
    let mut tpl = TopicPartitionList::new();
    for (&partition, &next_offset) in partitions {
        if let Err(err) = tpl.add_partition_offset(topic, partition, Offset::Offset(next_offset)) {
            warn!(topic, partition, next_offset, error = %err, "skipping follower partition in manifest commit");
        }
    }
    (tpl.count() > 0).then_some(tpl)
}

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
        durable_restore_enabled = config.durable_restore_enabled,
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    use cohort_stream_processor::store::durability::MANIFEST_VERSION;

    fn manifest_with(topics: BTreeMap<String, BTreeMap<i32, i64>>) -> OffsetManifest {
        OffsetManifest {
            version: MANIFEST_VERSION,
            captured_at: chrono::Utc::now(),
            topics,
        }
    }

    #[test]
    fn manifest_commit_tpl_is_none_for_an_absent_topic() {
        let manifest = manifest_with(BTreeMap::new());
        assert!(manifest_commit_tpl("person_merge_events", &manifest).is_none());
    }

    #[test]
    fn manifest_commit_tpl_is_none_for_an_empty_topic_entry() {
        let mut topics = BTreeMap::new();
        topics.insert("person_merge_events".to_string(), BTreeMap::new());
        let manifest = manifest_with(topics);
        assert!(
            manifest_commit_tpl("person_merge_events", &manifest).is_none(),
            "an empty follower topic entry must produce no commit (inert in Slice 2)",
        );
    }

    #[test]
    fn manifest_commit_tpl_commits_present_follower_offsets() {
        let mut topics = BTreeMap::new();
        topics.insert(
            "person_merge_events".to_string(),
            BTreeMap::from([(0, 7), (4, 19)]),
        );
        let manifest = manifest_with(topics);

        let tpl = manifest_commit_tpl("person_merge_events", &manifest)
            .expect("present follower offsets produce a commit list");
        assert_eq!(tpl.count(), 2);
        assert_eq!(
            tpl.find_partition("person_merge_events", 0)
                .unwrap()
                .offset(),
            Offset::Offset(7),
        );
        assert_eq!(
            tpl.find_partition("person_merge_events", 4)
                .unwrap()
                .offset(),
            Offset::Offset(19),
        );
    }

    #[test]
    fn manifest_commit_tpl_round_trips_a_multi_topic_live_capture() {
        // Distinct offsets per tracker/partition so a cross-wired capture would surface in the TPL.
        let owned = [3, 7];
        let merge = OffsetTracker::new();
        let transfer = OffsetTracker::new();
        let cascade = OffsetTracker::new();
        for (tracker, base) in [(&merge, 10), (&transfer, 20), (&cascade, 30)] {
            for (partition, bump) in [(3, 1), (7, 2)] {
                let offset = base + bump;
                tracker.mark_dispatched(partition, offset);
                let _ = tracker.mark_processed(partition, offset);
                tracker.mark_committed(partition, offset);
            }
        }

        let manifest = OffsetManifest::capture(
            &owned,
            &[
                ("person_merge_events", &merge),
                ("cohort_merge_state_transfer", &transfer),
                ("cohort_cascade_events", &cascade),
            ],
        );

        for (topic, base) in [
            ("person_merge_events", 10),
            ("cohort_merge_state_transfer", 20),
            ("cohort_cascade_events", 30),
        ] {
            let tpl = manifest_commit_tpl(topic, &manifest)
                .unwrap_or_else(|| panic!("{topic} live capture must produce a commit list"));
            assert_eq!(tpl.count(), 2, "{topic} commits both owned partitions");
            assert_eq!(
                tpl.find_partition(topic, 3).unwrap().offset(),
                Offset::Offset(base + 1),
            );
            assert_eq!(
                tpl.find_partition(topic, 7).unwrap().offset(),
                Offset::Offset(base + 2),
            );
        }

        assert!(
            manifest_commit_tpl("cohort_stream_events", &manifest).is_none(),
            "a topic absent from the live capture must produce no commit",
        );
    }
}
