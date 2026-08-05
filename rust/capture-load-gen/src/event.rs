use std::collections::HashMap;

use common_types::RawEvent;
use rand::Rng;
use serde::Serialize;
use serde_json::Value;
use uuid::Uuid;

/// Generates synthetic [`RawEvent`]s shaped like real capture traffic.
///
/// Distinct IDs are drawn from a fixed pool so person cardinality is
/// controllable, and each event is padded with filler properties to roughly
/// match a target serialized size.
pub struct EventFactory {
    distinct_ids: Vec<String>,
    event_names: Vec<String>,
    filler: String,
}

impl EventFactory {
    pub fn new(distinct_ids: u64, event_names: Vec<String>, prop_bytes: usize) -> Self {
        let distinct_ids = (0..distinct_ids.max(1))
            .map(|i| format!("loadgen-user-{i}"))
            .collect();
        Self {
            distinct_ids,
            event_names,
            filler: "x".repeat(prop_bytes),
        }
    }

    fn next(&self, rng: &mut impl Rng) -> RawEvent {
        let distinct_id = &self.distinct_ids[rng.gen_range(0..self.distinct_ids.len())];
        let event = &self.event_names[rng.gen_range(0..self.event_names.len())];

        let mut properties: HashMap<String, Value> = HashMap::new();
        properties.insert("$lib".to_string(), Value::String("capture-load-gen".into()));
        if !self.filler.is_empty() {
            properties.insert("filler".to_string(), Value::String(self.filler.clone()));
        }

        RawEvent {
            event: event.clone(),
            distinct_id: Some(Value::String(distinct_id.clone())),
            uuid: Some(Uuid::now_v7()),
            properties,
            ..Default::default()
        }
    }

    /// Build a batch of `size` events.
    pub fn batch(&self, size: usize, rng: &mut impl Rng) -> Vec<RawEvent> {
        (0..size).map(|_| self.next(rng)).collect()
    }
}

/// Body of a POST to `/batch`. Capture accepts `api_key` as an alias for the
/// project token at the batch level, with the events under `batch`.
#[derive(Serialize)]
pub struct BatchPayload<'a> {
    pub api_key: &'a str,
    pub batch: &'a [RawEvent],
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::rngs::StdRng;
    use rand::SeedableRng;

    fn factory() -> EventFactory {
        EventFactory::new(100, vec!["a".into(), "b".into()], 32)
    }

    #[test]
    fn batch_has_requested_size_and_shape() {
        let f = factory();
        let mut rng = StdRng::seed_from_u64(1);
        let batch = f.batch(10, &mut rng);

        assert_eq!(batch.len(), 10);
        for event in &batch {
            assert!(["a", "b"].contains(&event.event.as_str()));
            let distinct_id = event.distinct_id.as_ref().unwrap().as_str().unwrap();
            assert!(distinct_id.starts_with("loadgen-user-"));
            assert_eq!(event.properties["filler"].as_str().unwrap().len(), 32);
            assert_eq!(
                event.properties["$lib"],
                Value::String("capture-load-gen".into())
            );
        }
    }

    #[test]
    fn uuids_are_unique_within_a_batch() {
        let f = factory();
        let mut rng = StdRng::seed_from_u64(2);
        let batch = f.batch(50, &mut rng);

        let mut ids: Vec<_> = batch.iter().map(|e| e.uuid.unwrap()).collect();
        ids.sort();
        ids.dedup();
        assert_eq!(
            ids.len(),
            50,
            "every generated event should have a unique uuid"
        );
    }

    #[test]
    fn zero_prop_bytes_omits_filler() {
        let f = EventFactory::new(10, vec!["x".into()], 0);
        let mut rng = StdRng::seed_from_u64(3);
        let batch = f.batch(1, &mut rng);
        assert!(!batch[0].properties.contains_key("filler"));
    }
}
