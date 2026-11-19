use std::collections::HashMap;

use common_kafka_consumer::{Charge, Offset, TopicPartition};

use crate::debug_recorder::{PartitionOffset, PartitionOffsets};
use crate::order_sentinel::OffsetSpan;
use crate::types::Accumulator;

#[derive(Default)]
pub(crate) struct BatchStats {
    /// One (partition, lag in ms) pair per message with a parseable `now` header.
    pub(crate) message_lags_ms: Vec<(i32, i64)>,
    /// Sum of message payload sizes, without keys or headers.
    pub(crate) total_bytes: usize,
}

pub(crate) struct Delivery {
    pub(crate) offset: i64,
    pub(crate) charge: Charge,
    pub(crate) payload_bytes: usize,
    /// Kafka message timestamp (ms).
    pub(crate) kafka_ts: i64,
    /// Ingestion lag (ms); `None` without a parseable `now` header.
    pub(crate) lag_ms: Option<i64>,
}

pub(crate) struct PartitionDeliveries {
    /// The first and last delivered offsets. A compacted or transactional topic
    /// can skip offsets between them.
    pub(crate) span: OffsetSpan,
    /// The ledger generation, set when the poll is charged.
    pub(crate) generation: u64,
    pub(crate) charges: Vec<(Offset, Charge)>,
    pub(crate) payload_bytes: usize,
    /// Max Kafka message timestamp (ms).
    pub(crate) latest_kafka_ts: i64,
    pub(crate) max_lag_ms: Option<i64>,
    pub(crate) delivered: u32,
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
        }
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
}

pub(crate) struct CollectedBatch {
    pub(crate) accumulator: Accumulator,
    pub(crate) partitions: HashMap<TopicPartition, PartitionDeliveries>,
    pub(crate) stats: BatchStats,
}

pub(crate) struct InFlightPoll {
    pub(crate) partitions: HashMap<TopicPartition, PartitionDeliveries>,
    pub(crate) uncommitted: HashMap<TopicPartition, Charge>,
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
