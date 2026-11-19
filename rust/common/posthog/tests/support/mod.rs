use std::collections::HashMap;

use metrics_util::debugging::{DebugValue, Snapshotter};

pub fn counter(snapshotter: &Snapshotter, name: &str) -> Option<(HashMap<String, String>, u64)> {
    snapshotter
        .snapshot()
        .into_vec()
        .into_iter()
        .find_map(|(key, _, _, value)| {
            if key.key().name() != name {
                return None;
            }
            let labels = key
                .key()
                .labels()
                .map(|l| (l.key().to_string(), l.value().to_string()))
                .collect();
            match value {
                DebugValue::Counter(c) => Some((labels, c)),
                _ => None,
            }
        })
}

pub fn labels(pairs: &[(&str, &str)]) -> HashMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}
