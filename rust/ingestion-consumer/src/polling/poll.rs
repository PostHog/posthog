use std::collections::{HashMap, HashSet};
use std::time::Instant;

use common_kafka_consumer::{Charge, Offset, TopicPartition};

use crate::debug_recorder::{PartitionOffset, PartitionOffsets};
use crate::order_sentinel::OffsetSpan;
use crate::settlement::ChargedSlice;
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
    /// Messages the poll delivered, covered, and accepted from this
    /// partition, so a revoked partition can leave the poll exactly.
    pub(crate) delivered: u32,
    pub(crate) covered: u32,
    pub(crate) accepted: u32,
    /// The offsets that completions covered. Keyed by offset, not by position
    /// in `span`, because `span` can have gaps.
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
}

pub(crate) struct CollectedBatch {
    pub(crate) accumulator: Accumulator,
    pub(crate) partitions: HashMap<TopicPartition, PartitionDeliveries>,
    pub(crate) stats: BatchStats,
}

pub(crate) struct InFlightPoll {
    /// For logs and debug events only.
    pub(crate) poll_id: String,
    /// The epoch the batcher stamped on this poll's completions.
    pub(crate) assignment_epoch: u64,
    pub(crate) partitions: HashMap<TopicPartition, PartitionDeliveries>,
    pub(crate) uncommitted: HashMap<TopicPartition, Charge>,
    pub(crate) message_count: u32,
    /// Messages covered by completions so far, accepted or not.
    pub(crate) covered: u32,
    /// Worker-accepted messages so far.
    pub(crate) accepted: u32,
    pub(crate) dispatched_at: Instant,
}

impl InFlightPoll {
    pub(crate) fn is_complete(&self) -> bool {
        self.covered >= self.message_count
    }

    /// A charged offset that no completion covered. A complete poll can still
    /// have one, because `covered` also counts an offset that is credited twice.
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
