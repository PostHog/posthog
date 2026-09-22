use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use common_types::RawEvent;
use rand::Rng;
use serde::Serialize;
use serde_json::Value;
use uuid::Uuid;

/// Share of events, in percent, spent on each kind of person-pipeline work.
#[derive(Clone, Copy, Debug, Default)]
pub struct TrafficMix {
    /// Regular events carrying a `$set` payload.
    pub person_updates: u8,
    /// `$identify` claiming a fresh anonymous id, which attaches the id to the pool user.
    pub attaches: u8,
    /// `$identify` claiming an anonymous id that has a person, which merges two persons.
    pub person_merges: u8,
    /// `$merge_dangerously` between a pool user and its partner.
    pub dangerous_merges: u8,
}

impl TrafficMix {
    pub fn total(&self) -> u16 {
        [
            self.person_updates,
            self.attaches,
            self.person_merges,
            self.dangerous_merges,
        ]
        .into_iter()
        .map(u16::from)
        .sum()
    }
}

/// Generates synthetic [`RawEvent`]s shaped like real capture traffic.
///
/// Distinct IDs are drawn from a fixed pool so person cardinality is
/// controllable, and each event is padded with filler properties to roughly
/// match a target serialized size. A configurable share of events exercises
/// the person pipeline; see [`TrafficMix`].
pub struct EventFactory {
    distinct_ids: Vec<String>,
    event_names: Vec<String>,
    filler: String,
    mix: TrafficMix,
    person_merge_delay: Duration,
    /// Anonymous ids that sent an event of their own, oldest first, awaiting their `$identify`.
    seeded_anon_ids: Mutex<VecDeque<(String, Instant)>>,
}

fn fresh_anon_id() -> String {
    format!("loadgen-anon-{}", Uuid::now_v7())
}

impl EventFactory {
    pub fn new(
        distinct_ids: u64,
        event_names: Vec<String>,
        prop_bytes: usize,
        mix: TrafficMix,
        person_merge_delay: Duration,
    ) -> Self {
        let distinct_ids = (0..distinct_ids.max(1))
            .map(|i| format!("loadgen-user-{i}"))
            .collect();
        Self {
            distinct_ids,
            event_names,
            filler: "x".repeat(prop_bytes),
            mix,
            person_merge_delay,
            seeded_anon_ids: Mutex::new(VecDeque::new()),
        }
    }

    fn base_event(&self, distinct_id: &str) -> RawEvent {
        let mut properties: HashMap<String, Value> = HashMap::new();
        properties.insert("$lib".to_string(), Value::String("capture-load-gen".into()));
        if !self.filler.is_empty() {
            properties.insert("filler".to_string(), Value::String(self.filler.clone()));
        }

        RawEvent {
            distinct_id: Some(Value::String(distinct_id.to_string())),
            uuid: Some(Uuid::now_v7()),
            properties,
            ..Default::default()
        }
    }

    fn random_event_name(&self, rng: &mut impl Rng) -> String {
        self.event_names[rng.gen_range(0..self.event_names.len())].clone()
    }

    fn next(&self, rng: &mut impl Rng) -> RawEvent {
        let index = rng.gen_range(0..self.distinct_ids.len());
        let base = self.base_event(&self.distinct_ids[index]);

        let roll = u16::from(rng.gen_range(0..100u8));
        let mut share = u16::from(self.mix.attaches);
        if roll < share {
            return Self::identify_event(base, fresh_anon_id());
        }
        share += u16::from(self.mix.person_merges);
        if roll < share {
            return self.person_merge_event(base, rng);
        }
        share += u16::from(self.mix.dangerous_merges);
        if roll < share {
            // Fixed pairs bound a person to two pool users. Only the even user
            // merges, so the pair has one survivor on every backend.
            let pairs = self.distinct_ids.len() / 2;
            if pairs == 0 {
                return RawEvent {
                    event: self.random_event_name(rng),
                    ..base
                };
            }
            let even = 2 * rng.gen_range(0..pairs);
            let sender = self.base_event(&self.distinct_ids[even]);
            return Self::dangerous_merge_event(sender, &self.distinct_ids[even + 1]);
        }
        let event = self.random_event_name(rng);
        share += u16::from(self.mix.person_updates);
        if roll < share {
            return Self::person_update_event(base, event);
        }
        RawEvent { event, ..base }
    }

    /// `$identify` folding an anonymous distinct id into the pool user. An id with no
    /// person only attaches; one that sent its own event first merges two persons.
    fn identify_event(mut base: RawEvent, anon_id: String) -> RawEvent {
        base.properties
            .insert("$anon_distinct_id".to_string(), Value::String(anon_id));
        RawEvent {
            event: "$identify".to_string(),
            ..base
        }
    }

