//! Configured as `consumer-v1.ts` configures node-rdkafka, with offsets stored by the loop and committed by auto commit.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Duration;

use async_trait::async_trait;
use ingestion_framework::KafkaMessage;
use rand::Rng;
use rdkafka::consumer::{
    BaseConsumer, CommitMode, Consumer, ConsumerContext, Rebalance, StreamConsumer,
};
use rdkafka::error::KafkaError;
use rdkafka::message::{BorrowedMessage, Headers, Message};
use rdkafka::{ClientConfig, ClientContext, Offset, TopicPartitionList};

use super::consumer_loop::{BatchSource, OffsetsToStore};

pub fn consumer_client_config(
    group_id: &str,
    overrides: &[(String, String)],
    client_rack: Option<&str>,
    test_env: bool,
) -> ClientConfig {
    let mut config = ClientConfig::new();
    let host = super::kafka_outputs::hostname();
    for (k, v) in [
        ("client.id", host.as_str()),
        ("security.protocol", "plaintext"),
        ("metadata.broker.list", "kafka:9092"),
        ("log_level", "4"),
        ("session.timeout.ms", "30000"),
        ("max.poll.interval.ms", "300000"),
        ("max.partition.fetch.bytes", "1048576"),
        ("fetch.error.backoff.ms", "100"),
        ("fetch.message.max.bytes", "10485760"),
        ("fetch.wait.max.ms", "50"),
        ("queued.min.messages", "100000"),
        ("queued.max.messages.kbytes", "102400"),
        ("metadata.max.age.ms", "30000"),
        ("socket.timeout.ms", "30000"),
        ("enable.partition.eof", "true"),
        // Node sets this in both consumer versions, so a new group starts at the oldest offset.
        ("auto.offset.reset", "earliest"),
    ] {
        config.set(k, v);
    }
    if let Some(rack) = client_rack {
        config.set("client.rack", rack);
    }
    for (k, v) in overrides {
        config.set(k, v);
    }
    config
        .set("group.id", group_id)
        .set(
            "partition.assignment.strategy",
            if test_env {
                "roundrobin"
            } else {
                "cooperative-sticky"
            },
        )
        .set("enable.auto.offset.store", "false")
        .set("enable.auto.commit", "true");
    strip_classic_protocol_config(&mut config);
    config
}

/// librdkafka rejects these classic-protocol keys under `group.protocol=consumer`, so they go after every other key is set.
pub fn strip_classic_protocol_config(config: &mut ClientConfig) {
    if config.get("group.protocol") != Some("consumer") {
        return;
    }
    for key in [
        "session.timeout.ms",
        "heartbeat.interval.ms",
        "partition.assignment.strategy",
        "group.protocol.type",
    ] {
        config.remove(key);
    }
}

pub fn to_kafka_message(m: &BorrowedMessage<'_>) -> KafkaMessage {
    let headers = m
        .headers()
        .map(|hs| {
            hs.iter()
                .map(|h| (h.key.to_string(), h.value.map(<[u8]>::to_vec)))
                .collect()
        })
        .unwrap_or_default();
    KafkaMessage {
        topic: m.topic().to_string(),
        partition: m.partition(),
        offset: m.offset(),
        key: m.key().map(<[u8]>::to_vec),
        value: m.payload().map(bytes::Bytes::copy_from_slice),
        headers,
        timestamp: m.timestamp().to_millis(),
    }
}

/// A revoke bumps each revoked partition's epoch, so a task dispatched before it cannot store its offset after a reassignment.
#[derive(Default)]
pub struct PartitionEpochs(Mutex<HashMap<(String, i32), u64>>);

impl PartitionEpochs {
    pub fn revoke(&self, partitions: impl IntoIterator<Item = (String, i32)>) {
        let mut epochs = self.0.lock().unwrap();
        for p in partitions {
            *epochs.entry(p).or_default() += 1;
        }
    }

    pub fn snapshot(&self) -> HashMap<(String, i32), u64> {
        self.0.lock().unwrap().clone()
    }

    pub fn storable(&self, offsets: &OffsetsToStore, dispatch: &[u64]) -> OffsetsToStore {
        let epochs = self.0.lock().unwrap();
        offsets
            .iter()
            .zip(dispatch)
            .filter(|((topic, partition, _), at)| {
                epochs
                    .get(&(topic.clone(), *partition))
                    .copied()
                    .unwrap_or_default()
                    == **at
            })
            .map(|(o, _)| o.clone())
            .collect()
    }
}

