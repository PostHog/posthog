use std::ops::ControlFlow;
use std::sync::Arc;
use std::time::Duration;

use assignment_coordination::store::{EtcdStore, StoreConfig};
use axum::{routing::get, Router};
use common_database::{get_pool_with_config, PoolConfig};
use common_kafka::config::KafkaConfig;
use common_metrics::{setup_metrics_routes_with_overrides, Matcher};
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use metrics::counter;
use personhog_coordination::changelog::{
    load_changelog_config, watch_changelog_config_loop, CHANGELOG_BOOT_POLL_INTERVAL,
    CHANGELOG_RECONCILE_INTERVAL,
};
use personhog_coordination::follow::{follow_changelog, FollowTarget, Follower, Reporter};
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::types::{ClusterEndpoint, PropertyStoreLayout};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::fmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::EnvFilter;

use clap::Parser;
use personhog_writer::backfill;
use personhog_writer::catch_up::CatchUp;
use personhog_writer::config::{Config, PropertyStorageMode};
use personhog_writer::consumer::ConsumerTask;
use personhog_writer::kafka::{base_client_config, PersonConsumer};
use personhog_writer::pg::PgStore;
use personhog_writer::property_ownership::BackfillTopic;
use personhog_writer::store::PersonWriteStore;
use personhog_writer::writer::WriterTask;
use rdkafka::producer::Producer;

common_alloc::used!();

const STORE_CLOSE_TIMEOUT: Duration = Duration::from_secs(10);
const BACKFILL_PACE_INTERVAL: Duration = Duration::from_secs(5);
const METADATA_TIMEOUT: Duration = Duration::from_secs(10);

/// With no subcommand, runs the writer service.
#[derive(clap::Parser)]
#[command(name = "personhog-writer")]
struct Cli {
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(clap::Subcommand)]
enum Command {
    /// Splits the source table into the key ranges a backfill run scans.
    BackfillPlan(BackfillPlanArgs),
    /// Scans this worker's share of a planned run onto the backfill topic.
    Backfill(BackfillArgs),
    /// Copies missing SSTs into each directory bucket and removes copies Standard no longer has.
    ExpressRepair(ExpressRepairArgs),
}

#[derive(clap::Args)]
struct BackfillPlanArgs {
    #[arg(long)]
    run_id: String,
    #[arg(long, default_value_t = 5_000_000)]
    rows_per_range: i64,
}

#[derive(clap::Args)]
struct BackfillArgs {
    /// The run `backfill-plan` planned; rerunning a finished range does nothing.
    #[arg(long)]
    run_id: String,
    /// This worker's number, such as an Indexed Job's completion index.
    #[arg(long)]
    index: usize,
    #[arg(long)]
    workers: usize,
    #[arg(long, default_value_t = 1000)]
    page_size: i64,
}

#[derive(clap::Args)]
struct ExpressRepairArgs {
    #[arg(long, default_value_t = 3600)]
    orphan_min_age_secs: u64,
    #[arg(long, default_value_t = 4)]
    concurrency: usize,
    #[arg(long)]
    dry_run: bool,
}