    /// One of the two events a person merge takes: the seed gives a fresh anonymous id
    /// a person, and the claim is the `$identify` for the oldest id that waited out the delay.
    fn person_merge_event(&self, base: RawEvent, rng: &mut impl Rng) -> RawEvent {
        let seed_id = {
            let mut seeded = self
                .seeded_anon_ids
                .lock()
                .expect("seeded anon ids lock poisoned");
            let ripe = seeded
                .front()
                .is_some_and(|(_, seeded_at)| seeded_at.elapsed() >= self.person_merge_delay);
            if let Some((anon_id, _)) = ripe.then(|| seeded.pop_front()).flatten() {
                return Self::identify_event(base, anon_id);
            }
            let anon_id = fresh_anon_id();
            seeded.push_back((anon_id.clone(), Instant::now()));
            anon_id
        };
        // The shared key is contested between the seed and the survivor; the
        // per-id key has one writer and names which seeds reached the person.
        let seed_value = Uuid::now_v7().to_string();
        let mut set = HashMap::new();
        set.insert(
            "loadgen_anon_seed".to_string(),
            Value::String(seed_value.clone()),
        );
        set.insert(
            format!("loadgen_anon_seed_{seed_id}"),
            Value::String(seed_value),
        );
        RawEvent {
            event: self.random_event_name(rng),
            set: Some(set),
            ..self.base_event(&seed_id)
        }
    }

    /// The `$identify` for every id still seeded, and how long until the youngest has
    /// waited out the delay, so a run can finish the person merges it started.
    pub fn drain_person_merges(&self, rng: &mut impl Rng) -> (Vec<RawEvent>, Duration) {
        let seeded = std::mem::take(
            &mut *self
                .seeded_anon_ids
                .lock()
                .expect("seeded anon ids lock poisoned"),
        );
        let wait = seeded.back().map_or(Duration::ZERO, |(_, seeded_at)| {
            self.person_merge_delay.saturating_sub(seeded_at.elapsed())
        });
        let claims = seeded
            .into_iter()
            .map(|(anon_id, _)| {
                let index = rng.gen_range(0..self.distinct_ids.len());
                Self::identify_event(self.base_event(&self.distinct_ids[index]), anon_id)
            })
            .collect();
        (claims, wait)
    }

    /// `$merge_dangerously` folding the partner's person into the pool user's, identified or not.
    fn dangerous_merge_event(mut base: RawEvent, partner: &str) -> RawEvent {
        base.properties
            .insert("alias".to_string(), Value::String(partner.to_string()));
        RawEvent {
            event: "$merge_dangerously".to_string(),
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
        EventFactory::new(
            100,
            vec!["a".into(), "b".into()],
            32,
            TrafficMix::default(),
            Duration::ZERO,
        )
    }

    fn factory_with(pool: u64, mix: TrafficMix, person_merge_delay: Duration) -> EventFactory {
        EventFactory::new(
            pool,
            vec!["a".into(), "b".into()],
            0,
            mix,
            person_merge_delay,
        )
    }

    fn distinct_id(event: &RawEvent) -> &str {
        event.distinct_id.as_ref().unwrap().as_str().unwrap()
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
        let f = EventFactory::new(
            10,
            vec!["x".into()],
            0,
            TrafficMix::default(),
            Duration::ZERO,
        );
        let mut rng = StdRng::seed_from_u64(3);
        let batch = f.batch(1, &mut rng);
        assert!(!batch[0].properties.contains_key("filler"));
    }

    #[test]
    fn attach_events_are_identifies_with_fresh_anon_ids() {
        let mix = TrafficMix {
            attaches: 100,
            ..Default::default()
        };
        let f = factory_with(10, mix, Duration::ZERO);
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
            "every attach should claim a fresh anon id"
        );
    }

    #[test]
    fn person_update_events_carry_a_changing_set_payload() {
        let mix = TrafficMix {
            person_updates: 100,
            ..Default::default()
        };
        let f = factory_with(10, mix, Duration::ZERO);
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
        let mix = TrafficMix {
            person_updates: 30,
            attaches: 20,
            person_merges: 10,
            dangerous_merges: 10,
        };
        // The delay outlasts the test, so every person merge is a seed and none an `$identify`.
        let f = factory_with(100, mix, Duration::from_secs(3600));
        let mut rng = StdRng::seed_from_u64(6);
        let batch = f.batch(2000, &mut rng);

        let count =
            |matches: &dyn Fn(&RawEvent) -> bool| batch.iter().filter(|e| matches(e)).count();
        let attaches = count(&|e| e.event == "$identify");
        let seeds = count(&|e| distinct_id(e).starts_with("loadgen-anon-"));
        let dangerous = count(&|e| e.event == "$merge_dangerously");
        let updates = count(&|e| e.set.is_some()) - seeds;
        let plain = batch.len() - attaches - seeds - dangerous - updates;

        // Percentages are drawn per event; allow ±5 points on 2000 samples.
        assert!((attaches as i64 - 400).abs() < 100, "attaches: {attaches}");
        assert!((seeds as i64 - 200).abs() < 100, "seeds: {seeds}");
        assert!(
            (dangerous as i64 - 200).abs() < 100,
            "dangerous: {dangerous}"
        );
        assert!((updates as i64 - 600).abs() < 100, "updates: {updates}");
        assert!((plain as i64 - 600).abs() < 100, "plain: {plain}");
    }

