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
/// match a target serialized size. A configurable share of events exercises
/// the person pipeline: person updates carry a `$set` payload, merges are
/// `$identify` events claiming a fresh anonymous distinct id.
pub struct EventFactory {
    distinct_ids: Vec<String>,
    event_names: Vec<String>,
    filler: String,
    person_update_pct: u8,
    merge_pct: u8,
}

impl EventFactory {
    pub fn new(
        distinct_ids: u64,
        event_names: Vec<String>,
        prop_bytes: usize,
        person_update_pct: u8,
        merge_pct: u8,
    ) -> Self {
        let distinct_ids = (0..distinct_ids.max(1))
            .map(|i| format!("loadgen-user-{i}"))
            .collect();
        Self {
            distinct_ids,
            event_names,
            filler: "x".repeat(prop_bytes),
            person_update_pct,
            merge_pct,
        }
    }

    fn next(&self, rng: &mut impl Rng) -> RawEvent {
        let distinct_id = &self.distinct_ids[rng.gen_range(0..self.distinct_ids.len())];

        let mut properties: HashMap<String, Value> = HashMap::new();
        properties.insert("$lib".to_string(), Value::String("capture-load-gen".into()));
        if !self.filler.is_empty() {
            properties.insert("filler".to_string(), Value::String(self.filler.clone()));
        }

        let base = RawEvent {
            distinct_id: Some(Value::String(distinct_id.clone())),
            uuid: Some(Uuid::now_v7()),
            properties,
            ..Default::default()
        };

        let roll = rng.gen_range(0..100u8);
        if roll < self.merge_pct {
            return self.merge_event(base);
        }
        let event = self.event_names[rng.gen_range(0..self.event_names.len())].clone();
        if roll < self.merge_pct + self.person_update_pct {
            return Self::person_update_event(base, event);
        }
        RawEvent { event, ..base }
    }

    /// A merge: `$identify` folding a fresh anonymous distinct id into the
    /// pool user. The anon id is unique per event so every merge exercises
    /// the merge path instead of re-merging an already-folded pair.
    fn merge_event(&self, mut base: RawEvent) -> RawEvent {
        base.properties.insert(
            "$anon_distinct_id".to_string(),
            Value::String(format!("loadgen-anon-{}", Uuid::now_v7())),
        );
        RawEvent {
            event: "$identify".to_string(),
            ..base
        }
    }

    /// A person update: a regular event carrying a `$set` payload. The value
    /// is unique per event so every update actually changes the person.
    fn person_update_event(base: RawEvent, event: String) -> RawEvent {
        let mut set = HashMap::new();
        set.insert(
            "loadgen_last_update".to_string(),
            Value::String(Uuid::now_v7().to_string()),
        );
        RawEvent {
            event,
            set: Some(set),
            ..base
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
        EventFactory::new(100, vec!["a".into(), "b".into()], 32, 0, 0)
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
        let f = EventFactory::new(10, vec!["x".into()], 0, 0, 0);
        let mut rng = StdRng::seed_from_u64(3);
        let batch = f.batch(1, &mut rng);
        assert!(!batch[0].properties.contains_key("filler"));
    }

    #[test]
    fn merge_events_are_identifies_with_fresh_anon_ids() {
        let f = EventFactory::new(10, vec!["x".into()], 0, 0, 100);
        let mut rng = StdRng::seed_from_u64(4);
        let batch = f.batch(20, &mut rng);

        let mut anon_ids = Vec::new();
        for event in &batch {
            assert_eq!(event.event, "$identify");
            assert!(event.set.is_none());
            let anon = event.properties["$anon_distinct_id"].as_str().unwrap();
            assert!(anon.starts_with("loadgen-anon-"));
            anon_ids.push(anon.to_string());
            let distinct_id = event.distinct_id.as_ref().unwrap().as_str().unwrap();
            assert!(distinct_id.starts_with("loadgen-user-"));
        }
        anon_ids.sort();
        anon_ids.dedup();
        assert_eq!(
            anon_ids.len(),
            20,
            "every merge should claim a fresh anon id"
        );
    }

    #[test]
    fn person_update_events_carry_a_changing_set_payload() {
        let f = EventFactory::new(10, vec!["a".into(), "b".into()], 0, 100, 0);
        let mut rng = StdRng::seed_from_u64(5);
        let batch = f.batch(20, &mut rng);

        let mut values = Vec::new();
        for event in &batch {
            assert!(["a", "b"].contains(&event.event.as_str()));
            assert!(!event.properties.contains_key("$anon_distinct_id"));
            let set = event.set.as_ref().unwrap();
            values.push(set["loadgen_last_update"].as_str().unwrap().to_string());
        }
        values.sort();
        values.dedup();
        assert_eq!(values.len(), 20, "every update should change the person");
    }

    #[test]
    fn mix_roughly_matches_the_configured_percentages() {
        let f = EventFactory::new(100, vec!["a".into()], 0, 30, 20);
        let mut rng = StdRng::seed_from_u64(6);
        let batch = f.batch(2000, &mut rng);

        let merges = batch.iter().filter(|e| e.event == "$identify").count();
        let updates = batch.iter().filter(|e| e.set.is_some()).count();
        let plain = batch.len() - merges - updates;

        // Percentages are drawn per event; allow ±5 points on 2000 samples.
        assert!((merges as i64 - 400).abs() < 100, "merges: {merges}");
        assert!((updates as i64 - 600).abs() < 100, "updates: {updates}");
        assert!((plain as i64 - 1000).abs() < 100, "plain: {plain}");
    }
}
