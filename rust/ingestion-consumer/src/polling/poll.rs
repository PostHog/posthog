use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::Instant;

use common_kafka_consumer::{Charge, Offset, Partition, TopicPartition};
use rdkafka::message::{Headers, Message};

use crate::debug_recorder::{PartitionOffset, PartitionOffsets};
use crate::order_sentinel::OffsetSpan;
use crate::settlement::ChargedSlice;
use crate::types::{Accumulator, SerializedKafkaMessage};

/// Batch-wide statistics gathered while collecting, used to emit parity
/// metrics. Per-partition facts live on [`PartitionDeliveries`].
pub(crate) struct BatchStats {
    /// Per-message (partition, lag_ms) pairs — for `ingestion_lag_ms_histogram`.
    pub(crate) message_lags_ms: Vec<(i32, i64)>,
    /// Total byte size of message payloads — for `consumer_batch_size_kb`.
    pub(crate) total_bytes: usize,
}

impl BatchStats {
    fn new() -> Self {
        Self {
            message_lags_ms: Vec::new(),
            total_bytes: 0,
        }
    }
}

/// One delivered message, as the batch records it against its partition.
pub(crate) struct Delivery {
    pub(crate) offset: i64,
    pub(crate) charge: Charge,
    pub(crate) payload_bytes: usize,
    /// Kafka message timestamp (ms).
    pub(crate) kafka_ts: i64,
    /// Ingestion lag (ms); `None` without a parseable `now` header.
    pub(crate) lag_ms: Option<i64>,
}

/// What a batch saw delivered from one partition, folded in one map entry
/// per message. The span bounds what the batch delivered; the stamped
/// charges feed the ledger.
pub(crate) struct PartitionDeliveries {
    /// The offsets the batch delivered, first to last.
    pub(crate) span: OffsetSpan,
    /// The ledger generation, set when the poll is charged.
    pub(crate) generation: u64,
    pub(crate) charges: Vec<(Offset, Charge)>,
    pub(crate) payload_bytes: usize,
    /// Max Kafka message timestamp (ms) — for `latest_processed_timestamp_ms`.
    pub(crate) latest_kafka_ts: i64,
    /// Max ingestion lag (ms) — for `ingestion_lag_ms`.
    pub(crate) max_lag_ms: Option<i64>,
    /// Messages the poll delivered, covered, and accepted from this
    /// partition, so a revoked partition can leave the poll exactly.
    pub(crate) delivered: u32,
    pub(crate) covered: u32,
    pub(crate) accepted: u32,
    /// The offsets a completion covered. Keyed by offset rather than by
    /// position in `span`, because a poll can span an offset gap.
    pub(crate) credited: HashSet<i64, ahash::RandomState>,
}

impl PartitionDeliveries {
    pub(crate) fn new(delivery: &Delivery) -> Self {
        Self {
            span: OffsetSpan::new(delivery.offset),
            generation: 0,
            charges: vec![(Offset(delivery.offset), delivery.charge)],
            payload_bytes: delivery.payload_bytes,
            latest_kafka_ts: delivery.kafka_ts,
            max_lag_ms: delivery.lag_ms,
            delivered: 1,
            covered: 0,
            accepted: 0,
            credited: HashSet::default(),
        }
    }

    /// Credit a completion's run and return the offsets to settle: those
    /// charged that no earlier completion credited.
    pub(crate) fn credit_run(&mut self, run: &[Offset]) -> Vec<Offset> {
        let Self {
            credited, charges, ..
        } = self;
        run.iter()
            .copied()
            .filter(|offset| {
                credited.insert(offset.0)
                    && charges
                        .binary_search_by_key(&offset.0, |(charged, _)| charged.0)
                        .is_ok()
            })
            .collect()
    }

    pub(crate) fn uncredited_charge(&self) -> Option<Offset> {
        self.charges
            .iter()
            .map(|(offset, _)| *offset)
            .find(|offset| !self.credited.contains(&offset.0))
    }

    pub(crate) fn record(&mut self, delivery: &Delivery) {
        self.span.extend(delivery.offset);
        self.delivered += 1;
        self.payload_bytes += delivery.payload_bytes;
        self.latest_kafka_ts = self.latest_kafka_ts.max(delivery.kafka_ts);
        if let Some(lag_ms) = delivery.lag_ms {
            self.max_lag_ms = Some(self.max_lag_ms.map_or(lag_ms, |max| max.max(lag_ms)));
        }
        self.charges
            .push((Offset(delivery.offset), delivery.charge));
    }

    fn charge(&self) -> Charge {
        self.charges.iter().map(|(_, charge)| *charge).sum()
    }
}

