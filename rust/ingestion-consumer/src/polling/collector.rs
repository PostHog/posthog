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
            generation: 0,
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

    /// Returns how many messages it removed.
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
    /// at most one message, which the topic's `max.message.bytes` bounds.
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

/// The byte count bounds memory, so it counts the key and every header key
/// and value, not only the payload.
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

fn parse_now_ms(value: &str) -> Option<i64> {
    chrono::DateTime::parse_from_rfc3339(value)
        .ok()
        .map(|dt| dt.timestamp_millis())
}

#[cfg(test)]
pub(crate) mod tests {
    use common_kafka_consumer::Offset;
    use metrics_util::debugging::{DebugValue, DebuggingRecorder};
    use rdkafka::message::{Header, OwnedHeaders, OwnedMessage, Timestamp};

    use super::*;

    const BATCH_TIMEOUT: Duration = Duration::from_millis(500);

    struct Sent {
        partition: i32,
        offset: i64,
        key: Option<Vec<u8>>,
        payload: Option<Vec<u8>>,
        timestamp_ms: i64,
        headers: Vec<(&'static str, Vec<u8>)>,
    }

    impl Sent {
        fn new(partition: i32, offset: i64) -> Self {
            Self {
                partition,
                offset,
                key: Some(b"tok:user-1".to_vec()),
                payload: Some(b"{}".to_vec()),
                timestamp_ms: 1_000,
                headers: Vec::new(),
            }
        }

        fn message(&self) -> OwnedMessage {
            let headers = self
                .headers
                .iter()
                .fold(OwnedHeaders::new(), |headers, (key, value)| {
                    headers.insert(Header {
                        key,
                        value: Some(value),
                    })
                });
            OwnedMessage::new(
                self.payload.clone(),
                self.key.clone(),
                "events".to_string(),
                Timestamp::CreateTime(self.timestamp_ms),
                self.partition,
                self.offset,
                Some(headers),
            )
        }
    }

    pub(crate) fn message(partition: i32, offset: i64, payload_bytes: usize) -> OwnedMessage {
        Sent {
            key: Some(format!("tok:user-{offset}").into_bytes()),
            payload: Some(vec![b'x'; payload_bytes]),
            ..Sent::new(partition, offset)
        }
        .message()
    }

    fn collector(batch_size: usize, batch_size_bytes: usize) -> Collector {
        Collector::new(PollLimits {
            batch_size,
            batch_size_bytes,
            batch_timeout: BATCH_TIMEOUT,
        })
    }

    fn collect(sent: &[Sent]) -> CollectedBatch {
        let mut collector = collector(100, 0);
        let now = Instant::now();
        for sent in sent {
            collector.add(&sent.message(), now);
        }
        collector
            .take_ready(now + BATCH_TIMEOUT)
            .expect("the batch timeout passed")
    }

    fn captured(seconds_ago: i64) -> Vec<u8> {
        (chrono::Utc::now() - chrono::Duration::seconds(seconds_ago))
            .to_rfc3339()
            .into_bytes()
    }

    fn deliveries(batch: &CollectedBatch, partition: i32) -> &PartitionDeliveries {
        &batch.partitions[&TopicPartition::new("events", partition)]
    }

    fn offsets(batch: &CollectedBatch, partition: i32) -> Option<(i64, i64)> {
        batch
            .partitions
            .get(&TopicPartition::new("events", partition))
            .map(|deliveries| (deliveries.span.first, deliveries.span.last))
    }

    fn groups(batch: CollectedBatch) -> Vec<(i32, Option<String>, Vec<i64>)> {
        batch
            .accumulator
            .into_groups()
            .into_iter()
            .map(|group| {
                let offsets = group.messages.iter().map(|m| m.offset.0).collect();
                (group.partition.0, group.key, offsets)
            })
            .collect()
    }

