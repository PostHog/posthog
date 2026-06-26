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
