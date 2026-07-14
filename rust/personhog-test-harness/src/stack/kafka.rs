use std::time::Duration;

use anyhow::{bail, Context, Result};
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::client::DefaultClientContext;
use rdkafka::config::ClientConfig;
use rdkafka::types::RDKafkaErrorCode;

fn admin_client(kafka_hosts: &str) -> Result<AdminClient<DefaultClientContext>> {
    ClientConfig::new()
        .set("bootstrap.servers", kafka_hosts)
        .create()
        .context("creating kafka admin client")
}

/// Create the changelog topic with exactly `partitions` partitions. The
/// partition count must match `total_partitions` in etcd — a mismatch is a
/// silent mis-shard — so an existing topic with a different count is an
/// error rather than something to adopt.
pub async fn create_topic(kafka_hosts: &str, topic: &str, partitions: u32) -> Result<()> {
    let admin = admin_client(kafka_hosts)?;
    let options = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));

    let new_topic = NewTopic::new(topic, partitions as i32, TopicReplication::Fixed(1));
    let results = admin
        .create_topics([&new_topic], &options)
        .await
        .context("creating changelog topic")?;

    for result in results {
        match result {
            Ok(_) => {}
            Err((name, RDKafkaErrorCode::TopicAlreadyExists)) => {
                bail!(
                    "topic {name} already exists — a previous run may not have torn down; \
                     delete it or pass a different --topic"
                );
            }
            Err((name, code)) => bail!("failed to create topic {name}: {code}"),
        }
    }

    tracing::info!(topic, partitions, "created changelog topic");
    Ok(())
}

pub async fn delete_topic(kafka_hosts: &str, topic: &str) -> Result<()> {
    let admin = admin_client(kafka_hosts)?;
    let options = AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)));

    let results = admin
        .delete_topics(&[topic], &options)
        .await
        .context("deleting changelog topic")?;

    for result in results {
        match result {
            Ok(_) | Err((_, RDKafkaErrorCode::UnknownTopicOrPartition)) => {}
            Err((name, code)) => bail!("failed to delete topic {name}: {code}"),
        }
    }

    tracing::info!(topic, "deleted changelog topic");
    Ok(())
}
