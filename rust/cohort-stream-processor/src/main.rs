use std::path::{Path, PathBuf};
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
    BootReadiness, CascadeRoute, CohortStreamEventsConsumer, EventDispatcher, FollowerConsumer,
    FollowerRoute, MergeRoute, SeedFollowerConsumer, TransferRoute,
};
use cohort_stream_processor::filters::{run_refresh_loop, CatalogHandle};
use cohort_stream_processor::merge::gc::MergeGcSweeper;
use cohort_stream_processor::merge::redrive::RedriveSweeper;
use cohort_stream_processor::observability;
use cohort_stream_processor::observability::disk::SharedDiskUtilization;
use cohort_stream_processor::observability::store_stats::{DiskProbe, StoreStatsSweeper};
use cohort_stream_processor::observability::tokio_monitor::TokioRuntimeMonitor;
use cohort_stream_processor::partitions::{
    run_rebalance_worker, CohortConsumerContext, ConsumerPauser, Follower, FollowerSet,
    InputGroups, LiveWatermarks, OffsetTracker, PartitionPauser, PartitionRouter,
};
use cohort_stream_processor::producer::{
    CascadeSink, KafkaCascadeSink, KafkaMembershipSink, KafkaReconcileMarkerSink,
    KafkaSeedTileSink, KafkaStreamEventSink, KafkaTransferSink, MembershipSink, NoopCascadeSink,
    NoopReconcileMarkerSink, NoopSeedTileSink, ReconcileMarkerSink, SeedTileSink, StreamEventSink,
    TransferSink,
};
use cohort_stream_processor::store::durability::checkpoint::CHECKPOINT_LOOP_NAME;
use cohort_stream_processor::store::durability::{
    ensure_one_filesystem, open_store, upload_cadence, CheckpointSweeper,
};
use cohort_stream_processor::store::StoreHandle;
use cohort_stream_processor::sweep::{
    run_sweep_loop, run_sweep_loop_delayed, DispatchSweeper, ReconcileDrainSweeper,
};
use cohort_stream_processor::workers::{
    MergeWorkerDeps, PersonSeedDeps, ReconcileBacklog, ReconcileDeps,
};

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

    config.validate_startup()?;

    let lineage = config
        .checkpoint_enabled
        .then(|| config.checkpoint_lineage())
        .transpose()?;

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
    // Followers make their final commit after the consumer's worker drain. So each 45 s window
    // outlasts the consumer's 30 s one, and the 10 s past `FOLLOWER_DRAIN_WAIT` (35 s) is for the
    // commit itself.
    let merge_follower_handle = manager.register(
        "merge-follower",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(45)),
    );
    let transfer_follower_handle = manager.register(
        "transfer-follower",
        ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(45)),
    );
    // Registered only when the gate is on — a dormant deploy must not wait on a component that never
    // starts.
    let cascade_follower_handle = config.cohort_cascade_enabled.then(|| {
        manager.register(
            "cascade-follower",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(45)),
        )
    });
    let seed_follower_handle = config.cohort_seed_consumer_enabled.then(|| {
        manager.register(
            "seed-follower",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(45)),
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

    let catalog = Arc::new(CatalogHandle::with_allowlist(
        config.team_allowlist.clone(),
        config.cohort_cascade_enabled,
    ));
    let boot_readiness = BootReadiness::new(catalog.clone());

    // Bound before the restore, which can outlast the startup probe. `/_health` answers throughout;
    // `/_ready` reads "boot recovery in progress" until the events consumer goes live.
    let app = observability::health::router(
        SERVICE_NAME,
        readiness,
        boot_readiness.clone(),
        liveness,
        recorder_handle,
    );
    let bind = config.bind_address();
    let listener = TcpListener::bind(&bind)
        .await
        .with_context(|| format!("failed to bind observability server to {bind}"))?;
    info!(address = %bind, "observability server listening");
    let shutdown_signal = metrics_handle.shutdown_signal();
    let health_server = tokio::spawn(async move {
        axum::serve(listener, app)
            .with_graceful_shutdown(shutdown_signal)
            .await
    });

    let pool = get_pool_with_config(&config.database_url, config.pool_config())
        .context("creating posthog_cohort database pool")?;

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

    let groups = Arc::new(InputGroups::new(&config).context("creating input position readers")?);
    if lineage.is_some() {
        ensure_one_filesystem(
            Path::new(&config.checkpoint_local_dir),
            Path::new(&config.store_path),
        )
        .context("checking the checkpoint directory")?;
    }
    let (store, restore) = open_store(&config, lineage, groups.clone())
        .await
        .context("opening RocksDB state store")?;
    let router = PartitionRouter::with_intake_cap(
        config.partition_channel_buffer,
        config.partition_intake_max_events,
        config.seed_lane_cap(),
    );
    let offset_tracker = Arc::new(OffsetTracker::new());

    let kafka_config = config.build_kafka_config();
    let sink: Arc<dyn MembershipSink> = Arc::new(
        KafkaMembershipSink::new(
            &kafka_config,
            config.cohort_membership_changed_topic.clone(),
        )
        .await
        .context("creating membership producer")?,
    );

    // The transfer and marker sinks get the shorter `message.timeout.ms`: both produce inline on a
    // partition worker and both are retried on a cadence — the transfer by a bounded inline loop, the
    // marker by the drain sweeper — so a long per-attempt timeout repeats into a worker hold rather
    // than costing it once. The membership and re-key sinks keep the shared 20 s: membership drops on
    // fail (at-most-once) and the re-key produce rides the events-path offset gate
    // (held-then-redelivered), so neither retries a black-holed produce on a timer.
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
    let seed_tile_sink: Arc<dyn SeedTileSink> = if config.cohort_seed_consumer_enabled {
        Arc::new(
            KafkaSeedTileSink::new(
                &kafka_config,
                config.cohort_stream_seed_events_topic.clone(),
            )
            .await
            .context("creating cohort_stream_seed_events re-key producer")?,
        )
    } else {
        Arc::new(NoopSeedTileSink)
    };
    let marker_sink: Arc<dyn ReconcileMarkerSink> = if config.cohort_seed_reconcile_enabled {
        Arc::new(
            KafkaReconcileMarkerSink::new(
                &config.build_marker_kafka_config(),
                config.cohort_reconcile_markers_topic.clone(),
            )
            .await
            .context("creating cohort_reconcile_markers producer")?,
        )
    } else {
        Arc::new(NoopReconcileMarkerSink)
    };
    let reconcile_backlog = Arc::new(ReconcileBacklog::default());
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
        seed_tile_sink,
        seed_tracker: Arc::new(OffsetTracker::new()),
        // Unconditional (cheap): the event path observes regardless of the seed gate.
        live_watermarks: Arc::new(LiveWatermarks::new()),
        register_transfer_enabled: config.cohort_register_transfer_enabled,
        reconcile: ReconcileDeps {
            enabled: config.cohort_seed_reconcile_enabled,
            scan_page: config.cohort_seed_reconcile_scan_page,
            backlog: reconcile_backlog.clone(),
            marker_sink,
        },
        person_seed: PersonSeedDeps {
            enabled: config.cohort_seed_person_apply_enabled,
            live_margin_ms: config.cohort_seed_person_live_margin_ms,
        },
        seed_budget: config.seed_run_budget(),
    });

    // The checkpoint sweeper keeps the raw `CohortStore` rather than the facade because of its
    // must-not-panic policy (see checkpoint.rs).
    let store_for_checkpoint = store.clone();

    let handle = StoreHandle::new(store, config.offload_config());
    let handle_for_stats = handle.clone();

    let dispatcher = Arc::new(
        EventDispatcher::new(
            router,
            offset_tracker,
            handle,
            catalog.clone(),
            sink,
            merge_deps,
        )
        .with_readiness(boot_readiness.clone()),
    );
    // Set once, before the consume loop and any worker spawn. The fsync-before-commit invariant is
    // always on regardless — the gate only governs restore, not durability.
    if config.durable_restore_enabled {
        dispatcher.enable_durable_restore();
    }
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
    // Shared with the seed consumer's idle probe.
    let stream_consumer = Arc::new(stream_consumer);

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
    // Gated: a gate-off deploy is safe without the seed topic existing at all.
    let seed_follower_consumer: Option<Arc<StreamConsumer>> = if config.cohort_seed_consumer_enabled
    {
        Some(Arc::new(
            config
                .follower_client_config(&config.kafka_seed_consumer_group)
                .create()
                .context("creating cohort_stream_seed_events follower consumer")?,
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
    // A tile must land on the partition owning its person's state slice.
    if let Some(seed_consumer) = &seed_follower_consumer {
        let seed_partitions =
            fetch_partition_count(seed_consumer, &config.cohort_stream_seed_events_topic)?;
        anyhow::ensure!(
            seed_partitions as u32 == config.cohort_partition_count,
            "cohort_stream_seed_events must be co-partitioned with {} at COHORT_PARTITION_COUNT={}: {} has {}",
            config.cohort_stream_events_topic,
            config.cohort_partition_count,
            config.cohort_stream_seed_events_topic,
            seed_partitions,
        );
        // Nothing co-partitions with the marker topic, so only its existence matters. Failing here
        // beats the alternative: a marker produce retrying forever while it holds the seed offset.
        // Nested under the seed consumer on purpose: reconcile jobs are admitted only from seed
        // tiles, so without it no marker can be produced and there is nothing to prove.
        if config.cohort_seed_reconcile_enabled {
            fetch_partition_count(seed_consumer, &config.cohort_reconcile_markers_topic).with_context(
                || {
                    format!(
                        "{} must exist before a processor with COHORT_SEED_RECONCILE_ENABLED starts. \
                         Provision the topic, or set COHORT_SEED_RECONCILE_ENABLED=false to start \
                         without the reconcile path.",
                        config.cohort_reconcile_markers_topic,
                    )
                },
            )?;
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
    if let Some(seed_consumer) = &seed_follower_consumer {
        follower_mirrors.push(Follower::new(
            seed_consumer.clone(),
            config.cohort_stream_seed_events_topic.clone(),
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

    if config.cohort_seed_reconcile_enabled {
        tokio::spawn(run_sweep_loop(
            ReconcileDrainSweeper::new(dispatcher.clone(), reconcile_backlog),
            config.reconcile_tick_interval(),
            "reconcile",
            consumer_handle.shutdown_token(),
        ));
    }

    // Publish store cache/size metrics and the store filesystem's utilization via the sweep
    // machinery, and Tokio runtime metrics via a separate monitor. The disk snapshot feeds the
    // seed consumer's disk-backpressure gate; a sample surviving four sweep ticks unrefreshed
    // means the sweep is wedged, so it expires rather than latching the gate.
    let disk_state = Arc::new(SharedDiskUtilization::new(
        config.stats_publish_interval() * 4,
    ));
    tokio::spawn(run_sweep_loop(
        StoreStatsSweeper::new(
            handle_for_stats,
            DiskProbe::new(PathBuf::from(&config.store_path), disk_state.clone()),
        ),
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

    // Whole-DB checkpoints to the local volume and S3. The loop waits for boot: a capture before the
    // events rewind would record the broker's old offsets of a pending restore.
    if let Some(lineage) = lineage {
        let sweeper = CheckpointSweeper::new(
            store_for_checkpoint,
            dispatcher.clone(),
            groups,
            lineage,
            config.durability_config(),
            upload_cadence(
                config.checkpoint_interval_ms,
                config.checkpoint_s3_upload_interval_ms,
            ),
        );
        let stop = consumer_handle.shutdown_token();
        let interval = config.checkpoint_interval();
        let checkpoint_catalog = catalog.clone();
        let checkpoint_readiness = boot_readiness.clone();
        tokio::spawn(async move {
            tokio::select! {
                biased;
                // Boot never ended, so there are no settled positions to checkpoint.
                _ = stop.cancelled() => {}
                _ = wait_for_boot(&checkpoint_catalog, &checkpoint_readiness) => {
                    run_sweep_loop(sweeper, interval, CHECKPOINT_LOOP_NAME, stop.clone()).await;
                }
            }
        });
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
    spawn_follower_after_boot(
        catalog.clone(),
        boot_readiness.clone(),
        merge_follower,
        merge_follower_handle,
    );

    let transfer_follower = FollowerConsumer::<TransferRoute>::new(
        transfers_follower_consumer,
        config.cohort_merge_state_transfer_topic.clone(),
        dispatcher.clone(),
        transfer_follower_handle.clone(),
        config.recv_batch_size,
        config.recv_batch_timeout(),
        config.offset_commit_interval(),
    );
    spawn_follower_after_boot(
        catalog.clone(),
        boot_readiness.clone(),
        transfer_follower,
        transfer_follower_handle,
    );

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
        spawn_follower_after_boot(
            catalog.clone(),
            boot_readiness.clone(),
            cascade_follower,
            cascade_handle,
        );
    }

    if let (Some(seed_consumer), Some(seed_handle)) = (seed_follower_consumer, seed_follower_handle)
    {
        let seed_topic = config.cohort_stream_seed_events_topic.clone();
        let pauser: Arc<dyn PartitionPauser> = Arc::new(ConsumerPauser::new(
            seed_consumer.clone(),
            seed_topic.clone(),
        ));
        let seed_follower = SeedFollowerConsumer::new(
            seed_consumer,
            seed_topic,
            stream_consumer.clone(),
            config.cohort_stream_events_topic.clone(),
            dispatcher.clone(),
            seed_handle.clone(),
            pauser,
            config.recv_batch_size,
            config.recv_batch_timeout(),
            config.offset_commit_interval(),
            config.cohort_seed_fence_margin_ms,
            config.seed_idle_probe_interval(),
            config.seed_pacing_config()?,
            disk_state.clone(),
        );
        let seed_catalog = catalog.clone();
        let seed_readiness = boot_readiness.clone();
        tokio::spawn(async move {
            tokio::select! {
                biased;
                _ = seed_handle.shutdown_recv() => {}
                _ = wait_for_boot(&seed_catalog, &seed_readiness) => seed_follower.process().await,
            }
        });
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
        // A checkpoint restore boot settles before anything folds; `None` when the store reopened
        // or was created, where boot rewinds only what it polled.
        restore,
    );
    tokio::spawn(events_consumer.process());

    health_server
        .await
        .context("observability server task panicked")?
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

/// A follower dispatches only once the catalog has loaded and the events consumer's boot recovery
/// has ended, so no worker runs while boot recovery writes to the store.
async fn wait_for_boot(catalog: &CatalogHandle, readiness: &BootReadiness) {
    catalog.wait_until_loaded().await;
    readiness.wait_until_live().await;
}

fn spawn_follower_after_boot<R: FollowerRoute>(
    catalog: Arc<CatalogHandle>,
    readiness: Arc<BootReadiness>,
    follower: FollowerConsumer<R>,
    handle: Handle,
) {
    tokio::spawn(async move {
        tokio::select! {
            biased;
            _ = handle.shutdown_recv() => {}
            _ = wait_for_boot(&catalog, &readiness) => follower.process().await,
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
        reconcile_markers_topic = %config.cohort_reconcile_markers_topic,
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
        cohort_seed_consumer_enabled = config.cohort_seed_consumer_enabled,
        seed_topic = %config.cohort_stream_seed_events_topic,
        seed_consumer_group = %config.kafka_seed_consumer_group,
        seed_fence_margin_ms = config.cohort_seed_fence_margin_ms,
        cohort_seed_live_lag_pause_ms = config.cohort_seed_live_lag_pause_ms,
        cohort_seed_live_lag_resume_ms = config.cohort_seed_live_lag_resume_ms,
        cohort_seed_disk_pause_pct = config.cohort_seed_disk_pause_pct,
        cohort_seed_disk_resume_pct = config.cohort_seed_disk_resume_pct,
        cohort_seed_reconcile_enabled = config.cohort_seed_reconcile_enabled,
        cohort_seed_reconcile_scan_page = config.cohort_seed_reconcile_scan_page,
        cohort_seed_reconcile_tick_interval_ms = config.cohort_seed_reconcile_tick_interval_ms,
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
