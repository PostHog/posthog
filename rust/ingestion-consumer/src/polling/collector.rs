use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_kafka_consumer::{Charge, Partition, TopicPartition};
use metrics::counter;
use rdkafka::message::{Headers, Message};
use tokio::time::Instant;

use super::poll::{BatchStats, CollectedBatch, Delivery, PartitionDeliveries};
use crate::types::{Accumulator, SerializedKafkaMessage};

#[derive(Debug, Clone, Copy)]
pub(crate) struct PollLimits {
    pub(crate) batch_size: usize,
    /// Payload-byte bound; `0` disables it.
    pub(crate) batch_size_bytes: usize,
    pub(crate) batch_timeout: Duration,
}

pub(crate) struct Collector {
    limits: PollLimits,
    deadline: Option<Instant>,
    accumulator: Accumulator,
    partitions: HashMap<TopicPartition, PartitionDeliveries>,
    stats: BatchStats,
    started_ms: i64,
    current_topic: Option<Arc<str>>,
}

impl Collector {
    pub(crate) fn new(limits: PollLimits) -> Self {
        Self {
            limits,
            deadline: None,
            accumulator: Accumulator::default(),
            partitions: HashMap::new(),
            stats: BatchStats::default(),
            started_ms: 0,
            current_topic: None,
        }
    }

    /// The first message of a poll starts its batch timeout.
    pub(crate) fn add(&mut self, message: &impl Message, now: Instant) {
        if self.deadline.is_none() {
            self.deadline = Some(now + self.limits.batch_timeout);
            self.started_ms = current_time_ms();
        }
        if self.current_topic.as_deref() != Some(message.topic()) {
            self.current_topic = Some(Arc::from(message.topic()));
        }
        let topic = Arc::clone(self.current_topic.as_ref().expect("set above"));
        let partition = message.partition();
        let offset = message.offset();
        let kafka_ts = message.timestamp().to_millis().unwrap_or(0);

        let payload_bytes = message.payload().map(|v| v.len()).unwrap_or(0);
        self.stats.total_bytes += payload_bytes;

        let mut headers = HashMap::new();
        if let Some(rdkafka_headers) = message.headers() {
            for i in 0..rdkafka_headers.count() {
                let header = rdkafka_headers.get(i);
                if let Some(value) = header.value {
                    if let Ok(value_str) = std::str::from_utf8(value) {
                        headers.insert(header.key.to_string(), value_str.to_string());
                    }
                }
            }
        }

        let lag_ms = headers
            .get("now")
            .and_then(|v| parse_now_ms(v))
            .map(|capture_ms| (self.started_ms - capture_ms).max(0));
        if let Some(lag_ms) = lag_ms {
            self.stats.message_lags_ms.push((partition, lag_ms));
        }

        let delivery = Delivery {
            offset,
            charge: message_charge(message),
            payload_bytes,
            kafka_ts,
            lag_ms,
        };
        let key = TopicPartition::new(topic.to_string(), partition);
        match self.partitions.get_mut(&key) {
            Some(deliveries) => deliveries.record(&delivery),
            None => {
                self.partitions
                    .insert(key, PartitionDeliveries::new(&delivery));
            }
        }

        let serialized = SerializedKafkaMessage {
            topic,
            partition,
            offset,
            timestamp: kafka_ts,
            key: message
                .key()
                .and_then(|k| std::str::from_utf8(k).ok())
                .map(|s| s.to_string()),
            value: message
                .payload()
                .and_then(|v| std::str::from_utf8(v).ok())
                .map(|s| s.to_string()),
            headers,
        };

        self.accumulator
            .push(Partition(partition), serialized.into());
    }

    pub(crate) fn deadline(&self) -> Option<Instant> {
        self.deadline
    }

    pub(crate) fn take_ready(&mut self, now: Instant) -> Option<CollectedBatch> {
        let deadline = self.deadline?;
        if deadline > now && !self.is_full() {
            return None;
        }
        self.deadline = None;
        Some(CollectedBatch {
            accumulator: std::mem::take(&mut self.accumulator),
            partitions: std::mem::take(&mut self.partitions),
            stats: std::mem::take(&mut self.stats),
        })
    }

    /// Returns the messages removed.
    pub(crate) fn remove_partitions(&mut self, topic_partitions: &[TopicPartition]) -> usize {
        let mut removed = 0;
        for topic_partition in topic_partitions {
            let Some(deliveries) = self.partitions.remove(topic_partition) else {
                continue;
            };
            let partition = topic_partition.partition;
            self.accumulator.remove_partition(Partition(partition));
            self.stats.total_bytes -= deliveries.payload_bytes;
            self.stats
                .message_lags_ms
                .retain(|(lagging, _)| *lagging != partition);
            removed += deliveries.delivered as usize;
        }
        if self.partitions.is_empty() {
            self.discard();
        }
        removed
    }

    pub(crate) fn discard(&mut self) {
        self.deadline = None;
        self.accumulator = Accumulator::default();
        self.partitions.clear();
        self.stats = BatchStats::default();
    }

    /// The byte bound counts only messages already added, so a poll always
    /// carries one message, even one larger than the bound. The overshoot is
    /// at most one message, which `fetch.message.max.bytes` bounds.
    fn is_full(&self) -> bool {
        if self.accumulator.message_count() >= self.limits.batch_size {
            return true;
        }
        if self.limits.batch_size_bytes > 0
            && self.stats.total_bytes >= self.limits.batch_size_bytes
        {
            counter!("ingestion_consumer_batches_byte_capped_total").increment(1);
            return true;
        }
        false
    }
}

