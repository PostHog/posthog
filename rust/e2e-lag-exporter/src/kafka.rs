use anyhow::{Context, Result};
use futures::future::join_all;
use rdkafka::admin::AdminClient;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::message::Message;
use rdkafka::topic_partition_list::{Offset, TopicPartitionList};
use rdkafka::util::Timeout;
use std::time::Duration;
use tracing::{debug, error, info};

use crate::config::Config;
use crate::metrics;

pub struct KafkaMonitor {
    admin_client: AdminClient<rdkafka::client::DefaultClientContext>,
    consumer: StreamConsumer,
    config: Config, // Used for consumer group name and other config
    message_consumer: StreamConsumer,
}

impl KafkaMonitor {
    pub fn new(config: Config) -> Result<Self> {
        let mut common_config = ClientConfig::new();
        common_config
            .set("bootstrap.servers", &config.kafka_hosts)
            .set("session.timeout.ms", "6000");

        if config.kafka_tls {
            common_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        };

        let admin_client: AdminClient<_> = common_config
            .clone()
            .create()
            .context("Failed to create Kafka admin client")?;

        let consumer: StreamConsumer = common_config
            .clone()
            .set("group.id", &config.kafka_consumer_group)
            .set("enable.auto.commit", "false")
            .set("enable.partition.eof", "false")
            .create()
            .context("Failed to create Kafka consumer")?;

        // Create a consumer to get the message at the offset
        let message_consumer: StreamConsumer = common_config
            .clone()
            .set(
                "group.id",
                format!("{}-lag-checker", &config.kafka_consumer_group),
            )
            .set("enable.auto.commit", "false")
            .create()
            .context("Failed to create message fetcher consumer")?;

        let metadata = admin_client
            .inner()
            .fetch_metadata(None, Timeout::from(Duration::from_secs(10)))
            .context("Failed to fetch Kafka metadata")?;

        let topic = metadata
            .topics()
            .iter()
            .find(|t| t.name() == config.kafka_topic.as_str())
            .unwrap();

        let topic_name = topic.name();
        debug!("Checking lag for topic: {}", topic_name);

        let mut tpl = TopicPartitionList::new();
        for partition in topic.partitions() {
            tpl.add_partition(topic_name, partition.id());
        }

        // Assign the consumer to the specific offset
        message_consumer
            .assign(&tpl)
            .context("Failed to assign consumer to partition")?;

        Ok(Self {
            admin_client,
            consumer,
            config,
            message_consumer,
        })
    }

    pub async fn check_lag(&self) -> Result<()> {
        let metadata = self
            .admin_client
            .inner()
            .fetch_metadata(None, Timeout::from(Duration::from_secs(10)))
            .context("Failed to fetch Kafka metadata")?;

        let topic = metadata
            .topics()
            .iter()
            .find(|t| t.name() == self.config.kafka_topic)
            .unwrap();

        let topic_name = topic.name();
        debug!("Checking lag for topic: {}", topic_name);

        let mut tpl = TopicPartitionList::new();
        for partition in topic.partitions() {
            tpl.add_partition(topic_name, partition.id());
        }

        // Get consumer group offsets
        match self
            .consumer
            .committed_offsets(tpl.clone(), Timeout::from(Duration::from_secs(10)))
        {
            Ok(committed_tpl) => {
                let mut futes: Vec<_> = vec![];
                // Process each partition
                for tpl_elem in committed_tpl.elements() {
                    let partition_id = tpl_elem.partition();
                    let topic_name = tpl_elem.topic();
                    if let Offset::Offset(consumer_offset) = tpl_elem.offset() {
                        // Get high watermark (latest offset)
                        match self.consumer.fetch_watermarks(
                            topic_name,
                            partition_id,
                            Timeout::from(Duration::from_secs(10)),
                        ) {
                            Ok((_, high_watermark)) => {
                                // Calculate lag in messages
                                let lag = if high_watermark >= consumer_offset {
                                    high_watermark - consumer_offset
                                } else {
                                    0
                                };

                                info!(
                                    "Topic: {}, Partition: {}, Consumer offset: {}, High watermark: {}, Lag: {}",
                                    topic_name, partition_id, consumer_offset, high_watermark, lag
                                );

                                // Record message count lag metric
                                metrics::record_lag_count(
                                    topic_name,
                                    partition_id,
                                    &self.config.kafka_consumer_group,
                                    lag,
                                );

                                let topic_name_owned = topic_name.to_owned();

                                // concurrently fetch messages, there is one per partition so e.g. 128 fetches
                                futes.push(async move {
                                    // Fetch the message at consumer offset to get timestamp
                                    match self.fetch_message_at_offset(
                                        &topic_name_owned,
                                        partition_id,
                                        consumer_offset
                                    ).await {
                                        Ok(Some((_, Some(timestamp)))) => {
                                            metrics::record_timestamp(
                                                &topic_name_owned,
                                                partition_id,
                                                &self.config.kafka_consumer_group,
                                                timestamp
                                            );
                                        }
                                        Ok(_) => {
                                            debug!(
                                                "Could not determine timestamp for offset {} in {}/{}",
                                                consumer_offset, topic_name_owned, partition_id
                                            );
                                        }
                                        Err(e) => {
                                            error!(
                                                "Error fetching message: {:?}", e
                                            );
                                        }
                                    }
                                })
                            }
                            Err(e) => {
                                error!(
                                    "Failed to fetch watermarks for {}/{}: {:?}",
                                    topic_name, partition_id, e
                                );
                            }
                        }
                    } else {
                        debug!("No offset for {}/{}", topic_name, partition_id);
                    }
                }

                join_all(futes).await;
            }
            Err(e) => {
                error!("Error fetching committed offsets: {:?}", e);
            }
        }

        Ok(())
    }

    async fn fetch_message_at_offset(
        &self,
        topic: &str,
        partition: i32,
        consumer_offset: i64,
    ) -> Result<Option<(i64, Option<i64>)>> {
        self.message_consumer
            .seek(
                topic,
                partition,
                Offset::Offset(consumer_offset - 1),
                Duration::from_secs(5),
            )
            .context("Failed to seek messageconsumer")?;

        // Try to get a single message at the consumer offset
        let timeout = Duration::from_secs(1);
        match tokio::time::timeout(timeout, self.message_consumer.recv()).await {
            Ok(result) => match result {
                Ok(msg) => {
                    // Return the message offset and timestamp (if available)
                    let offset = msg.offset();
                    let timestamp = msg.timestamp().to_millis();

                    debug!(
                        "Message found at offset {} with timestamp {:?}",
                        offset, timestamp
                    );

                    Ok(Some((offset, timestamp)))
                }
                Err(e) => {
                    error!("Failed to get message: {:?}", e);
                    Ok(None)
                }
            },
            Err(_) => {
                debug!("Timeout waiting for message at offset {}", consumer_offset);
                Ok(None)
            }
        }
    }
}