/// One collected poll, ready to charge and submit.
pub(crate) struct CollectedBatch {
    /// The poll's messages, demuxed per partition and routing key.
    pub(crate) accumulator: Accumulator,
    pub(crate) partitions: HashMap<TopicPartition, PartitionDeliveries>,
    pub(crate) stats: BatchStats,
}

/// One submitted poll, awaiting its group completions. The consumer
/// correlates completions to it by assignment epoch, partition, and offset;
/// the poll retires only once completions cover every message.
pub(crate) struct InFlightPoll {
    /// Consumer-side id for logs and debug events only; the batcher's
    /// internal batch id never crosses the boundary.
    pub(crate) poll_id: String,
    /// The epoch the batcher stamped on this poll's completions.
    pub(crate) assignment_epoch: u64,
    pub(crate) partitions: HashMap<TopicPartition, PartitionDeliveries>,
    pub(crate) uncommitted: HashMap<TopicPartition, Charge>,
    pub(crate) message_count: u32,
    /// Messages covered by completions so far, accepted or not.
    pub(crate) covered: u32,
    /// Worker-accepted messages so far. The poll retires only when this
    /// reaches `message_count`.
    pub(crate) accepted: u32,
    pub(crate) dispatched_at: Instant,
}

impl InFlightPoll {
    pub(crate) fn is_complete(&self) -> bool {
        self.covered >= self.message_count
    }

    /// A charged offset that no completion covered. A complete poll can still
    /// have one, because one offset credited twice fills `covered` as well.
    pub(crate) fn uncredited_charge(&self) -> Option<(&TopicPartition, Offset)> {
        self.partitions
            .iter()
            .find_map(|(topic_partition, deliveries)| {
                deliveries
                    .uncredited_charge()
                    .map(|offset| (topic_partition, offset))
            })
    }

    pub(crate) fn charged_slices(&self) -> Vec<ChargedSlice<'_>> {
        self.partitions
            .iter()
            .map(|(topic_partition, deliveries)| ChargedSlice {
                topic_partition,
                generation: deliveries.generation,
                span: deliveries.span,
                charges: &deliveries.charges,
            })
            .collect()
    }
}

pub(crate) struct PollBuilder {
    accumulator: Accumulator,
    partitions: HashMap<TopicPartition, PartitionDeliveries>,
    stats: BatchStats,
    charge: Charge,
    started_ms: i64,
    current_topic: Option<Arc<str>>,
}

impl PollBuilder {
    pub(crate) fn new() -> Self {
        Self {
            accumulator: Accumulator::default(),
            partitions: HashMap::new(),
            stats: BatchStats::new(),
            charge: Charge::ZERO,
            started_ms: current_time_ms(),
            current_topic: None,
        }
    }

    pub(crate) fn message_count(&self) -> usize {
        self.accumulator.message_count()
    }

    pub(crate) fn payload_bytes(&self) -> usize {
        self.stats.total_bytes
    }

    pub(crate) fn charge(&self) -> Charge {
        self.charge
    }

    pub(crate) fn add(&mut self, message: &impl Message) {
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
        self.charge += delivery.charge;
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

    /// Returns the messages removed.
    pub(crate) fn remove_partition(&mut self, topic_partition: &TopicPartition) -> usize {
        let Some(deliveries) = self.partitions.remove(topic_partition) else {
            return 0;
        };
        let partition = topic_partition.partition;
        self.accumulator.remove_partition(Partition(partition));
        self.charge -= deliveries.charge();
        self.stats.total_bytes -= deliveries.payload_bytes;
        self.stats
            .message_lags_ms
            .retain(|(lagging, _)| *lagging != partition);
        deliveries.delivered as usize
    }

    pub(crate) fn finish(self) -> CollectedBatch {
        CollectedBatch {
            accumulator: self.accumulator,
            partitions: self.partitions,
            stats: self.stats,
        }
    }
}

/// Per-partition max offset + observed lag for the debug UI's batch events.
pub(crate) fn debug_partition_offsets(
    partitions: &HashMap<TopicPartition, PartitionDeliveries>,
) -> Vec<PartitionOffset> {
    partitions
        .iter()
        .map(|(topic_partition, partition)| PartitionOffset {
            topic: topic_partition.topic.clone(),
            partition: topic_partition.partition,
            offset: partition.span.last,
            lag_ms: partition.max_lag_ms.unwrap_or(0),
        })
        .collect()
}

/// Per-partition offset ranges, so the debug UI can match requests to polls.
pub(crate) fn debug_partition_spans(
    partitions: &HashMap<TopicPartition, PartitionDeliveries>,
) -> Vec<PartitionOffsets> {
    partitions
        .iter()
        .map(|(topic_partition, partition)| PartitionOffsets {
            topic: topic_partition.topic.clone(),
            partition: topic_partition.partition,
            ranges: vec![(partition.span.first, partition.span.last)],
        })
        .collect()
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
