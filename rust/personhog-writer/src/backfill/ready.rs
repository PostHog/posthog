//! The check before the snapshot: a record the writer applies to Postgres after the snapshot and
//! the backfill group never reads would reach neither store. Once the writer group's commits have
//! passed the backfill group's start on every partition, no such record exists.

use std::collections::HashMap;
use std::time::Duration;

use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::error::KafkaError;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};

const TIMEOUT: Duration = Duration::from_secs(10);

/// A group's committed offsets on the changelog; partitions without a commit are absent.
pub fn committed_offsets(
    base: &ClientConfig,
    group: &str,
    topic: &str,
    partitions: u32,
) -> Result<HashMap<i32, i64>, KafkaError> {
    let consumer: BaseConsumer = base
        .clone()
        .set("group.id", group)
        .set("enable.auto.commit", "false")
        .create()?;
    let mut tpl = TopicPartitionList::new();
    for partition in 0..partitions as i32 {
        tpl.add_partition(topic, partition);
    }
    Ok(consumer
        .committed_offsets(tpl, TIMEOUT)?
        .elements()
        .iter()
        .filter_map(|e| match e.offset() {
            Offset::Offset(offset) => Some((e.partition(), offset)),
            _ => None,
        })
        .collect())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NotReady {
    pub partition: i32,
    pub writer: Option<i64>,
    pub backfill: Option<i64>,
}

/// The partitions where the writer group's commit has not reached the backfill group's start.
pub fn not_ready(
    writer: &HashMap<i32, i64>,
    backfill: &HashMap<i32, i64>,
    partitions: u32,
) -> Vec<NotReady> {
    (0..partitions as i32)
        .filter_map(|partition| {
            let (writer, backfill) = (
                writer.get(&partition).copied(),
                backfill.get(&partition).copied(),
            );
            match (writer, backfill) {
                (Some(writer), Some(backfill)) if writer >= backfill => None,
                _ => Some(NotReady {
                    partition,
                    writer,
                    backfill,
                }),
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_partition_is_ready_once_the_writer_commits_past_the_backfill_start() {
        let writer = HashMap::from([(0, 10), (1, 4), (2, 7)]);
        let backfill = HashMap::from([(0, 10), (1, 5), (3, 1)]);

        assert_eq!(
            not_ready(&writer, &backfill, 4),
            vec![
                NotReady {
                    partition: 1,
                    writer: Some(4),
                    backfill: Some(5)
                },
                NotReady {
                    partition: 2,
                    writer: Some(7),
                    backfill: None
                },
                NotReady {
                    partition: 3,
                    writer: None,
                    backfill: Some(1)
                },
            ]
        );
    }
}