fn init_tracing() {
    let log_layer = fmt::layer()
        .with_target(true)
        .with_thread_ids(true)
        .with_level(true);

    tracing_subscriber::registry()
        .with(log_layer)
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    init_tracing();
    match Cli::parse().command {
        Some(Command::BackfillPlan(args)) => return backfill_plan(args).await,
        Some(Command::Backfill(args)) => return backfill(args).await,
        Some(Command::ExpressRepair(args)) => return express_repair(args).await,
        None => {}
    }
    let config = Config::init_from_env().expect("Invalid configuration");
    let mode = config.property_storage_mode;

    tracing::info!(property_storage_mode = ?mode, "Starting personhog-writer");
    tracing::info!("Consumer group: {}", config.kafka_consumer_group);
    tracing::info!("Flush interval: {}ms", config.flush_interval_ms);
    tracing::info!("Flush buffer size: {}", config.flush_buffer_size);
    tracing::info!("Buffer capacity: {}", config.buffer_capacity);
    tracing::info!("Writer lanes: {}", config.writer_lanes);
    tracing::info!("Upsert concurrency: {}", config.upsert_concurrency);
    tracing::info!("Metrics port: {}", config.metrics_port);

    let store = EtcdStore::connect_with_member_failover(StoreConfig {
        endpoints: config.etcd_endpoint_list(),
        prefix: config.etcd_prefix.clone(),
    })
    .await?;
    let store = Arc::new(PersonhogStore::new(store));
    // No signal handler is installed until the lifecycle monitor starts,
    // so SIGTERM ends the process during this wait.
    let Some(loaded) = load_changelog_config(
        &store,
        CHANGELOG_BOOT_POLL_INTERVAL,
        &CancellationToken::new(),
    )
    .await?
    else {
        return Ok(());
    };
    let backfilling = mode == PropertyStorageMode::Backfill;
    if backfilling {
        if loaded.writer_group == config.kafka_consumer_group {
            return Err(format!(
                "backfill mode needs its own consumer group, not the writer group {}",
                loaded.writer_group
            )
            .into());
        }
        if config.property_backfill_topic.is_empty() {
            return Err("backfill mode needs PROPERTY_BACKFILL_TOPIC".into());
        }
        if !loaded.draining.is_empty() {
            return Err("a changelog migration is draining; backfill after it finishes".into());
        }
    } else if !config.property_backfill_group.is_empty() && mode != PropertyStorageMode::Dual {
        return Err("PROPERTY_BACKFILL_GROUP is read in dual mode only".into());
    } else if loaded.writer_group != config.kafka_consumer_group {
        return Err(format!(
            "config/changelog names writer group {} but KAFKA_CONSUMER_GROUP is {}",
            loaded.writer_group, config.kafka_consumer_group
        )
        .into());
    }
    tracing::info!(
        topic = %loaded.topic,
        epoch = loaded.epoch,
        "loaded changelog config"
    );
    // Oldest undrained generation first, so a restart mid-drain resumes it.
    let mut follower = Follower::default();
    let FollowTarget { topic, cluster } = follower
        .select_topic(&loaded, |target| drained(&config, target))
        .await?;

    let mut manager = Manager::builder("personhog-writer")
        .with_global_shutdown_timeout(Duration::from_secs(30))
        .build();

    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(Duration::from_secs(15))
            .with_liveness_deadline(Duration::from_secs(30)),
    );
    // All components must be registered before monitor_background() starts,
    // so writer lane handles are created up front.
    let lanes = config.writer_lanes.max(1);
    let mut writer_handles = Vec::with_capacity(lanes);
    for lane in 0..lanes {
        writer_handles.push(
            manager.register(
                &format!("writer-{lane}"),
                ComponentOptions::new()
                    .with_graceful_shutdown(Duration::from_secs(15))
                    .with_liveness_deadline(Duration::from_secs(30)),
            ),
        );
    }
    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );
    let changelog_handle = manager.register("changelog-config", ComponentOptions::new());
    let ownership_handle = mode
        .writes_slatedb()
        .then(|| manager.register("property-ownership", ComponentOptions::new()));

    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();

    let monitor_guard = manager.monitor_background();

    // Metrics/health HTTP server
    let metrics_port = config.metrics_port;
    tokio::spawn(async move {
        let _guard = metrics_handle.process_scope();

        let health_router = Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let r = readiness.clone();
                    async move { r.check().await }
                }),
            )
            .route("/_liveness", get(move || async move { liveness.check() }));
        // E2E latency is a lag detector: healthy produce-to-commit lag is
        // seconds (the flush cadence), and the interesting tail is minutes
        // of writer lag. The default buckets cap at 10s, which would
        // collapse every lag excursion into +Inf.
        let metrics_router = setup_metrics_routes_with_overrides(
            health_router,
            &[
                (
                    Matcher::Full("personhog_writer_e2e_latency_ms".into()),
                    &[
                        250.0, 1000.0, 2500.0, 5000.0, 10000.0, 30000.0, 60000.0, 120000.0,
                        300000.0, 600000.0,
                    ],
                ),
                (
                    Matcher::Full(personhog_property_store::OBJECT_STORE_REQUEST_DURATION.into()),
                    personhog_property_store::OBJECT_STORE_REQUEST_BUCKETS_SECONDS,
                ),
            ],
        );

        let bind = format!("0.0.0.0:{metrics_port}");
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .expect("Failed to bind metrics port");
        tracing::info!("Metrics server listening on {}", bind);
        axum::serve(listener, metrics_router)
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("Metrics server error");
    });

    let pool = if mode.writes_postgres() {
        let pool_config = PoolConfig {
            max_connections: config.pg_max_connections,
            pool_name: Some("personhog-writer".to_string()),
            statement_timeout_ms: Some(30_000),
            ..Default::default()
        };
        let pool = get_pool_with_config(&config.database_url, pool_config)?;

        // Sample pool state into Prometheus gauges every 5s. Useful for tuning
        // PG_MAX_CONNECTIONS against observed utilization during fallback.
        {
            let pool = pool.clone();
            tokio::spawn(async move {
                let mut ticker = tokio::time::interval(std::time::Duration::from_secs(5));
                loop {
                    ticker.tick().await;
                    metrics::gauge!("personhog_writer_pg_pool_size").set(pool.size() as f64);
                    metrics::gauge!("personhog_writer_pg_pool_idle").set(pool.num_idle() as f64);
                }
            });
        }
        Some(pool)
    } else {
        None
    };

    let backfill_topic = backfilling.then(|| BackfillTopic {
        topic: Arc::from(config.property_backfill_topic.as_str()),
        changelog: Arc::from(topic.as_str()),
    });
    let changelog = changelog_kafka(&config.kafka, cluster.as_ref());
    let kafka_consumer = Arc::new(
        match &backfill_topic {
            Some(backfill) => PersonConsumer::for_backfill(
                &changelog,
                &config.kafka_consumer_group,
                topic.clone(),
                backfill.topic.to_string(),
            )?,
            None => PersonConsumer::from_config(
                &changelog,
                &config.kafka_consumer_group,
                topic.clone(),
            )?,
        }
        .on_cluster(cluster.clone()),
    );
    if let Some(backfill) = &backfill_topic {
        let consumer = Arc::clone(&kafka_consumer);
        let name = backfill.topic.to_string();
        let partitions =
            tokio::task::spawn_blocking(move || consumer.partition_count(&name, METADATA_TIMEOUT))
                .await??;
        // The range assignor co-locates the two topics' partitions only when their counts match.
        if partitions != loaded.partitions {
            return Err(format!(
                "backfill topic {} has {partitions} partitions; the changelog has {}",
                backfill.topic, loaded.partitions
            )
            .into());
        }
    }
    kafka_consumer.set_draining(topic != loaded.topic);
    tracing::info!(topic = %topic, draining = kafka_consumer.is_draining(), "Subscribed to Kafka topic");

    // One statement-concurrency budget for the whole pod: every lane's
    // chunk and per-row statements draw from it, so lanes can overlap
    // writes without collectively oversubscribing the pool.
    let upsert_concurrency = config.upsert_concurrency.max(1);
    if upsert_concurrency > config.pg_max_connections as usize {
        tracing::warn!(
            upsert_concurrency,
            pg_max_connections = config.pg_max_connections,
            "UPSERT_CONCURRENCY exceeds PG_MAX_CONNECTIONS; excess statements \
             will queue on pool acquire instead of the semaphore"
        );
    }
    let upsert_permits = Arc::new(tokio::sync::Semaphore::new(upsert_concurrency));

    let property_writer = if mode.writes_slatedb() {
        let object_store = personhog_property_store::writer_object_store(&config.property_store)?;
        let writer =
            personhog_property_store::PropertyWriter::new(&config.property_store, object_store);
        // A topic still draining is consumed too, so its partitions must fit as well.
        writer.check_partitions(loaded.partitions)?;
        for draining in &loaded.draining {
            writer.check_partitions(draining.partitions)?;
        }
        store
            .require_property_store_layout(&PropertyStoreLayout {
                shards: config.property_store.shards,
                location: config.property_store.location()?,
            })
            .await?;
        tracing::info!(
            location = %config.property_store.location()?,
            shards = config.property_store.shards,
            "Writing properties to SlateDB"
        );
        let writer = Arc::new(writer);
        writer.spawn_maintenance();
        let events = kafka_consumer
            .take_ownership_events()
            .expect("ownership events are taken once");
        tokio::spawn(personhog_writer::property_ownership::run(
            Arc::clone(&kafka_consumer),
            Arc::clone(&writer),
            events,
            backfill_topic.clone(),
            (!config.property_backfill_group.is_empty()).then(|| CatchUp {
                base: base_client_config(&changelog),
                backfill_group: config.property_backfill_group.clone(),
                own_group: config.kafka_consumer_group.clone(),
            }),
            ownership_handle.expect("registered when the property store is enabled"),
        ));
        Some(writer)
    } else {
        // Nothing consumes ownership events without a store, so stop them queuing.
        drop(kafka_consumer.take_ownership_events());
        None
    };

    // Writer lanes: each lane gets its own channel, store, and task, and
    // commits offsets only for the partitions routed to it.
    let mut lane_txs = Vec::with_capacity(lanes);
    for writer_handle in writer_handles {
        let (flush_tx, flush_rx) = mpsc::channel(config.flush_channel_capacity);
        let store = pool.as_ref().map(|pool| {
            let pg = if mode.writes_postgres_properties() {
                PgStore::new(pool.clone(), config.pg_target_table.clone())
            } else {
                PgStore::without_properties(pool.clone(), config.pg_target_table.clone())
            };
            PersonWriteStore::new(
                pg,
                personhog_writer::store::StoreConfig {
                    chunk_size: config.upsert_batch_size,
                    row_fallback_concurrency: config.row_fallback_concurrency,
                },
                Arc::clone(&upsert_permits),
            )
        });
        let mut writer_task =
            WriterTask::new(Arc::clone(&kafka_consumer), store, flush_rx, writer_handle);
        if let Some(properties) = &property_writer {
            writer_task = writer_task.with_properties(Arc::clone(properties));
        }
        if let Some(backfill) = &backfill_topic {
            writer_task = writer_task.with_backfill(backfill.clone());
        }
        tokio::spawn(async move {
            writer_task.run().await;
        });
        lane_txs.push(flush_tx);
    }

    // Consumer task
    let mut consumer_task = ConsumerTask::new(
        Arc::clone(&kafka_consumer),
        lane_txs,
        (config.buffer_capacity / lanes).max(1),
        config.flush_interval(),
        config.flush_buffer_size,
        consumer_handle,
    );
    if let Some(backfill) = &backfill_topic {
        consumer_task = consumer_task.with_backfill(backfill.clone());
    }

    tokio::spawn(async move {
        consumer_task.run().await;
    });

    if backfilling {
        spawn_backfill_pacing(
            Arc::clone(&kafka_consumer),
            config.property_backfill_max_live_lag,
        );
        // A migration's drain waits on the writer group alone, so a backfill writer stops instead of following it.
        let handle = changelog_handle;
        tokio::spawn(async move {
            let _guard = handle.process_scope();
            let cancel = CancellationToken::new();
            let initial_topic = loaded.topic.clone();
            let watch = watch_changelog_config_loop(
                store,
                loaded,
                CHANGELOG_RECONCILE_INTERVAL,
                cancel.clone(),
                move |next| {
                    if next.topic == initial_topic && next.draining.is_empty() {
                        ControlFlow::Continue(())
                    } else {
                        ControlFlow::Break(())
                    }
                },
            );
            tokio::select! {
                _ = handle.shutdown_signal() => cancel.cancel(),
                _ = watch => handle.signal_failure(
                    "a changelog migration started; the backfill writer stops".to_string(),
                ),
            }
        });
    } else {
        // The subscription follows the config; the drain is read from the group's commits.
        let consumer = Arc::clone(&kafka_consumer);
        let config = config.clone();
        let handle = changelog_handle;
        tokio::spawn(async move {
            let _guard = handle.process_scope();
            let cancel = CancellationToken::new();
            let follow = follow_changelog(
                store,
                loaded,
                follower,
                consumer,
                |target: FollowTarget| drained(&config, target),
                Reporter::for_group(&config.kafka_consumer_group),
                |_, _| counter!("personhog_writer_resubscriptions_total").increment(1),
                cancel.clone(),
            );
            tokio::select! {
                _ = handle.shutdown_signal() => cancel.cancel(),
                rebind = follow => {
                    // The pod's restart subscribes on the next generation's cluster.
                    if rebind.is_some() {
                        handle.request_shutdown();
                        handle.shutdown_signal().await;
                    }
                }
            }
        });
    }

    let waited = monitor_guard.wait().await;
    if let Some(properties) = property_writer {
        // A hung object store must not keep the process alive.
        if tokio::time::timeout(STORE_CLOSE_TIMEOUT, properties.close())
            .await
            .is_err()
        {
            tracing::warn!("property store shards did not close in time");
        }
    }
    waited?;
    Ok(())
}

