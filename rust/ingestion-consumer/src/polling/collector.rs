use std::time::Duration;

use common_kafka_consumer::TopicPartition;
use metrics::counter;
use rdkafka::message::Message;
use tokio::time::Instant;

use super::poll::{CollectedBatch, PollBuilder};

#[derive(Debug, Clone, Copy)]
pub(crate) struct PollLimits {
    pub(crate) batch_size: usize,
    /// Payload-byte bound; `0` disables it.
    pub(crate) batch_size_bytes: usize,
    pub(crate) batch_timeout: Duration,
}

pub(crate) struct Collector {
    limits: PollLimits,
    poll: Option<PollBuilder>,
    deadline: Option<Instant>,
}

impl Collector {
    pub(crate) fn new(limits: PollLimits) -> Self {
        Self {
            limits,
            poll: None,
            deadline: None,
        }
    }

    /// The first message of a poll starts its batch timeout.
    pub(crate) fn add(&mut self, message: &impl Message, now: Instant) {
        if self.poll.is_none() {
            self.poll = Some(PollBuilder::new());
            self.deadline = Some(now + self.limits.batch_timeout);
        }
        self.poll.as_mut().expect("started above").add(message);
    }

    pub(crate) fn deadline(&self) -> Option<Instant> {
        self.deadline
    }

    pub(crate) fn take_ready(&mut self, now: Instant) -> Option<CollectedBatch> {
        let poll = self.poll.as_ref()?;
        let timed_out = self.deadline.is_some_and(|deadline| deadline <= now);
        if !timed_out && !self.is_full(poll) {
            return None;
        }
        self.deadline = None;
        self.poll.take().map(PollBuilder::finish)
    }

    /// Returns the messages removed.
    pub(crate) fn remove_partitions(&mut self, topic_partitions: &[TopicPartition]) -> usize {
        let Some(poll) = self.poll.as_mut() else {
            return 0;
        };
        let removed = topic_partitions
            .iter()
            .map(|topic_partition| poll.remove_partition(topic_partition))
            .sum();
        if poll.message_count() == 0 {
            self.discard();
        }
        removed
    }

    pub(crate) fn discard(&mut self) {
        self.poll = None;
        self.deadline = None;
    }

    /// The byte bound counts only messages already added, so a poll always
    /// carries one message, even one larger than the bound. The overshoot is
    /// at most one message, which `fetch.message.max.bytes` bounds.
    fn is_full(&self, poll: &PollBuilder) -> bool {
        if poll.message_count() >= self.limits.batch_size {
            return true;
        }
        if self.limits.batch_size_bytes > 0 && poll.payload_bytes() >= self.limits.batch_size_bytes
        {
            counter!("ingestion_consumer_batches_byte_capped_total").increment(1);
            return true;
        }
        false
    }
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
