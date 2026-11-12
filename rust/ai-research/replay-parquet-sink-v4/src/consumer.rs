//! The consume loop. The batcher stores offsets after their files are written, and librdkafka commits the stored
//! offsets on its interval, on revoke and on close.

use std::future::Future;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use futures::FutureExt;
use lifecycle::Handle;
use metrics::counter;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, RebalanceProtocol, StreamConsumer,
};
use rdkafka::error::{KafkaError, KafkaResult, RDKafkaErrorCode};
use rdkafka::message::{BorrowedMessage, Headers as _, Message as _};
use rdkafka::types::RDKafkaRespErr;
use rdkafka::{ClientConfig, ClientContext, Offset, TopicPartitionList};

use crate::batcher::{now_ms, Batcher, Message, OffsetStore, Tp};
use crate::config::Config;
use crate::row::Headers;

const POLL_BATCH: usize = 500;
/// An empty poll still checks the flush interval.
const IDLE_TICK: Duration = Duration::from_millis(500);
const HEARTBEAT: Duration = Duration::from_secs(10);
const MAX_POLL_INTERVAL: Duration = Duration::from_secs(300);
/// How long a flush can run and still own its partitions, with a margin for the polls around it.
pub const OWNED_FOR: Duration = Duration::from_secs(MAX_POLL_INTERVAL.as_secs() - 30);

pub struct SinkContext {
    topic: &'static str,
    revoked: Mutex<Vec<Tp>>,
}

impl ClientContext for SinkContext {}

impl ConsumerContext for SinkContext {
    /// librdkafka commits in the background, so a failed commit reaches no poll. Offsets that stop committing replay
    /// on the next restart.
    fn commit_callback(&self, result: KafkaResult<()>, offsets: &TopicPartitionList) {
        if let Err(error) = result {
            counter!("ai_research_v4_parquet_sink_commit_failures_total").increment(1);
            tracing::warn!(%error, partitions = offsets.count(), "committing offsets failed");
        }
    }

    fn rebalance(
        &self,
        consumer: &BaseConsumer<Self>,
        err: RDKafkaRespErr,
        partitions: &mut TopicPartitionList,
    ) {
        let cooperative = matches!(
            consumer.rebalance_protocol(),
            RebalanceProtocol::Cooperative
        );
        let applied = if err == RDKafkaRespErr::RD_KAFKA_RESP_ERR__ASSIGN_PARTITIONS {
            if cooperative {
                consumer.incremental_assign(partitions)
            } else {
                consumer.assign(partitions)
            }
        } else {
            if err != RDKafkaRespErr::RD_KAFKA_RESP_ERR__REVOKE_PARTITIONS {
                tracing::error!(error = %RDKafkaErrorCode::from(err), "rebalancing failed");
            }
            self.revoked.lock().unwrap().extend(
                partitions
                    .elements()
                    .iter()
                    .filter(|element| element.topic() == self.topic)
                    .map(|element| Tp {
                        topic: self.topic,
                        partition: element.partition(),
                    }),
            );
            if cooperative {
                consumer.incremental_unassign(partitions)
            } else {
                consumer.unassign()
            }
        };
        if let Err(error) = applied {
            tracing::error!(%error, "applying a rebalance failed");
        }
    }
}

pub struct SinkConsumer {
    consumer: Arc<StreamConsumer<SinkContext>>,
}

impl SinkConsumer {
    pub fn new(config: &Config) -> Result<Self, KafkaError> {
        let topic: &'static str = Box::leak(config.topic.clone().into_boxed_str());
        let kafka = &config.kafka;
        let mut client = ClientConfig::new();
        client
            .set("bootstrap.servers", &kafka.kafka_hosts)
            .set("group.id", &config.group_id)
            .set("auto.offset.reset", "earliest")
            .set("enable.auto.commit", "true")
            .set("enable.auto.offset.store", "false")
            .set("partition.assignment.strategy", "cooperative-sticky")
            .set("session.timeout.ms", "30000")
            .set("heartbeat.interval.ms", "10000")
            .set(
                "max.poll.interval.ms",
                MAX_POLL_INTERVAL.as_millis().to_string(),
            )
            .set("fetch.max.bytes", "50242880")
            .set("max.partition.fetch.bytes", "10485760")
            .set("fetch.wait.max.ms", "10000")
            .set("fetch.error.backoff.ms", "100")
            .set("queued.min.messages", "1000")
            .set("queued.max.messages.kbytes", "102400")
            .set("topic.metadata.refresh.interval.ms", "60000")
            .set("metadata.max.age.ms", "30000")
            .set("socket.timeout.ms", "30000")
            .set("enable.partition.eof", "false");
        if kafka.kafka_tls {
            client.set("security.protocol", "ssl");
        }
        if !kafka.kafka_client_rack.is_empty() {
            client.set("client.rack", &kafka.kafka_client_rack);
        }
        if !kafka.kafka_client_id.is_empty() {
            client.set("client.id", &kafka.kafka_client_id);
        }
        let consumer: StreamConsumer<SinkContext> = client.create_with_context(SinkContext {
            topic,
            revoked: Mutex::new(Vec::new()),
        })?;
        consumer.subscribe(&[topic])?;
        Ok(Self {
            consumer: Arc::new(consumer),
        })
    }

    fn take_revoked(&self) -> Vec<Tp> {
        std::mem::take(&mut self.consumer.context().revoked.lock().unwrap())
    }

    fn topic(&self) -> &'static str {
        self.consumer.context().topic
    }

    fn commit_stored(&self) {
        if let Err(error) = self.consumer.commit_consumer_state(CommitMode::Sync) {
            tracing::warn!(%error, "committing the stored offsets on shutdown failed");
        }
    }
}

