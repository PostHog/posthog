use rand::Rng;
use serde_json::{json, Value};
use uuid::Uuid;

use crate::config::BenchmarkConfig;

/// All generated data needed for the benchmark workload phases.
pub struct PersonRegistry {
    /// (team_id, person_uuid, properties) for each person.
    pub persons: Vec<(i32, Uuid, Value)>,
    /// (team_id, person_uuid, distinct_id) — one entry per distinct_id.
    pub distinct_ids: Vec<(i32, Uuid, String)>,
}

/// Generate a JSONB properties object targeting approximately `target_bytes` total serialized size.
///
/// Uses realistic PostHog person property keys. The last value is padded to hit the target.
pub fn generate_properties(rng: &mut impl Rng, target_bytes: usize) -> Value {
    const KEYS: &[&str] = &[
        "$browser",
        "$os",
        "$initial_referrer",
        "$initial_referring_domain",
        "$geoip_city_name",
        "$geoip_country_code",
        "$geoip_time_zone",
        "email",
        "name",
        "plan",
        "company",
        "role",
        "signup_date",
        "last_login",
    ];

    let mut obj = serde_json::Map::with_capacity(KEYS.len() + 1);

    for &key in KEYS {
        let val_len: usize = rng.gen_range(4..30);
        let val: String = (0..val_len)
            .map(|_| rng.gen_range(b'a'..=b'z') as char)
            .collect();
        obj.insert(key.to_string(), Value::String(val));
    }

    // Measure current size and pad the last property to hit target.
    let current = serde_json::to_string(&Value::Object(obj.clone()))
        .unwrap()
        .len();
    if current < target_bytes {
        let padding_needed = target_bytes - current;
        // Account for the key overhead: `,"_pad":"..."` = key + quotes + colon + comma ~ 10 bytes
        let pad_val_len = padding_needed.saturating_sub(12);
        let pad: String = (0..pad_val_len)
            .map(|_| rng.gen_range(b'a'..=b'z') as char)
            .collect();
        obj.insert("_pad".to_string(), Value::String(pad));
    }

    Value::Object(obj)
}

/// Generate a full person registry from the benchmark config.
///
/// - `scale` persons spread evenly across `teams` teams.
/// - 95% get 1 distinct_id, 5% get 2.
/// - Properties target ~700 bytes each.
pub fn generate_person_registry(config: &BenchmarkConfig, rng: &mut impl Rng) -> PersonRegistry {
    let scale = config.scale as usize;
    let teams = config.teams;

    let mut persons = Vec::with_capacity(scale);
    let mut distinct_ids = Vec::with_capacity((scale as f64 * 1.05) as usize);

    for i in 0..scale {
        let team_id = (i as i32 % teams) + 1;
        let person_uuid = Uuid::new_v4();
        let properties = generate_properties(rng, 700);

        persons.push((team_id, person_uuid, properties));

        // First distinct_id (everyone gets one).
        let did = format!("did_{team_id}_{i}");
        distinct_ids.push((team_id, person_uuid, did));

        // 5% get a second distinct_id.
        if rng.gen_ratio(1, 20) {
            let did2 = format!("did_{team_id}_{i}_alt");
            distinct_ids.push((team_id, person_uuid, did2));
        }
    }

    PersonRegistry {
        persons,
        distinct_ids,
    }
}

/// Minimal properties for property-update workload (avoids allocation overhead
/// from generating full 700-byte objects on every iteration).
pub fn generate_small_properties_update(rng: &mut impl Rng) -> Value {
    let ts: u64 = rng.gen();
    json!({
        "last_seen": ts,
        "$browser": "Chrome",
    })
}
