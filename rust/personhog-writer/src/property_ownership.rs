//! Order does not matter: the store ignores an assign that was revoked or superseded.

use std::sync::Arc;
use std::time::Duration;

use bytes::Bytes;
use lifecycle::Handle;
use personhog_property_store::{PartitionKey, PropertyRecord, PropertyStoreError, PropertyWriter};
use personhog_proto::personhog::types::v1::Person;
use rdkafka::error::KafkaError;
use tokio::sync::mpsc;

use crate::kafka::{OwnershipEvent, PersonConsumer, Source};

const METADATA_TIMEOUT: Duration = Duration::from_secs(10);
const RETRY_BACKOFF: Duration = Duration::from_secs(1);

pub fn partition_key(source: &Source) -> PartitionKey {
    PartitionKey {
        topic: Arc::clone(&source.topic),
        partition: source.partition as u32,
    }
}

pub fn property_record(person: &Person) -> PropertyRecord {
    PropertyRecord {
        team_id: person.team_id,
        person_id: person.id,
        version: person.version,
        deleted: person.is_deleted,
        properties: Bytes::copy_from_slice(&person.properties),
    }
}

pub trait Assignments: Send + Sync + 'static {
    fn generation(&self, source: &Source) -> Option<u64>;
    fn partition_count(&self, topic: &str, timeout: Duration) -> Result<u32, KafkaError>;
}

impl Assignments for PersonConsumer {
    fn generation(&self, source: &Source) -> Option<u64> {
        PersonConsumer::generation(self, source)
    }

    fn partition_count(&self, topic: &str, timeout: Duration) -> Result<u32, KafkaError> {
        PersonConsumer::partition_count(self, topic, timeout)
    }
}

/// The event channel never closes: its sender lives in the consumer this task holds.
pub async fn run<C: Assignments>(
    consumer: Arc<C>,
    writer: Arc<PropertyWriter>,
    mut events: mpsc::UnboundedReceiver<OwnershipEvent>,
    handle: Handle,
) {
    loop {
        let event = tokio::select! {
            biased;
            _ = handle.shutdown_signal() => return,
            event = events.recv() => match event {
                Some(event) => event,
                None => return,
            },
        };
        let writer = Arc::clone(&writer);
        match event {
            OwnershipEvent::Assigned(source, generation) => {
                let consumer = Arc::clone(&consumer);
                let handle = handle.clone();
                tokio::spawn(async move {
                    assign(&consumer, &writer, &source, generation, &handle).await;
                });
            }
            OwnershipEvent::Revoked(source, generation) => {
                tokio::spawn(async move {
                    writer.revoke(&partition_key(&source), generation).await;
                    tracing::info!(topic = %source.topic, partition = source.partition, generation, "property store shards closed");
                });
            }
        }
    }
}

async fn assign<C: Assignments>(
    consumer: &Arc<C>,
    writer: &PropertyWriter,
    source: &Source,
    generation: u64,
    handle: &Handle,
) {
    let still_assigned = || consumer.generation(source) == Some(generation);
    loop {
        if handle.is_shutting_down() || !still_assigned() {
            return;
        }
        let partitions = {
            let consumer = Arc::clone(consumer);
            let topic = source.topic.to_string();
            tokio::task::spawn_blocking(move || consumer.partition_count(&topic, METADATA_TIMEOUT))
                .await
        };
        let partitions = match partitions {
            Ok(Ok(partitions)) => partitions,
            Ok(Err(e)) => {
                tracing::warn!(topic = %source.topic, error = %e, "changelog partition count unavailable; retrying");
                backoff(handle).await;
                continue;
            }
            Err(e) => {
                handle.signal_failure(format!("partition count lookup panicked: {e}"));
                return;
            }
        };
        match writer
            .assign(
                &partition_key(source),
                generation,
                partitions,
                still_assigned,
            )
            .await
        {
            Ok(()) => {
                tracing::info!(topic = %source.topic, partition = source.partition, generation, partitions, "property store shards opened");
                return;
            }
            Err(PropertyStoreError::ShardLayout(reason)) => {
                handle.signal_failure(reason);
                return;
            }
            Err(e) => {
                tracing::warn!(topic = %source.topic, partition = source.partition, error = %e, "opening property store shards failed; retrying");
                backoff(handle).await;
            }
        }
    }
}

async fn backoff(handle: &Handle) {
    tokio::select! {
        _ = handle.shutdown_signal() => {}
        _ = tokio::time::sleep(RETRY_BACKOFF) => {}
    }
}

#[cfg(test)]
mod tests {
    use lifecycle::{ComponentOptions, Manager};
    use personhog_property_store::object_store::local::LocalFileSystem;
    use personhog_property_store::PropertyStoreConfig;

    use super::*;

    struct Unassigned;

    impl Assignments for Unassigned {
        fn generation(&self, _source: &Source) -> Option<u64> {
            None
        }

        fn partition_count(&self, _topic: &str, _timeout: Duration) -> Result<u32, KafkaError> {
            Ok(1)
        }
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn the_ownership_task_finishes_on_shutdown_while_its_events_stay_open() {
        let dir = tempfile::tempdir().unwrap();
        let writer = Arc::new(PropertyWriter::new(
            &PropertyStoreConfig::local("props", 1),
            Arc::new(LocalFileSystem::new_with_prefix(dir.path()).unwrap()),
        ));
        let mut manager = Manager::builder("test")
            .with_global_shutdown_timeout(Duration::from_secs(5))
            .build();
        let handle = manager.register("property-ownership", ComponentOptions::new());
        let shutdown = handle.clone();
        let monitor = manager.monitor_background();
        let (_events, received) = mpsc::unbounded_channel();
        tokio::spawn(run(Arc::new(Unassigned), writer, received, handle));

        shutdown.request_shutdown();
        drop(shutdown);

        assert!(monitor.wait().await.is_ok(), "shutdown must not time out");
    }
}