#[derive(Default)]
pub struct FencingContext {
    pub epochs: PartitionEpochs,
}

impl ClientContext for FencingContext {}

impl ConsumerContext for FencingContext {
    fn pre_rebalance(&self, _: &BaseConsumer<Self>, rebalance: &Rebalance<'_>) {
        if let Rebalance::Revoke(tpl) = rebalance {
            self.epochs.revoke(
                tpl.elements()
                    .iter()
                    .map(|e| (e.topic().to_string(), e.partition())),
            );
        }
    }
}

pub type LogsConsumer = StreamConsumer<FencingContext>;

pub struct KafkaBatchSource {
    consumer: std::mem::ManuallyDrop<LogsConsumer>,
    dispatch_epochs: HashMap<(String, i32), u64>,
}

impl KafkaBatchSource {
    pub fn new(consumer: LogsConsumer) -> Self {
        Self {
            consumer: std::mem::ManuallyDrop::new(consumer),
            dispatch_epochs: HashMap::new(),
        }
    }

    pub fn consumer(&self) -> &LogsConsumer {
        &self.consumer
    }
}

impl Drop for KafkaBatchSource {
    fn drop(&mut self) {
        // librdkafka deadlocks when it destroys a client after a fatal error, so that client leaks and the process exits.
        if self.consumer.client().fatal_error().is_some() {
            return;
        }
        // SAFETY: `consumer` is not used after this point, and `drop` runs once.
        // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
        unsafe { std::mem::ManuallyDrop::drop(&mut self.consumer) }
    }
}

/// node-rdkafka sets no `isRetriable` on a consume error, so every error is tried 3 times before the loop fails.
pub async fn retry_consume<T, F, Fut>(mut attempt: F) -> anyhow::Result<T>
where
    F: FnMut() -> Fut,
    Fut: std::future::Future<Output = anyhow::Result<T>>,
{
    const TRIES: u32 = 3;
    const JITTER: f64 = 0.05;
    let mut sleep_ms = 100.0_f64;
    let mut tries = 1;
    loop {
        match attempt().await {
            Ok(v) => return Ok(v),
            Err(error) if tries >= TRIES => return Err(error),
            Err(error) => {
                tracing::warn!(error = %error, tries, "kafka consume failed, retrying");
                let jittered = sleep_ms * (1.0 - JITTER + rand::thread_rng().gen::<f64>() * JITTER);
                tokio::time::sleep(Duration::from_secs_f64(jittered / 1000.0)).await;
                sleep_ms = (sleep_ms * 2.0).min(10_000.0);
                tries += 1;
            }
        }
    }
}

/// An error is returned only when no message was read, as node-rdkafka's `ConsumeNum` does.
pub async fn recv_batch<C: ConsumerContext + 'static>(
    consumer: &StreamConsumer<C>,
    max: usize,
    timeout: Duration,
) -> anyhow::Result<Vec<KafkaMessage>> {
    let deadline = tokio::time::Instant::now() + timeout;
    let mut out = Vec::new();
    while out.len() < max {
        match tokio::time::timeout_at(deadline, consumer.recv()).await {
            Err(_) => break,
            Ok(Ok(m)) => out.push(to_kafka_message(&m)),
            Ok(Err(KafkaError::PartitionEOF(_))) => continue,
            Ok(Err(e)) => {
                tracing::warn!(error = %e, "kafka consume error");
                if out.is_empty() {
                    return Err(e.into());
                }
                break;
            }
        }
    }
    Ok(out)
}

#[async_trait]
impl BatchSource for KafkaBatchSource {
    async fn next_batch(
        &mut self,
        max: usize,
        timeout: Duration,
    ) -> anyhow::Result<Vec<KafkaMessage>> {
        // Rebalance callbacks run inside recv, so every message here was read under this epoch or an older one.
        self.dispatch_epochs = self.consumer.context().epochs.snapshot();
        let consumer = &self.consumer;
        let batch = retry_consume(|| recv_batch(consumer, max, timeout)).await;
        // A fatal error is reported once, and later polls return empty batches, so the client state decides.
        if let Some((code, reason)) = consumer.client().fatal_error() {
            anyhow::bail!("fatal kafka consumer error {code:?}: {reason}");
        }
        batch
    }