    #[test]
    fn a_poll_carries_each_message_whole() {
        let batch = collect(&[Sent {
            key: Some(b"tok:user-1".to_vec()),
            payload: Some(br#"{"event":"$pageview"}"#.to_vec()),
            timestamp_ms: 1_234,
            headers: vec![("token", b"tok".to_vec()), ("binary", vec![0xff, 0xfe])],
            ..Sent::new(3, 42)
        }]);

        let mut groups = batch.accumulator.into_groups();
        assert_eq!(groups.len(), 1);
        let group = groups.remove(0);
        assert_eq!(group.partition, Partition(3));
        assert_eq!(group.key.as_deref(), Some("tok:user-1"));
        assert_eq!(group.messages.len(), 1);
        assert_eq!(group.messages[0].offset, Offset(42));
        let message = &group.messages[0].message;
        assert_eq!(&*message.topic, "events");
        assert_eq!(message.partition, 3);
        assert_eq!(message.offset, 42);
        assert_eq!(message.timestamp, 1_234);
        assert_eq!(message.key.as_deref(), Some("tok:user-1"));
        assert_eq!(message.value.as_deref(), Some(r#"{"event":"$pageview"}"#));
        assert_eq!(
            message.headers,
            HashMap::from([("token".to_string(), "tok".to_string())]),
            "a header that is not UTF-8 is left out"
        );
    }

    #[test]
    fn a_message_that_is_not_utf8_keeps_its_place_without_its_text() {
        let batch = collect(&[Sent {
            key: Some(vec![0xff]),
            payload: Some(vec![0xff, 0xfe, 0xfd]),
            ..Sent::new(0, 7)
        }]);

        assert_eq!(batch.stats.total_bytes, 3);
        assert_eq!(deliveries(&batch, 0).delivered, 1);
        let group = batch.accumulator.into_groups().remove(0);
        assert_eq!(group.key, None, "a key that is not UTF-8 routes as keyless");
        assert_eq!(group.messages[0].offset, Offset(7));
        assert_eq!(group.messages[0].message.value, None);
    }

    #[test]
    fn a_poll_groups_messages_per_partition_and_key_in_the_order_received() {
        let keyed = |partition, offset, key: &str| Sent {
            key: Some(key.as_bytes().to_vec()),
            ..Sent::new(partition, offset)
        };
        let batch = collect(&[
            keyed(0, 0, "a"),
            keyed(0, 1, "b"),
            keyed(1, 5, "a"),
            keyed(0, 2, "a"),
            Sent {
                key: None,
                ..Sent::new(0, 3)
            },
        ]);

        assert_eq!(
            groups(batch),
            vec![
                (0, Some("a".to_string()), vec![0, 2]),
                (0, Some("b".to_string()), vec![1]),
                (1, Some("a".to_string()), vec![5]),
                (0, None, vec![3]),
            ]
        );
    }

    #[test]
    fn a_poll_records_each_partitions_span_charges_and_latest_timestamp() {
        let sent = |offset, timestamp_ms| Sent {
            key: Some(b"k".to_vec()),
            payload: Some(vec![b'x'; 10]),
            timestamp_ms,
            headers: vec![("h", b"vv".to_vec())],
            ..Sent::new(0, offset)
        };
        let batch = collect(&[sent(10, 5_000), sent(12, 3_000), Sent::new(1, 20)]);

        let p0 = deliveries(&batch, 0);
        assert_eq!((p0.span.first, p0.span.last), (10, 12));
        assert_eq!(p0.delivered, 2);
        let each = Charge {
            events: 1,
            bytes: 10 + 1 + 3,
        };
        assert_eq!(
            p0.charges,
            vec![(Offset(10), each), (Offset(12), each)],
            "a charge counts the payload, the key, and every header"
        );
        assert_eq!(p0.latest_kafka_ts, 5_000);
        assert_eq!(deliveries(&batch, 1).delivered, 1);
    }

    #[test]
    fn a_poll_measures_lag_from_each_messages_now_header() {
        let with_now = |partition, offset, now: Vec<u8>| Sent {
            headers: vec![("now", now)],
            ..Sent::new(partition, offset)
        };
        let batch = collect(&[
            with_now(0, 0, captured(60)),
            with_now(0, 1, captured(10)),
            with_now(1, 0, b"not a timestamp".to_vec()),
            Sent::new(1, 1),
        ]);

        let lags: Vec<(i32, i64)> = batch.stats.message_lags_ms.clone();
        assert_eq!(lags.len(), 2, "{lags:?}");
        assert!(lags.iter().all(|(partition, _)| *partition == 0));
        assert!((60_000..61_000).contains(&lags[0].1), "{lags:?}");
        assert!((10_000..11_000).contains(&lags[1].1), "{lags:?}");
        assert_eq!(deliveries(&batch, 0).max_lag_ms, Some(lags[0].1));
        assert_eq!(deliveries(&batch, 1).max_lag_ms, None);
        assert_eq!(batch.stats.total_bytes, 8, "four two-byte payloads");
    }

    struct Bound {
        batch_size: usize,
        batch_size_bytes: usize,
        payloads: Vec<usize>,
        expected_ready_after: usize,
        expected_byte_capped: u64,
    }

    #[rstest::rstest]
    #[case::the_count_bound(Bound { batch_size: 3, batch_size_bytes: 0, payloads: vec![10; 5], expected_ready_after: 3, expected_byte_capped: 0 })]
    #[case::the_byte_bound(Bound { batch_size: 100, batch_size_bytes: 25, payloads: vec![10; 5], expected_ready_after: 3, expected_byte_capped: 1 })]
    #[case::an_oversized_first_message(Bound { batch_size: 100, batch_size_bytes: 25, payloads: vec![100, 10], expected_ready_after: 1, expected_byte_capped: 1 })]
    #[case::no_byte_bound(Bound { batch_size: 4, batch_size_bytes: 0, payloads: vec![1_000; 5], expected_ready_after: 4, expected_byte_capped: 0 })]
    fn a_poll_is_ready_at_its_first_bound(#[case] bound: Bound) {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let _guard = metrics::set_default_local_recorder(&recorder);
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
        let byte_capped = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .find_map(|(key, _, _, value)| match value {
                DebugValue::Counter(count)
                    if key.key().name() == "ingestion_consumer_batches_byte_capped_total" =>
                {
                    Some(count)
                }
                _ => None,
            })
            .unwrap_or(0);
        assert_eq!(byte_capped, bound.expected_byte_capped);
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

        assert_eq!(collector.deadline(), Some(first + BATCH_TIMEOUT));
        assert!(collector
            .take_ready(first + Duration::from_millis(499))
            .is_none());
        let batch = collector
            .take_ready(first + BATCH_TIMEOUT)
            .expect("the timeout passed");
        assert_eq!(offsets(&batch, 0), Some((0, 1)));
        assert_eq!(collector.deadline(), None);
    }

    #[test]
    fn the_next_poll_starts_empty_with_its_own_timeout() {
        let mut collector = collector(100, 0);
        let first = Instant::now();
        collector.add(&message(0, 0, 5), first);
        collector.take_ready(first + BATCH_TIMEOUT);

        let second = first + Duration::from_secs(2);
        collector.add(&message(1, 9, 7), second);

        assert_eq!(collector.deadline(), Some(second + BATCH_TIMEOUT));
        let batch = collector
            .take_ready(second + BATCH_TIMEOUT)
            .expect("the second timeout passed");
        assert_eq!(batch.accumulator.message_count(), 1);
        assert_eq!(offsets(&batch, 0), None);
        assert_eq!(offsets(&batch, 1), Some((9, 9)));
        assert_eq!(batch.stats.total_bytes, 7);
    }

    #[test]
    fn a_removed_partition_leaves_the_poll() {
        let mut collector = collector(100, 0);
        let now = Instant::now();
        let with_now = |partition, offset| Sent {
            payload: Some(vec![b'x'; 5]),
            headers: vec![("now", captured(1))],
            ..Sent::new(partition, offset)
        };
        collector.add(&with_now(0, 10).message(), now);
        collector.add(&with_now(1, 20).message(), now);
        collector.add(&with_now(0, 11).message(), now);

        let removed = collector.remove_partitions(&[TopicPartition::new("events", 0)]);
        collector.add(&message(0, 10, 7), now);

        assert_eq!(removed, 2);
        let batch = collector
            .take_ready(now + BATCH_TIMEOUT)
            .expect("partition 1 and the redelivery stay");
        assert_eq!(batch.stats.total_bytes, 12);
        assert_eq!(
            batch
                .stats
                .message_lags_ms
                .iter()
                .map(|(partition, _)| *partition)
                .collect::<Vec<_>>(),
            vec![1]
        );
        assert_eq!(
            groups(batch),
            vec![
                (1, Some("tok:user-1".to_string()), vec![20]),
                (0, Some("tok:user-10".to_string()), vec![10]),
            ]
        );
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

    #[test]
    fn a_discarded_poll_leaves_nothing_for_the_next() {
        let mut collector = collector(100, 0);
        let now = Instant::now();
        collector.add(&message(0, 10, 5), now);

        collector.discard();
        assert_eq!(collector.deadline(), None);
        collector.add(&message(0, 11, 5), now);

        let batch = collector
            .take_ready(now + BATCH_TIMEOUT)
            .expect("the timeout passed");
        assert_eq!(offsets(&batch, 0), Some((11, 11)));
        assert_eq!(batch.stats.total_bytes, 5);
    }
}