fn spawn_backfill_pacing(consumer: Arc<PersonConsumer>, max_live_lag: i64) {
    tokio::spawn(async move {
        let mut ticker = tokio::time::interval(BACKFILL_PACE_INTERVAL);
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        loop {
            ticker.tick().await;
            let consumer = Arc::clone(&consumer);
            let paced = tokio::task::spawn_blocking(move || {
                consumer.pace_backfill(max_live_lag, METADATA_TIMEOUT)
            })
            .await;
            match paced {
                Ok(Ok(pace)) => {
                    metrics::gauge!("personhog_writer_backfill_live_lag").set(pace.live_lag as f64);
                    metrics::gauge!("personhog_writer_backfill_paused").set(if pace.paused {
                        1.0
                    } else {
                        0.0
                    });
                }
                Ok(Err(e)) => tracing::warn!(error = %e, "backfill pacing failed"),
                Err(e) => tracing::warn!(error = %e, "backfill pacing panicked"),
            }
        }
    });
}

async fn express_repair(args: ExpressRepairArgs) -> Result<(), Box<dyn std::error::Error>> {
    let config = personhog_property_store::PropertyStoreConfig::init_from_env()?;
    let primary = personhog_property_store::object_store(&config)?;
    let buckets = personhog_property_store::express_buckets(&config)?;
    if buckets.is_empty() {
        return Err("PROPERTY_STORE_EXPRESS_BUCKETS names no buckets to repair".into());
    }
    let prefix = personhog_property_store::object_store::path::Path::from(config.prefix.as_str());
    let options = personhog_property_store::repair::RepairOptions {
        orphan_min_age: Duration::from_secs(args.orphan_min_age_secs),
        concurrency: args.concurrency,
        dry_run: args.dry_run,
    };
    let mut failed = 0;
    for bucket in &buckets {
        let report =
            personhog_property_store::repair::repair_bucket(&primary, bucket, &prefix, &options)
                .await?;
        tracing::info!(
            bucket = bucket.name(),
            checked = report.checked,
            copied = report.copied,
            removed = report.removed,
            failed = report.failed,
            dry_run = args.dry_run,
            "express bucket repaired"
        );
        failed += report.failed;
    }
    if failed > 0 {
        return Err(format!("{failed} sst copies could not be repaired").into());
    }
    Ok(())
}

