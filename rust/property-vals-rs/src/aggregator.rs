use std::collections::HashMap;

use crate::types::TupleKey;

pub struct Aggregator {
    counts: HashMap<TupleKey, u64>,
}

impl Aggregator {
    pub fn new() -> Self {
        Self {
            counts: HashMap::new(),
        }
    }

    pub fn add(&mut self, tuple: TupleKey, count: u64) {
        *self.counts.entry(tuple).or_insert(0) += count;
    }

    pub fn len(&self) -> usize {
        self.counts.len()
    }

    pub fn is_empty(&self) -> bool {
        self.counts.is_empty()
    }

    pub fn drain(&mut self) -> HashMap<TupleKey, u64> {
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

    fn tuple(team: i64, key: &str, value: &str) -> TupleKey {
        TupleKey {
            team_id: team,
            property_type: PropertyType::Event,
            property_key: key.to_string(),
            property_value: value.to_string(),
        }
    }

    #[test]
    fn add_accumulates_counts_for_same_tuple() {
        let mut agg = Aggregator::new();
        agg.add(tuple(2, "$lib", "web"), 3);
        agg.add(tuple(2, "$lib", "web"), 5);
        agg.add(tuple(2, "$os", "mac"), 2);

        let drained = agg.drain();
        assert_eq!(drained.len(), 2);
        assert_eq!(drained[&tuple(2, "$lib", "web")], 8);
        assert_eq!(drained[&tuple(2, "$os", "mac")], 2);
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
}
