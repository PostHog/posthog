use std::collections::HashMap;

use crate::types::TupleKey;

/// In-memory accumulator for one Kafka partition's worth of tuples. Inserts
/// increment the per-tuple count; `drain` returns the accumulated map and
/// clears state in one shot so the next flush window starts fresh.
pub struct Aggregator {
    counts: HashMap<TupleKey, u64>,
}

impl Aggregator {
    pub fn new() -> Self {
        Self {
            counts: HashMap::new(),
        }
    }

    pub fn record(&mut self, tuple: TupleKey) {
        *self.counts.entry(tuple).or_insert(0) += 1;
    }

    pub fn record_many<I: IntoIterator<Item = TupleKey>>(&mut self, tuples: I) {
        for t in tuples {
            self.record(t);
        }
    }

    pub fn len(&self) -> usize {
        self.counts.len()
    }

    pub fn is_empty(&self) -> bool {
        self.counts.is_empty()
    }

    /// Atomically take the accumulated state and reset for the next window.
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
    fn record_increments_count_for_same_tuple() {
        let mut agg = Aggregator::new();
        agg.record(tuple(2, "$browser", "Chrome"));
        agg.record(tuple(2, "$browser", "Chrome"));
        agg.record(tuple(2, "$browser", "Chrome"));

        let drained = agg.drain();
        assert_eq!(drained.len(), 1);
        assert_eq!(drained[&tuple(2, "$browser", "Chrome")], 3);
    }

    #[test]
    fn distinct_tuples_have_independent_counts() {
        let mut agg = Aggregator::new();
        agg.record(tuple(2, "$browser", "Chrome"));
        agg.record(tuple(2, "$browser", "Chrome"));
        agg.record(tuple(2, "$browser", "Firefox"));
        agg.record(tuple(3, "$browser", "Chrome"));

        let drained = agg.drain();
        assert_eq!(drained.len(), 3);
        assert_eq!(drained[&tuple(2, "$browser", "Chrome")], 2);
        assert_eq!(drained[&tuple(2, "$browser", "Firefox")], 1);
        assert_eq!(drained[&tuple(3, "$browser", "Chrome")], 1);
    }

    #[test]
    fn drain_clears_state() {
        let mut agg = Aggregator::new();
        agg.record(tuple(2, "$browser", "Chrome"));

        let first = agg.drain();
        assert_eq!(first.len(), 1);
        assert!(agg.is_empty());

        let second = agg.drain();
        assert!(second.is_empty());
    }

    #[test]
    fn record_many_accepts_iterator() {
        let mut agg = Aggregator::new();
        agg.record_many(vec![
            tuple(2, "$browser", "Chrome"),
            tuple(2, "$browser", "Chrome"),
            tuple(2, "$os", "Linux"),
        ]);

        let drained = agg.drain();
        assert_eq!(drained.len(), 2);
        assert_eq!(drained[&tuple(2, "$browser", "Chrome")], 2);
        assert_eq!(drained[&tuple(2, "$os", "Linux")], 1);
    }
}
