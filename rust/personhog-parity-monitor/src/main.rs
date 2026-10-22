use std::time::Duration;

use anyhow::{Context, Result};
use envconfig::Envconfig;
use health::HealthRegistry;
use tokio::sync::mpsc;
use tracing::info;
use tracing::level_filters::LevelFilter;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter};

use personhog_parity_monitor::config::Config;
use personhog_parity_monitor::feed::TopicReader;
use personhog_parity_monitor::join::{Event, Join, JoinConfig, Kind, SampleRing};
use personhog_parity_monitor::{pipeline, server};

common_alloc::used!();

/// A reader or the join that reports nothing for this long is dead.
const LIVENESS_DEADLINE: Duration = Duration::from_secs(60);
const EVENT_QUEUE: usize = 10_000;

#[tokio::main]
async fn main() -> Result<()> {
    let config = Config::init_from_env().context("reading the configuration")?;
    tracing_subscriber::registry()
        .with(fmt::layer().with_target(true).with_level(true))
        .with(
            EnvFilter::builder()
                .with_default_directive(LevelFilter::INFO.into())
                .from_env_lossy(),
        )
        .init();

    let join_config = JoinConfig {
        grace: config.grace(),
        idle_partition: config.idle_partition(),
        max_entries: config.parity_max_entries,
        teams: config.teams().map_err(anyhow::Error::msg)?,
        mapping_lag: config.mapping_lag(),
        warmup: config.warmup(),
        person_ignored_properties: config.person_ignored_properties(),
    };
    let mut kinds = vec![Kind::DistinctIds, Kind::MergeEvents];
    if config.compares_persons().map_err(anyhow::Error::msg)? {
        kinds.push(Kind::Persons);
    }
    info!(
        grace_seconds = config.parity_grace_seconds,
        max_entries = config.parity_max_entries,
        teams = ?join_config.teams,
        persons = kinds.contains(&Kind::Persons),
        debug_api = config.debug_api_secret().is_some(),
        "starting personhog-parity-monitor"
    );

    let health = HealthRegistry::new("personhog-parity-monitor");
    let samples = SampleRing::new(config.parity_sample_ring_size);
    // Building the router installs the metrics recorder; counter handles the
    // tasks create before that would bind to the no-op recorder for good.
    let router = server::router(
        health.clone(),
        samples.clone(),
        config.debug_api_secret().map(str::to_string),
    );
    let (events, arrivals) = mpsc::channel(EVENT_QUEUE);

    // The join drains the queue, so it runs before the first reader fills it.
    let join_health = health.register("join".to_string(), LIVENESS_DEADLINE).await;
    tokio::spawn(pipeline::run(
        Join::new(join_config, samples),
        arrivals,
        config.sweep_interval(),
        join_health,
    ));

    for feed in config.feeds() {
        for &kind in &kinds {
            let feed_for_reader = feed.clone();
            // rdkafka's metadata fetch and assignment block the thread.
            let (reader, partitions) =
                tokio::task::spawn_blocking(move || TopicReader::connect(&feed_for_reader, kind))
                    .await
                    .context("the reader setup task panicked")??;
            let topic = reader.topic();
            info!(
                feed = topic.side.label(),
                topic = topic.kind.label(),
                partitions,
                hosts = %feed.kafka_hosts,
                "assigned every partition at the end of the log"
            );
            events
                .send(Event::Assigned { topic, partitions })
                .await
                .context("the join is gone")?;
            let handle = health
                .register(
                    format!("{}-{}", topic.side.label(), topic.kind.label()),
                    LIVENESS_DEADLINE,
                )
                .await;
            tokio::spawn(reader.run(events.clone(), handle, config.metadata_poll()));
        }
    }
    drop(events);

    let bind = config.bind();
    info!(%bind, "serving metrics");
    common_metrics::serve(router, &bind)
        .await
        .context("serving metrics")?;
    Ok(())
}