/// One delivered message's cost against the ledger: one event, and the bytes
/// the process holds for the message. The byte count is a memory bound, so it
/// is the payload plus the key plus every header key and value, not only the
/// payload.
fn message_charge(message: &impl Message) -> Charge {
    let payload_bytes = message.payload().map(|v| v.len()).unwrap_or(0);
    let key_bytes = message.key().map(|k| k.len()).unwrap_or(0);
    let mut header_bytes = 0;
    if let Some(headers) = message.headers() {
        for i in 0..headers.count() {
            let header = headers.get(i);
            header_bytes += header.key.len() + header.value.map(|v| v.len()).unwrap_or(0);
        }
    }
    Charge {
        events: 1,
        bytes: (payload_bytes + key_bytes + header_bytes) as u64,
    }
}

fn current_time_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

/// Parse an ISO 8601 / RFC 3339 timestamp string into milliseconds since epoch.
/// Returns `None` if the string is missing or unparseable.
fn parse_now_ms(value: &str) -> Option<i64> {
    chrono::DateTime::parse_from_rfc3339(value)
        .ok()
        .map(|dt| dt.timestamp_millis())
}

#[cfg(test)]
pub(crate) mod tests {
    use rdkafka::message::{OwnedHeaders, OwnedMessage, Timestamp};

    use super::*;

    pub(crate) fn message(partition: i32, offset: i64, payload_bytes: usize) -> OwnedMessage {
        OwnedMessage::new(
            Some(vec![b'x'; payload_bytes]),
            Some(format!("tok:user-{offset}").into_bytes()),
            "events".to_string(),
            Timestamp::CreateTime(1_000),
            partition,
            offset,
            Some(OwnedHeaders::new()),
        )
    }

    fn collector(batch_size: usize, batch_size_bytes: usize) -> Collector {
        Collector::new(PollLimits {
            batch_size,
            batch_size_bytes,
            batch_timeout: Duration::from_millis(500),
        })
    }

    fn offsets(batch: &CollectedBatch, partition: i32) -> Option<(i64, i64)> {
        batch
            .partitions
            .get(&TopicPartition::new("events", partition))
            .map(|deliveries| (deliveries.span.first, deliveries.span.last))
    }

    struct Bound {
        batch_size: usize,
        batch_size_bytes: usize,
        payloads: Vec<usize>,
        expected_ready_after: usize,
    }

    #[rstest::rstest]
    #[case::the_count_bound(Bound { batch_size: 3, batch_size_bytes: 0, payloads: vec![10; 5], expected_ready_after: 3 })]
    #[case::the_byte_bound(Bound { batch_size: 100, batch_size_bytes: 25, payloads: vec![10; 5], expected_ready_after: 3 })]
    #[case::an_oversized_first_message(Bound { batch_size: 100, batch_size_bytes: 25, payloads: vec![100, 10], expected_ready_after: 1 })]
    #[case::no_byte_bound(Bound { batch_size: 4, batch_size_bytes: 0, payloads: vec![1_000; 5], expected_ready_after: 4 })]
    fn a_poll_is_ready_at_its_first_bound(#[case] bound: Bound) {
        let mut collector = collector(bound.batch_size, bound.batch_size_bytes);
        let now = Instant::now();

        let mut ready_after = None;
        for (offset, &payload) in bound.payloads.iter().enumerate() {
            collector.add(&message(0, offset as i64, payload), now);
            if collector.take_ready(now).is_some() {
                ready_after = Some(offset + 1);
                break;
            }
        }

        assert_eq!(ready_after, Some(bound.expected_ready_after));
    }

    #[test]
    fn a_poll_is_ready_once_its_first_message_is_a_batch_timeout_old() {
        let mut collector = collector(100, 0);
        let first = Instant::now();
        assert_eq!(
            collector.deadline(),
            None,
            "an empty collector has no deadline"
        );

        collector.add(&message(0, 0, 1), first);
        collector.add(&message(0, 1, 1), first + Duration::from_millis(400));

        assert_eq!(
            collector.deadline(),
            Some(first + Duration::from_millis(500))
        );
        assert!(collector
            .take_ready(first + Duration::from_millis(499))
            .is_none());
        let batch = collector
            .take_ready(first + Duration::from_millis(500))
            .expect("the timeout passed");
        assert_eq!(offsets(&batch, 0), Some((0, 1)));
        assert_eq!(collector.deadline(), None);
    }

    #[test]
    fn a_removed_partition_leaves_the_poll() {
        let mut collector = collector(100, 0);
        let now = Instant::now();
        collector.add(&message(0, 10, 5), now);
        collector.add(&message(1, 20, 7), now);
        collector.add(&message(0, 11, 5), now);

        let removed = collector.remove_partitions(&[TopicPartition::new("events", 0)]);
        collector.add(&message(0, 10, 5), now);

        assert_eq!(removed, 2);
        let batch = collector
            .take_ready(now + Duration::from_millis(500))
            .expect("partition 1 and the redelivery stay");
        assert_eq!(batch.accumulator.message_count(), 2);
        assert_eq!(offsets(&batch, 0), Some((10, 10)));
        assert_eq!(offsets(&batch, 1), Some((20, 20)));
        assert_eq!(batch.stats.total_bytes, 12);
    }

    #[test]
    fn removing_every_partition_ends_the_poll() {
        let mut collector = collector(100, 0);
        collector.add(&message(0, 10, 5), Instant::now());

        collector.remove_partitions(&[TopicPartition::new("events", 0)]);

        assert_eq!(collector.deadline(), None);
        assert!(collector
            .take_ready(Instant::now() + Duration::from_secs(1))
            .is_none());
    }
}
