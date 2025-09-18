use rdkafka::topic_partition_list::TopicPartitionListElem;

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
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

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PartitionOffset {
    partition: Partition,
    offset: i64,
}

/// Partition with an optional initial offset from Kafka assignment
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PartitionAssignment {
    partition: Partition,
    offset: Option<i64>, // The offset Kafka tells us to start from
}

impl From<TopicPartitionListElem<'_>> for Partition {
    fn from(elem: TopicPartitionListElem<'_>) -> Self {
        Self::new(elem.topic().to_string(), elem.partition())
    }
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

impl PartitionAssignment {
    pub fn new(partition: Partition, offset: Option<i64>) -> Self {
        Self { partition, offset }
    }

    pub fn partition(&self) -> &Partition {
        &self.partition
    }

    pub fn topic(&self) -> &str {
        self.partition.topic()
    }

    pub fn partition_number(&self) -> i32 {
        self.partition.partition_number()
    }

    pub fn offset(&self) -> Option<i64> {
        self.offset
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum PartitionState {
    Active,  // Normal processing
    Fenced,  // Temporarily stopped (pending revocation)
    Revoked, // Fully revoked, awaiting reassignment
}