pub struct KafkaOffsets(Arc<StreamConsumer<SinkContext>>);

impl OffsetStore for KafkaOffsets {
    fn store(&self, offsets: &[(Tp, i64)]) -> Result<(), String> {
        let mut list = TopicPartitionList::new();
        for (tp, offset) in offsets {
            list.add_partition_offset(tp.topic, tp.partition, Offset::Offset(*offset))
                .map_err(|error| error.to_string())?;
        }
        self.0
            .store_offsets(&list)
            .map_err(|error| error.to_string())
    }
}

impl SinkConsumer {
    pub fn offsets(&self) -> KafkaOffsets {
        KafkaOffsets(self.consumer.clone())
    }
}

fn message<'m>(topic: &'static str, message: &'m BorrowedMessage<'_>) -> Message<'m> {
    let headers = message.headers().map_or_else(Headers::default, |headers| {
        Headers::from_pairs(headers.iter().map(|header| (header.key, header.value)))
    });
    Message {
        tp: Tp {
            topic,
            partition: message.partition(),
        },
        offset: message.offset(),
        headers,
        value: message.payload(),
    }
}

/// Runs `work` while reporting the component healthy, so a slow but bounded flush does not fail the liveness check.
async fn with_heartbeat<T>(handle: &Handle, work: impl Future<Output = T>) -> T {
    tokio::pin!(work);
    let mut heartbeat = tokio::time::interval(HEARTBEAT);
    loop {
        tokio::select! {
            done = &mut work => return done,
            _ = heartbeat.tick() => handle.report_healthy(),
        }
    }
}

/// The reason the client failed for good, when only a restart recovers it.
fn receive_failed(consumer: &SinkConsumer, error: &KafkaError) -> Option<String> {
    tracing::warn!(%error, "kafka receive failed");
    counter!("ai_research_v4_parquet_sink_kafka_errors_total").increment(1);
    let (code, reason) = consumer.consumer.client().fatal_error()?;
    Some(format!("kafka consumer fatal error {code}: {reason}"))
}

fn release_revoked<O: OffsetStore>(consumer: &SinkConsumer, batcher: &mut Batcher<O>) {
    let revoked = consumer.take_revoked();
    if !revoked.is_empty() {
        batcher.release(&revoked);
    }
}

/// Hands the batcher one batch of messages. A revocation reported while the batch was read splits it, so the rows
/// read before the revoke are released with their partition and the rows read after it stay.
fn add_batch<O: OffsetStore>(
    consumer: &SinkConsumer,
    batcher: &mut Batcher<O>,
    first: BorrowedMessage<'_>,
) -> Option<String> {
    let topic = consumer.topic();
    let mut segment = Vec::with_capacity(POLL_BATCH);
    let mut received = 0;
    let mut next = Some(first);
    let mut fatal = None;
    while let Some(borrowed) = next.take() {
        let revoked = consumer.take_revoked();
        if !revoked.is_empty() {
            batcher.add(
                &segment
                    .iter()
                    .map(|m| message(topic, m))
                    .collect::<Vec<_>>(),
            );
            segment.clear();
            batcher.release(&revoked);
        }
        segment.push(borrowed);
        received += 1;
        if received < POLL_BATCH {
            match consumer.consumer.recv().now_or_never() {
                Some(Ok(borrowed)) => next = Some(borrowed),
                Some(Err(error)) => fatal = receive_failed(consumer, &error),
                None => {}
            }
        }
    }
    batcher.add(
        &segment
            .iter()
            .map(|m| message(topic, m))
            .collect::<Vec<_>>(),
    );
    fatal
}

enum Step {
    Continue,
    Shutdown,
    Fatal(String),
}

pub async fn consume<O: OffsetStore>(
    consumer: SinkConsumer,
    mut batcher: Batcher<O>,
    handle: Handle,
) {
    let shutdown = handle.shutdown_signal();
    tokio::pin!(shutdown);
    let mut tick = tokio::time::interval(IDLE_TICK);
    let mut failure = None;
    loop {
        let step = tokio::select! {
            _ = &mut shutdown => Step::Shutdown,
            _ = tick.tick() => Step::Continue,
            received = consumer.consumer.recv() => {
                let fatal = match received {
                    Ok(first) => add_batch(&consumer, &mut batcher, first),
                    Err(error) => receive_failed(&consumer, &error),
                };
                fatal.map_or(Step::Continue, Step::Fatal)
            }
        };
        // A poll can run the rebalance callback and still return nothing, so every step releases what it revoked.
        release_revoked(&consumer, &mut batcher);
        match step {
            Step::Continue => {}
            Step::Shutdown => break,
            Step::Fatal(reason) => {
                failure = Some(reason);
                break;
            }
        }
        handle.report_healthy();
        let now = now_ms();
        if batcher.should_flush(now) {
            if let Err(error) = with_heartbeat(&handle, batcher.flush(now)).await {
                // Nothing of this flush is stored. The shutdown flush below tries once more.
                tracing::error!(%error, "flush failed");
                failure = Some(format!("flush failed: {error}"));
                break;
            }
        } else if batcher.watermark_files_due(now) {
            with_heartbeat(&handle, batcher.write_watermark_files_if_due(now)).await;
        }
    }
    // Flush the buffer so a graceful restart does not read it again. A failed final flush replays on restart.
    if let Err(error) = with_heartbeat(&handle, batcher.flush(now_ms())).await {
        tracing::warn!(%error, "ai_research_v4_parquet_sink_shutdown_flush_failed");
    }
    consumer.commit_stored();
    // Reported only now: a failed component ends the process, which would cancel the flush above.
    if let Some(reason) = failure {
        handle.signal_failure(reason);
    }
}