    fn epochs(&self, offsets: &OffsetsToStore) -> Vec<u64> {
        offsets
            .iter()
            .map(|(topic, partition, _)| {
                self.dispatch_epochs
                    .get(&(topic.clone(), *partition))
                    .copied()
                    .unwrap_or_default()
            })
            .collect()
    }

    fn store_offsets(&mut self, offsets: &OffsetsToStore, epochs: &[u64]) -> anyhow::Result<()> {
        let storable = self.consumer.context().epochs.storable(offsets, epochs);
        let fenced = offsets.len() - storable.len();
        if fenced > 0 {
            metrics::counter!("logs_ingestion_consumer_stale_store_offsets_skipped_total")
                .increment(fenced as u64);
        }
        if storable.is_empty() {
            return Ok(());
        }
        let mut tpl = TopicPartitionList::new();
        for (topic, partition, offset) in &storable {
            tpl.add_partition_offset(topic, *partition, Offset::Offset(*offset))?;
        }
        // librdkafka also rejects a store for a partition this member no longer holds.
        if let Err(error) = self.consumer.store_offsets(&tpl) {
            tracing::warn!(error = %error, "offset store rejected");
        }
        Ok(())
    }

    fn commit(&mut self) -> anyhow::Result<()> {
        match self.consumer.commit_consumer_state(CommitMode::Sync) {
            Ok(())
            | Err(KafkaError::ConsumerCommit(rdkafka::types::RDKafkaErrorCode::NoOffset)) => Ok(()),
            Err(e) => Err(e.into()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU32, Ordering};

    #[tokio::test(start_paused = true)]
    async fn consume_errors_retry_like_retry_if_retriable_then_fail() {
        let calls = AtomicU32::new(0);
        let recovered = retry_consume(|| async {
            match calls.fetch_add(1, Ordering::SeqCst) {
                0 | 1 => Err(anyhow::anyhow!("transient")),
                _ => Ok(7),
            }
        })
        .await;
        assert_eq!(recovered.unwrap(), 7);
        calls.store(0, Ordering::SeqCst);
        let failed: anyhow::Result<()> = retry_consume(|| async {
            calls.fetch_add(1, Ordering::SeqCst);
            Err(anyhow::anyhow!("down"))
        })
        .await;
        assert_eq!(failed.unwrap_err().to_string(), "down");
        assert_eq!(calls.load(Ordering::SeqCst), 3);
    }

    #[test]
    fn a_revoke_fences_only_the_revoked_partition() {
        let epochs = PartitionEpochs::default();
        let offsets: OffsetsToStore = vec![("in".into(), 0, 5), ("in".into(), 1, 9)];
        let at_dispatch = vec![0, 0];
        epochs.revoke([("in".to_string(), 1)]);
        assert_eq!(
            epochs.storable(&offsets, &at_dispatch),
            vec![("in".to_string(), 0, 5)]
        );
        let after = epochs.snapshot();
        assert_eq!(after.get(&("in".to_string(), 1)), Some(&1));
        assert_eq!(epochs.storable(&offsets, &[0, 1]), offsets);
    }

    fn config(overrides: &[(&str, &str)]) -> ClientConfig {
        let overrides: Vec<(String, String)> = overrides
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        consumer_client_config("g", &overrides, None, false)
    }

    #[test]
    fn consumer_config_matches_node_offset_reset_and_kip848_strip() {
        let classic = config(&[]);
        assert_eq!(classic.get("auto.offset.reset"), Some("earliest"));
        assert_eq!(
            classic.get("partition.assignment.strategy"),
            Some("cooperative-sticky")
        );
        assert_eq!(
            config(&[("auto.offset.reset", "latest")]).get("auto.offset.reset"),
            Some("latest")
        );
        let kip848 = config(&[
            ("group.protocol", "consumer"),
            ("heartbeat.interval.ms", "3000"),
        ]);
        for key in [
            "session.timeout.ms",
            "heartbeat.interval.ms",
            "partition.assignment.strategy",
        ] {
            assert_eq!(kip848.get(key), None, "{key}");
        }
        assert_eq!(kip848.get("group.id"), Some("g"));
    }
}
