use std::fmt::{Display, Formatter, Result};

use rdkafka::topic_partition_list::TopicPartitionListElem;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Hash, Deserialize, Serialize)]
pub struct Partition {
    topic: String,
    partition_number: i32,
}

impl Partition {
    pub fn new(topic: String, partition_number: i32) -> Self {
        Self {
            topic,
            partition_number,
        }
    }

    pub fn topic(&self) -> &str {
        &self.topic
    }

    pub fn partition_number(&self) -> i32 {
        self.partition_number
    }
}

impl Display for Partition {
    fn fmt(&self, f: &mut Formatter) -> Result {
        write!(f, "{}:{}", self.topic, self.partition_number)
    }
}

impl From<TopicPartitionListElem<'_>> for Partition {
    fn from(elem: TopicPartitionListElem<'_>) -> Self {
        Self::new(elem.topic().to_string(), elem.partition())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PartitionOffset {
    partition: Partition,
    offset: i64,
}

impl PartitionOffset {
    pub fn new(partition: Partition, offset: i64) -> Self {
        Self { partition, offset }
    }

    pub fn topic(&self) -> &str {
        self.partition.topic()
    }

    pub fn partition_number(&self) -> i32 {
        self.partition.partition_number()
    }

    pub fn offset(&self) -> i64 {
        self.offset
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum PartitionState {
    Active,  // Normal processing
    Fenced,  // Temporarily stopped (pending revocation)
    Revoked, // Fully revoked, awaiting reassignment
}
