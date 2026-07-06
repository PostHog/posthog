use std::collections::hash_map::Entry;
use std::collections::HashMap;

use crate::types::TupleKey;

pub struct Aggregator {
    counts: HashMap<TupleKey, u64>,
    approx_bytes: usize,
}

impl Aggregator {
    pub fn new() -> Self {
        Self {
            counts: HashMap::new(),
            approx_bytes: 0,
        }
    }

    pub fn add(&mut self, tuple: TupleKey, count: u64) {
        let tuple_bytes = tuple.approx_bytes();
        match self.counts.entry(tuple) {
            Entry::Occupied(mut entry) => *entry.get_mut() += count,
            Entry::Vacant(entry) => {
                self.approx_bytes += tuple_bytes;
                entry.insert(count);
            }
        }
    }

    pub fn len(&self) -> usize {
        self.counts.len()
    }

    pub fn approx_bytes(&self) -> usize {
        self.approx_bytes
    }

    pub fn is_empty(&self) -> bool {
        self.counts.is_empty()
    }

    pub fn drain(&mut self) -> HashMap<TupleKey, u64> {
        self.approx_bytes = 0;
        std::mem::take(&mut self.counts)
    }
}

impl Default for Aggregator {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::PropertyType;
    use proptest::prelude::*;

    fn tuple(team: i64, key: &str, value: &str) -> TupleKey {
        TupleKey {
            team_id: team,
            property_type: PropertyType::Event,
            property_key: key.to_string(),
            property_value: value.to_string(),
        }
    }

    fn arb_property_type() -> impl Strategy<Value = PropertyType> {
        prop_oneof![
            Just(PropertyType::Event),
            Just(PropertyType::Person),
            (0u8..=10).prop_map(PropertyType::Group),
        ]
    }

    prop_compose! {
        fn arb_tuple()(
            team_id in -5i64..=5,
            property_type in arb_property_type(),
            property_key in "[a-c]{1,3}",
            property_value in "[x-z]{1,3}",
        ) -> TupleKey {
            TupleKey { team_id, property_type, property_key, property_value }
        }
    }

    proptest! {
        #[test]
        fn drained_counts_equal_per_tuple_sum(
            ops in prop::collection::vec((arb_tuple(), 1u64..1_000), 0..200),
        ) {
            let mut agg = Aggregator::new();
            let mut expected: HashMap<TupleKey, u64> = HashMap::new();

            for (t, n) in &ops {
                agg.add(t.clone(), *n);
                *expected.entry(t.clone()).or_insert(0) += *n;
            }

            prop_assert_eq!(agg.drain(), expected);
        }
    }

    #[test]
    fn drain_clears_state() {
        let mut agg = Aggregator::new();
        agg.add(tuple(2, "$browser", "Chrome"), 1);

        let first = agg.drain();
        assert_eq!(first.len(), 1);
        assert!(agg.is_empty());

        let second = agg.drain();
        assert!(second.is_empty());
    }

    #[test]
    fn approx_bytes_counts_distinct_keys_only() {
        let mut agg = Aggregator::new();
        assert_eq!(agg.approx_bytes(), 0);

        agg.add(tuple(2, "$browser", "Chrome"), 1);
        let one_key = agg.approx_bytes();
        assert_eq!(one_key, tuple(2, "$browser", "Chrome").approx_bytes());

        agg.add(tuple(2, "$browser", "Chrome"), 5);
        assert_eq!(agg.approx_bytes(), one_key);

        agg.add(tuple(2, "$browser", "Firefox"), 1);
        assert!(agg.approx_bytes() > one_key);

        agg.drain();
        assert_eq!(agg.approx_bytes(), 0);
    }
}
