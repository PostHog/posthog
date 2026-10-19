use std::time::Duration;

use anyhow::{bail, Context};
use assignment_coordination::store::{EtcdStore, StoreConfig};
use etcd_client::Client;
use personhog_coordination::store::PersonhogStore;
use personhog_coordination::types::ChangelogConfig;
use rdkafka::consumer::Consumer;
use serde::Serialize;

use crate::config::Config;
use crate::kafka::client::metadata_consumer;
use crate::kafka::lag::{scan_group_lag, ConsumerTarget};

fn store(client: &Client, prefix: &str) -> PersonhogStore {
    PersonhogStore::new(EtcdStore::from_client(
        client.clone(),
        StoreConfig {
            endpoints: Vec::new(),
            prefix: prefix.to_string(),
        },
    ))
}

pub async fn topic_partition_count(config: &Config, topic: &str) -> anyhow::Result<u32> {
    let timeout = Duration::from_millis(config.kafka_metadata_timeout_ms);
    let config = config.clone();
    let topic = topic.to_string();
    tokio::task::spawn_blocking(move || {
        let consumer = metadata_consumer(&config).context("create metadata client")?;
        let metadata = consumer
            .fetch_metadata(Some(&topic), timeout)
            .with_context(|| format!("fetch metadata for {topic}"))?;
        let topic_metadata = metadata
            .topics()
            .iter()
            .find(|t| t.name() == topic)
            .with_context(|| format!("topic {topic} is absent from broker metadata"))?;
        if let Some(error) = topic_metadata.error() {
            bail!("topic {topic}: {error:?}");
        }
        let count = topic_metadata.partitions().len();
        if count == 0 {
            bail!("topic {topic} has no partitions");
        }
        Ok(count as u32)
    })
    .await
    .context("metadata task panicked")?
}

pub async fn seed(
    config: &Config,
    client: &Client,
    prefix: &str,
    topic: &str,
    writer_group: &str,
) -> anyhow::Result<ChangelogConfig> {
    let config = &config.personhog_kafka();
    let partitions = topic_partition_count(config, topic).await?;
    let created = store(client, prefix)
        .seed_changelog_config(topic, partitions, writer_group)
        .await?;
    if !created {
        bail!("config/changelog is already seeded");
    }
    Ok(ChangelogConfig {
        writer_group: writer_group.to_string(),
        ..ChangelogConfig::new(topic, partitions)
    })
}

#[derive(Serialize)]
pub struct GroupLag {
    pub group: String,
    pub partitions: usize,
    pub lagging_partitions: usize,
    pub total_lag: i64,
    pub max_partition_lag: i64,
    pub error: Option<String>,
}

#[derive(Serialize)]
pub struct ChangelogView {
    pub config: Option<ChangelogConfig>,
    pub writer: Option<GroupLag>,
}

pub async fn view(config: &Config, client: &Client, prefix: &str) -> anyhow::Result<ChangelogView> {
    let config = &config.personhog_kafka();
    let store = store(client, prefix);
    let changelog = store.get_changelog_config().await?;
    let writer = match &changelog {
        Some(changelog) => Some(group_lag(config, &changelog.writer_group, &changelog.topic).await),
        None => None,
    };
    Ok(ChangelogView {
        config: changelog,
        writer,
    })
}

async fn group_lag(config: &Config, group: &str, topic: &str) -> GroupLag {
    let target = ConsumerTarget {
        group: group.to_string(),
        topic: topic.to_string(),
    };
    match scan_group_lag(config, &target).await {
        Ok(lag) => GroupLag {
            group: group.to_string(),
            partitions: lag.partitions.len(),
            lagging_partitions: lag.partitions.iter().filter(|p| p.lag > 0).count(),
            total_lag: lag.partitions.iter().map(|p| p.lag).sum(),
            max_partition_lag: lag.partitions.iter().map(|p| p.lag).max().unwrap_or(0),
            error: None,
        },
        Err(e) => GroupLag {
            group: group.to_string(),
            partitions: 0,
            lagging_partitions: 0,
            total_lag: 0,
            max_partition_lag: 0,
            error: Some(format!("{e:#}")),
        },
    }
}