    #[test]
    fn a_person_merge_seeds_an_anonymous_person_then_claims_it() {
        let mix = TrafficMix {
            person_merges: 100,
            ..Default::default()
        };
        let f = factory_with(10, mix, Duration::ZERO);
        let mut rng = StdRng::seed_from_u64(7);
        let batch = f.batch(2, &mut rng);

        let (seed, claim) = (&batch[0], &batch[1]);
        assert!(distinct_id(seed).starts_with("loadgen-anon-"));
        assert_ne!(seed.event, "$identify");
        let seed_set = seed.set.as_ref().unwrap();
        assert!(seed_set.contains_key("loadgen_anon_seed"));
        assert_eq!(
            seed_set[&format!("loadgen_anon_seed_{}", distinct_id(seed))],
            seed_set["loadgen_anon_seed"]
        );

        assert_eq!(claim.event, "$identify");
        assert!(distinct_id(claim).starts_with("loadgen-user-"));
        assert_eq!(
            claim.properties["$anon_distinct_id"].as_str().unwrap(),
            distinct_id(seed)
        );
    }

    #[test]
    fn a_seeded_id_is_not_claimed_before_its_delay() {
        let mix = TrafficMix {
            person_merges: 100,
            ..Default::default()
        };
        let f = factory_with(10, mix, Duration::from_secs(3600));
        let mut rng = StdRng::seed_from_u64(8);
        let batch = f.batch(5, &mut rng);

        assert!(batch.iter().all(|e| e.event != "$identify"));
    }

    #[test]
    fn draining_claims_every_seeded_id_once() {
        let mix = TrafficMix {
            person_merges: 100,
            ..Default::default()
        };
        let delay = Duration::from_secs(3600);
        let f = factory_with(10, mix, delay);
        let mut rng = StdRng::seed_from_u64(11);
        let mut seeded: Vec<String> = f
            .batch(5, &mut rng)
            .iter()
            .map(|e| distinct_id(e).to_string())
            .collect();

        let (claims, wait) = f.drain_person_merges(&mut rng);

        let mut claimed: Vec<String> = claims
            .iter()
            .map(|e| {
                assert_eq!(e.event, "$identify");
                assert!(distinct_id(e).starts_with("loadgen-user-"));
                e.properties["$anon_distinct_id"]
                    .as_str()
                    .unwrap()
                    .to_string()
            })
            .collect();
        seeded.sort();
        claimed.sort();
        assert_eq!(claimed, seeded);
        assert!(wait > Duration::ZERO && wait <= delay, "wait: {wait:?}");

        let (again, no_wait) = f.drain_person_merges(&mut rng);
        assert!(again.is_empty());
        assert_eq!(no_wait, Duration::ZERO);
    }

    #[test]
    fn dangerous_merges_pair_each_user_with_one_partner() {
        let mix = TrafficMix {
            dangerous_merges: 100,
            ..Default::default()
        };
        let f = factory_with(10, mix, Duration::ZERO);
        let mut rng = StdRng::seed_from_u64(9);
        let index = |id: &str| {
            id.strip_prefix("loadgen-user-")
                .unwrap()
                .parse::<u64>()
                .unwrap()
        };

        for event in f.batch(200, &mut rng) {
            assert_eq!(event.event, "$merge_dangerously");
            let sender = index(distinct_id(&event));
            assert_eq!(sender % 2, 0, "only the even user of a pair merges");
            assert_eq!(
                index(event.properties["alias"].as_str().unwrap()),
                sender + 1
            );
        }
    }

    #[test]
    fn a_user_without_a_partner_sends_a_plain_event() {
        let mix = TrafficMix {
            dangerous_merges: 100,
            ..Default::default()
        };
        let f = factory_with(1, mix, Duration::ZERO);
        let mut rng = StdRng::seed_from_u64(10);

        for event in f.batch(5, &mut rng) {
            assert!(["a", "b"].contains(&event.event.as_str()));
            assert!(!event.properties.contains_key("alias"));
        }
    }
}