async fn backfill_plan(args: BackfillPlanArgs) -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::init_from_env().expect("Invalid configuration");
    let pool = backfill_pool(&config)?;
    let object_store = personhog_property_store::object_store(&config.property_store)?;
    let run = backfill::Run::new(object_store, &config.property_store.prefix, &args.run_id)?;
    let plan = backfill::plan(&pool, &config.pg_target_table, args.rows_per_range).await?;
    run.save_plan(&plan).await?;
    tracing::info!(
        run_id = %args.run_id,
        table = %config.pg_target_table,
        ranges = plan.ranges.len(),
        "backfill planned"
    );
    Ok(())
}

async fn backfill(args: BackfillArgs) -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::init_from_env().expect("Invalid configuration");
    if config.property_backfill_topic.is_empty() {
        return Err("the backfill needs PROPERTY_BACKFILL_TOPIC".into());
    }
    let store = EtcdStore::connect_with_member_failover(StoreConfig {
        endpoints: config.etcd_endpoint_list(),
        prefix: config.etcd_prefix.clone(),
    })
    .await?;
    let store = PersonhogStore::new(store);
    let Some(loaded) = load_changelog_config(
        &store,
        CHANGELOG_BOOT_POLL_INTERVAL,
        &CancellationToken::new(),
    )
    .await?
    else {
        return Ok(());
    };
    if !loaded.draining.is_empty() {
        return Err("a changelog migration is draining; backfill after it finishes".into());
    }

    let producer = common_kafka::kafka_producer::create_kafka_producer(
        &changelog_kafka(&config.kafka, loaded.cluster.as_ref()),
        Unmonitored,
    )
    .await?;
    let partitions = {
        let producer = producer.clone();
        let topic = config.property_backfill_topic.clone();
        tokio::task::spawn_blocking(move || {
            producer
                .client()
                .fetch_metadata(Some(&topic), METADATA_TIMEOUT)
                .map(|metadata| {
                    metadata
                        .topics()
                        .iter()
                        .find(|t| t.name() == topic)
                        .map_or(0, |t| t.partitions().len() as u32)
                })
        })
        .await??
    };
    if partitions != loaded.partitions {
        return Err(format!(
            "backfill topic {} has {partitions} partitions; the changelog has {}",
            config.property_backfill_topic, loaded.partitions
        )
        .into());
    }

    let pool = backfill_pool(&config)?;
    let object_store = personhog_property_store::object_store(&config.property_store)?;
    let run = backfill::Run::new(object_store, &config.property_store.prefix, &args.run_id)?;
    let sink = backfill::TopicSink::new(
        producer,
        config.property_backfill_topic.clone(),
        loaded.partitions,
    );
    tracing::info!(
        run_id = %args.run_id,
        index = args.index,
        workers = args.workers,
        topic = %config.property_backfill_topic,
        "starting backfill worker"
    );
    let counts =
        backfill::run_worker(&pool, &sink, &run, args.index, args.workers, args.page_size).await?;
    tracing::info!(?counts, "backfill worker finished");
    Ok(())
}

