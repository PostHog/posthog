use std::collections::HashMap;

use common_kafka_consumer::{Offset, Partition};

/// librdkafka can repeat a partition's last message; see the README, "Polling".
#[derive(Default)]
pub(super) struct RedeliveryFilter {
    last_offsets: HashMap<Partition, Offset>,
}

impl RedeliveryFilter {
    pub(super) fn admit(&mut self, partition: Partition, offset: Offset) -> bool {
        self.last_offsets.insert(partition, offset) != Some(offset)
    }

    pub(super) fn forget(&mut self, partition: Partition) {
        self.last_offsets.remove(&partition);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_an_exact_repeat_of_the_partitions_last_offset_is_dropped() {
        let mut filter = RedeliveryFilter::default();
        let admitted: Vec<bool> = [(0, 5), (0, 5), (1, 5), (0, 6), (0, 5), (0, 7), (0, 7)]
            .into_iter()
            .map(|(partition, offset)| filter.admit(Partition(partition), Offset(offset)))
            .collect();

        assert_eq!(
            admitted,
            [true, false, true, true, true, true, false],
            "the out-of-order 5 after 6 passes to the ledger"
        );
    }
}
