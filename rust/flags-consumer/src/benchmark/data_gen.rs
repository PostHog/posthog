use std::collections::HashMap;
use std::sync::Arc;

use rand::Rng;
use serde_json::Value;
use uuid::Uuid;

use super::BenchmarkArgs;

pub struct PersonRegistry {
    pub persons: Vec<(i32, Uuid)>,
    pub distinct_ids: Vec<(i32, Uuid, String)>,
}

pub struct BenchmarkData {
    pub persons: Arc<Vec<(i32, Uuid)>>,
    pub distinct_ids: Arc<Vec<(i32, Uuid, String)>>,
    /// team_id -> indices into `distinct_ids` for the first distinct_id per person.
    pub team_person_indices: Arc<HashMap<i32, Vec<usize>>>,
    /// Weighted CDF for team selection: (cumulative_probability, team_id).
    pub team_cdf: Arc<Vec<(f64, i32)>>,
}

pub fn build_benchmark_data(registry: PersonRegistry) -> BenchmarkData {
    let team_person_indices = build_team_person_indices(&registry.distinct_ids);
    let team_cdf = build_team_cdf(&team_person_indices);

    BenchmarkData {
        persons: Arc::new(registry.persons),
        distinct_ids: Arc::new(registry.distinct_ids),
        team_person_indices: Arc::new(team_person_indices),
        team_cdf: Arc::new(team_cdf),
    }
}

fn build_team_person_indices(distinct_ids: &[(i32, Uuid, String)]) -> HashMap<i32, Vec<usize>> {
    let mut seen_persons = std::collections::HashSet::new();
    let mut map: HashMap<i32, Vec<usize>> = HashMap::new();

    for (idx, (team_id, person_uuid, _)) in distinct_ids.iter().enumerate() {
        if seen_persons.insert((*team_id, *person_uuid)) {
            map.entry(*team_id).or_default().push(idx);
        }
    }

    map
}

/// Only teams with >= 2 persons are included since merges require two distinct persons.
fn build_team_cdf(team_person_indices: &HashMap<i32, Vec<usize>>) -> Vec<(f64, i32)> {
    let mut entries: Vec<(i32, usize)> = team_person_indices
        .iter()
        .filter(|(_, v)| v.len() >= 2)
        .map(|(&tid, v)| (tid, v.len()))
        .collect();

    entries.sort_by_key(|(tid, _)| *tid);

    let eligible_total: f64 = entries.iter().map(|(_, count)| *count as f64).sum();
    if eligible_total == 0.0 {
        return Vec::new();
    }

    let mut cumulative = 0.0;
    let mut cdf = Vec::with_capacity(entries.len());

    for (tid, count) in &entries {
        cumulative += *count as f64 / eligible_total;
        cdf.push((cumulative, *tid));
    }

    if let Some(last) = cdf.last_mut() {
        last.0 = 1.0;
    }

    cdf
}

pub fn select_team_weighted(cdf: &[(f64, i32)], rng: &mut impl Rng) -> Option<i32> {
    if cdf.is_empty() {
        return None;
    }
    let r: f64 = rng.gen();
    let idx = cdf.partition_point(|(cum, _)| *cum < r);
    Some(cdf[idx.min(cdf.len() - 1)].1)
}

/// Generate a JSONB properties object padded to approximately `target_bytes`.
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

    let current = serde_json::to_string(&Value::Object(obj.clone()))
        .unwrap()
        .len();
    if current < target_bytes {
        let padding_needed = target_bytes - current;
        let pad_val_len = padding_needed.saturating_sub(12);
        let pad: String = (0..pad_val_len)
            .map(|_| rng.gen_range(b'a'..=b'z') as char)
            .collect();
        obj.insert("_pad".to_string(), Value::String(pad));
    }

    Value::Object(obj)
}

/// Zipf-weighted team sizes (weight = 1/rank^1.5) so a few teams dominate.
/// 86% of persons get 1 distinct_id, 14% get 2 (matching the measured ~1.14 ratio).
pub fn generate_person_registry(args: &BenchmarkArgs, rng: &mut impl Rng) -> PersonRegistry {
    let scale = args.scale as usize;
    let teams = args.teams;

    let weights: Vec<f64> = (1..=teams).map(|i| 1.0 / (i as f64).powf(1.5)).collect();
    let total_weight: f64 = weights.iter().sum();

    let mut team_counts: Vec<usize> = weights
        .iter()
        .map(|w| ((w / total_weight) * scale as f64).round() as usize)
        .collect();

    let total: usize = team_counts.iter().sum();
    match total.cmp(&scale) {
        std::cmp::Ordering::Greater => team_counts[0] -= total - scale,
        std::cmp::Ordering::Less => team_counts[0] += scale - total,
        std::cmp::Ordering::Equal => {}
    }

    let mut persons = Vec::with_capacity(scale);
    let mut distinct_ids = Vec::with_capacity((scale as f64 * 1.14) as usize);

    for (team_idx, &count) in team_counts.iter().enumerate() {
        let team_id = (team_idx as i32) + 1;
        for _ in 0..count {
            let person_uuid = Uuid::new_v4();
            persons.push((team_id, person_uuid));

            let mut bytes = [0u8; 16];
            rng.fill(&mut bytes);
            distinct_ids.push((team_id, person_uuid, Uuid::from_bytes(bytes).to_string()));

            if rng.gen_ratio(14, 100) {
                let mut bytes2 = [0u8; 16];
                rng.fill(&mut bytes2);
                distinct_ids.push((team_id, person_uuid, Uuid::from_bytes(bytes2).to_string()));
            }
        }
    }

    PersonRegistry {
        persons,
        distinct_ids,
    }
}
