use std::{
    fmt,
    sync::{Arc, Weak},
};

use rdkafka::{
    consumer::{Consumer, ConsumerGroupMetadata, StreamConsumer},
    error::KafkaError,
    ClientConfig, Message,
};
use serde::de::DeserializeOwned;
use std::time::Duration;

use crate::config::{ConsumerConfig, KafkaConfig};

#[derive(Clone)]
pub struct SingleTopicConsumer {
    inner: Arc<Inner>,
}

struct Inner {
    consumer: StreamConsumer,
    topic: String,
}

#[derive(Debug, thiserror::Error)]
pub enum RecvErr {
    #[error("Kafka error: {0}")]
    Kafka(#[from] KafkaError),
    #[error("Serde error: {0}")]
    Serde(#[from] serde_json::Error),
    #[error("Received empty payload")]
    Empty,
}

#[derive(Debug, thiserror::Error)]
pub enum OffsetErr {
    #[error("Kafka error: {0}")]
    Kafka(#[from] KafkaError),
    #[error("Consumer gone")]
    Gone,
}

impl SingleTopicConsumer {
    pub fn new(
        common_config: KafkaConfig,
        consumer_config: ConsumerConfig,
    ) -> Result<Self, KafkaError> {
        let mut client_config = ClientConfig::new();
        client_config
            .set("bootstrap.servers", &common_config.kafka_hosts)
            .set("statistics.interval.ms", "10000")
            .set("group.id", consumer_config.kafka_consumer_group)
            .set(
                "auto.offset.reset",
                &consumer_config.kafka_consumer_offset_reset,
            );

        // IMPORTANT: this means *by default* all consumers are
        // responsible for storing their own offsets, regardless
        // of whether automatic offset commit is enabled or disabled!
        client_config.set("enable.auto.offset.store", "false");

        if common_config.kafka_tls {
            client_config
                .set("security.protocol", "ssl")
                .set("enable.ssl.certificate.verification", "false");
        };

        if consumer_config.kafka_consumer_auto_commit {
            client_config.set("enable.auto.commit", "true").set(
                "auto.commit.interval.ms",
                consumer_config
                    .kafka_consumer_auto_commit_interval_ms
                    .to_string(),
            );
        }

        let consumer: StreamConsumer = client_config.create()?;
        consumer.subscribe(&[consumer_config.kafka_consumer_topic.as_str()])?;

        let inner = Inner {
            consumer,
            topic: consumer_config.kafka_consumer_topic,
        };
        Ok(Self {
            inner: Arc::new(inner),
        })
    }

    pub async fn json_recv<T>(&self) -> Result<(T, Offset), RecvErr>
    where
        T: DeserializeOwned,
    {
        let message = self.inner.consumer.recv().await?;

        let offset = Offset {
            handle: Arc::downgrade(&self.inner),
            partition: message.partition(),
            offset: message.offset(),
            topic: self.inner.topic.clone(),
        };

        let Some(payload) = message.payload() else {
            // We auto-store poison pills, panicking on failure
            offset.store().unwrap();
            return Err(RecvErr::Empty);
        };

        let payload = match serde_json::from_slice(payload) {
            Ok(p) => p,
            Err(e) => {
                // We auto-store poison pills, panicking on failure
                offset.store().unwrap();
                return Err(RecvErr::Serde(e));
            }
        };

        Ok((payload, offset))
    }

    pub async fn json_recv_batch<T>(
        &self,
        max: usize,
        timeout: Duration,
    ) -> Vec<Result<(T, Offset), RecvErr>>
    where
        T: DeserializeOwned,
    {
        let mut results = Vec::with_capacity(max);

        tokio::select! {
            _ = tokio::time::sleep(timeout) => {},
            _ = async {
                while results.len() < max {
                    let result = self.json_recv::<T>().await;
                    let was_err = result.is_err();
                    results.push(result);
                    if was_err {
                        break; // Early exit on error, since it might indicate a kafka error or somethingz
                    }
                }
            } => {}
        }

        results
    }

    pub fn metadata(&self) -> ConsumerGroupMetadata {
        self.inner
            .consumer
            .group_metadata()
            .expect("It is impossible to construct a stream consumer without a group id")
    }
}

pub struct Offset {
    handle: Weak<Inner>,
    pub(crate) topic: String,
    pub(crate) partition: i32,
    pub(crate) offset: i64,
}

impl Offset {
    pub fn store(self) -> Result<(), OffsetErr> {
        let inner = self.handle.upgrade().ok_or(OffsetErr::Gone)?;
        inner
            .consumer
            .store_offset(&self.topic, self.partition, self.offset)?;
        Ok(())
    }

    pub fn get_value(&self) -> i64 {
        self.offset
    }
}

impl fmt::Debug for Offset {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(
            f,
            "{{ partition: {}, offset: {} }}",
            self.partition, self.offset
        )
    }
}
