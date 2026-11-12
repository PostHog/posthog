//! A `dual` writer replays the changelog from the backfill group's committed offset up to its own
//! group's. The backfill writers stop before `dual` starts, so that offset no longer moves, and a
//! replay a crash interrupts repeats in full on the next owner.

use std::sync::Arc;
use std::time::Duration;

use lifecycle::Handle;
use metrics::counter;
use personhog_property_store::{PartitionKey, PropertyRecord, PropertyWriter, PutError};
use personhog_proto::personhog::types::v1::Person;
use prost::Message;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::error::KafkaError;
use rdkafka::message::Message as KafkaMessage;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use tokio::sync::{mpsc, Semaphore};

use crate::property_ownership::property_record;

const KAFKA_TIMEOUT: Duration = Duration::from_secs(10);
const POLL_TIMEOUT: Duration = Duration::from_secs(1);
const CHUNK_ROWS: usize = 1000;
const RETRY_BACKOFF: Duration = Duration::from_secs(1);

#[derive(Clone)]
pub struct CatchUp {
    pub base: ClientConfig,
    pub backfill_group: String,
    pub own_group: String,
    /// Bounds the replays in flight; each holds a consumer and its prefetch.
    pub permits: Arc<Semaphore>,
}

/// The changelog offsets `[from, to)` the backfill writer may not have written.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Range {
    pub from: i64,
    pub to: i64,
}

impl CatchUp {
    fn committed(
        &self,
        group: &str,
        topic: &str,
        partition: i32,
    ) -> Result<Option<i64>, KafkaError> {
        let consumer: BaseConsumer = self
            .base
            .clone()
            .set("group.id", group)
            .set("enable.auto.commit", "false")
            .create()?;
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition(topic, partition);
        let committed = consumer.committed_offsets(tpl, KAFKA_TIMEOUT)?;
        Ok(committed.elements().first().and_then(|e| match e.offset() {
            Offset::Offset(offset) => Some(offset),
            _ => None,
        }))
    }

    /// Blocking: call off the async runtime.
    pub fn range(&self, topic: &str, partition: i32) -> Result<Option<Range>, KafkaError> {
        // Without a commit this group reads the partition from its first record.
        let Some(to) = self.committed(&self.own_group, topic, partition)? else {
            return Ok(None);
        };
        let from = match self.committed(&self.backfill_group, topic, partition)? {
            Some(from) => from,
            None => {
                let consumer: BaseConsumer = self.base.create()?;
                consumer
                    .fetch_watermarks(topic, partition, KAFKA_TIMEOUT)?
                    .0
            }
        };
        Ok((from < to).then_some(Range { from, to }))
    }

    /// Blocking: call off the async runtime.
    fn read(
        &self,
        topic: &str,
        partition: i32,
        range: Range,
        chunks: mpsc::Sender<Vec<PropertyRecord>>,
    ) -> Result<(), KafkaError> {
        let consumer: BaseConsumer = self
            .base
            .clone()
            // Polling without a group reports an error; this one never joins or commits.
            .set("group.id", format!("{}-catch-up", self.own_group))
            .set("enable.auto.commit", "false")
            .set("enable.partition.eof", "true")
            // Retention may have deleted the range's start; the rest of it is still there.
            .set("auto.offset.reset", "earliest")
            .set("isolation.level", "read_committed")
            // 8 MiB of prefetch per replay rather than librdkafka's 64 MiB.
            .set("queued.max.messages.kbytes", "8192")
            .create()?;
        let mut tpl = TopicPartitionList::new();
        tpl.add_partition_offset(topic, partition, Offset::Offset(range.from))?;
        consumer.assign(&tpl)?;
        let mut chunk = Vec::with_capacity(CHUNK_ROWS);
        loop {
            let Some(polled) = consumer.poll(POLL_TIMEOUT) else {
                if chunks.is_closed() {
                    return Ok(());
                }
                continue;
            };
            let message = match polled {
                Ok(message) => message,
                Err(KafkaError::PartitionEOF(_)) => break,
                Err(e) => return Err(e),
            };
            if message.offset() >= range.to {
                break;
            }
            match message.payload().map(Person::decode) {
                Some(Ok(person)) => chunk.push(property_record(&person)),
                Some(Err(e)) => {
                    counter!("personhog_writer_decode_errors_total").increment(1);
                    tracing::warn!(error = %e, partition, offset = message.offset(), "failed to decode Person proto");
                }
                None => {}
            }
            if chunk.len() >= CHUNK_ROWS
                && chunks
                    .blocking_send(std::mem::replace(
                        &mut chunk,
                        Vec::with_capacity(CHUNK_ROWS),
                    ))
                    .is_err()
            {
                return Ok(());
            }
        }
        if !chunk.is_empty() {
            chunks.blocking_send(chunk).ok();
        }
        Ok(())
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum Outcome {
    Finished { rows: u64 },
    Lost,
}

pub async fn replay(
    catch_up: &CatchUp,
    writer: &PropertyWriter,
    key: &PartitionKey,
    generation: u64,
    range: Range,
    handle: &Handle,
    still_assigned: impl Fn() -> bool,
) -> Result<Outcome, KafkaError> {
    let _permit = catch_up.permits.acquire().await;
    let (tx, mut chunks) = mpsc::channel(2);
    let reader = {
        let catch_up = catch_up.clone();
        let topic = key.topic.to_string();
        let partition = key.partition as i32;
        tokio::task::spawn_blocking(move || catch_up.read(&topic, partition, range, tx))
    };
    let mut rows = 0;
    // Dropping the receiver stops the reader at its next chunk.
    while let Some(chunk) = chunks.recv().await {
        loop {
            if handle.is_shutting_down() {
                return Ok(Outcome::Lost);
            }
            match writer.put(key, generation, &chunk).await {
                Ok(()) => break,
                // A late opener fenced a partition this pod still owns; the main path retries the same way.
                Err(PutError::Lost) if still_assigned() => {
                    tracing::warn!(topic = %key.topic, partition = key.partition, "catch-up fenced while still assigned; retrying");
                    tokio::time::sleep(RETRY_BACKOFF).await;
                }
                Err(PutError::Lost) => return Ok(Outcome::Lost),
                Err(PutError::Invariant(reason)) => {
                    handle.signal_failure(format!("property store catch-up: {reason}"));
                    return Ok(Outcome::Lost);
                }
                Err(e @ (PutError::NotReady | PutError::Store(_))) => {
                    tracing::warn!(topic = %key.topic, partition = key.partition, error = %e, "catch-up write failed; retrying");
                    tokio::time::sleep(RETRY_BACKOFF).await;
                }
            }
        }
        rows += chunk.len() as u64;
        counter!("personhog_writer_property_catch_up_rows_total").increment(chunk.len() as u64);
    }
    match reader.await {
        Ok(read) => read?,
        Err(e) => {
            handle.signal_failure(format!("catch-up reader panicked: {e}"));
            return Ok(Outcome::Lost);
        }
    }
    Ok(Outcome::Finished { rows })
}