fn backfill_pool(config: &Config) -> Result<sqlx::PgPool, Box<dyn std::error::Error>> {
    Ok(get_pool_with_config(
        &config.database_url,
        PoolConfig {
            max_connections: 2,
            pool_name: Some("personhog-writer-backfill".to_string()),
            statement_timeout_ms: Some(300_000),
            ..Default::default()
        },
    )?)
}

#[derive(Clone)]
struct Unmonitored;

impl common_liveness::SyncLivenessReporter for Unmonitored {
    fn report_healthy(&self) {}
    fn report_unhealthy(&self) {}
}

fn changelog_kafka(base: &KafkaConfig, cluster: Option<&ClusterEndpoint>) -> KafkaConfig {
    match cluster {
        Some(cluster) => base.with_endpoint(&cluster.hosts, cluster.tls),
        None => base.clone(),
    }
}

async fn drained(config: &Config, target: FollowTarget) -> Result<bool, String> {
    let base = base_client_config(&changelog_kafka(&config.kafka, target.cluster.as_ref()));
    let topic = target.topic;
    let group = config.kafka_consumer_group.clone();
    tokio::task::spawn_blocking(move || {
        common_kafka::probe::group_drained(&base, &group, &topic, Duration::from_secs(10))
    })
    .await
    .map_err(|e| format!("drain probe join: {e}"))?
    .map_err(|e| format!("drain probe: {e}"))
}
