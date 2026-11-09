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

    fn admitted(filter: &mut RedeliveryFilter, deliveries: &[(i32, i64)]) -> Vec<bool> {
        deliveries
            .iter()
            .map(|&(partition, offset)| filter.admit(Partition(partition), Offset(offset)))
            .collect()
    }

    #[test]
    fn a_partitions_first_offset_is_admitted() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(admitted(&mut filter, &[(0, 5)]), [true]);
    }

    #[test]
    fn consecutive_offsets_are_admitted() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(
            admitted(&mut filter, &[(0, 5), (0, 6), (0, 7)]),
            [true, true, true]
        );
    }

    #[test]
    fn a_repeat_of_the_last_offset_is_dropped() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(admitted(&mut filter, &[(0, 5), (0, 5)]), [true, false]);
    }

    #[test]
    fn every_further_repeat_of_the_last_offset_is_dropped() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(
            admitted(&mut filter, &[(0, 5), (0, 5), (0, 5)]),
            [true, false, false]
        );
    }

    #[test]
    fn the_offset_after_a_dropped_repeat_is_admitted() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(
            admitted(&mut filter, &[(0, 5), (0, 5), (0, 6)]),
            [true, false, true]
        );
    }

    #[test]
    fn an_offset_below_the_last_passes_to_the_ledger() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(
            admitted(&mut filter, &[(0, 5), (0, 6), (0, 5)]),
            [true, true, true]
        );
    }

    #[test]
    fn an_offset_gap_is_admitted() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(admitted(&mut filter, &[(0, 5), (0, 9)]), [true, true]);
    }

    #[test]
    fn partitions_are_filtered_independently() {
        let mut filter = RedeliveryFilter::default();
        assert_eq!(
            admitted(&mut filter, &[(0, 5), (1, 5), (1, 5), (0, 5)]),
            [true, true, false, false]
        );
    }

    #[test]
    fn a_forgotten_partition_admits_its_last_offset_again() {
        let mut filter = RedeliveryFilter::default();
        admitted(&mut filter, &[(0, 5)]);
        filter.forget(Partition(0));
        assert_eq!(admitted(&mut filter, &[(0, 5)]), [true]);
    }

    #[test]
    fn forgetting_a_partition_keeps_the_others() {
        let mut filter = RedeliveryFilter::default();
        admitted(&mut filter, &[(0, 5), (1, 7)]);
        filter.forget(Partition(0));
        assert_eq!(admitted(&mut filter, &[(0, 5), (1, 7)]), [true, false]);
    }

    #[test]
    fn forgetting_an_unknown_partition_changes_nothing() {
        let mut filter = RedeliveryFilter::default();
        admitted(&mut filter, &[(0, 5)]);
        filter.forget(Partition(3));
        assert_eq!(admitted(&mut filter, &[(0, 5)]), [false]);
    }
}
