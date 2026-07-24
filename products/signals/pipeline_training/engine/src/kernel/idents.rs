//! identifiers-lite: exact port of features.py extract_identifiers / id_features.

use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

pub const CATEGORIES: [(&str, &str, f64); 7] = [
    (
        "uuid",
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        3.0,
    ),
    ("hash", r"\b[0-9a-f]{12,40}\b", 3.0),
    ("longnum", r"\b\d{5,}\b", 2.0),
    ("path", r"/[a-zA-Z0-9_.\-/]{6,}", 2.0),
    (
        "dotted",
        r"[a-zA-Z_][a-zA-Z0-9_]{2,}\.[a-zA-Z_][a-zA-Z0-9_.]{3,}",
        1.5,
    ),
    ("kebab", r"[a-zA-Z_][a-zA-Z0-9_]*-[a-zA-Z0-9_\-]{4,}", 1.0),
    ("error_class", r"[A-Z][a-zA-Z]*Error[a-zA-Z]*", 1.0),
];

const CONFLICT_CATEGORIES: [&str; 4] = ["kebab", "path", "dotted", "error_class"];

static COMPILED: LazyLock<Vec<(&'static str, Regex, f64)>> = LazyLock::new(|| {
    CATEGORIES
        .iter()
        .map(|(cat, pat, w)| (*cat, Regex::new(pat).unwrap(), *w))
        .collect()
});

pub type IdSets = HashMap<&'static str, HashSet<String>>;

pub fn extract_identifiers(text: &str) -> IdSets {
    // Python truncates by *characters*, not bytes
    let snippet: String = text.chars().take(4000).collect();
    let mut out: IdSets = HashMap::new();
    for (cat, rx, _w) in COMPILED.iter() {
        let found: HashSet<String> = rx
            .find_iter(&snippet)
            .map(|m| m.as_str().to_string())
            .collect();
        if !found.is_empty() {
            out.insert(cat, found);
        }
    }
    out
}

pub fn merge_identifier_sets(sets: &[&IdSets]) -> IdSets {
    let mut out: IdSets = HashMap::new();
    for d in sets {
        for (cat, vals) in d.iter() {
            out.entry(cat).or_default().extend(vals.iter().cloned());
        }
    }
    out
}

pub struct IdFeatures {
    pub id_overlap: f64,
    pub id_shared_w: f64,
    pub id_conflict: f64,
}

pub fn id_features(ids_a: &IdSets, ids_b: &IdSets) -> IdFeatures {
    let weights: HashMap<&str, f64> = CATEGORIES.iter().map(|(c, _p, w)| (*c, *w)).collect();
    let mut shared_w = 0.0;
    let mut union_w = 0.0;
    let mut conflict = 0.0;
    let mut cats: HashSet<&'static str> = ids_a.keys().copied().collect();
    cats.extend(ids_b.keys().copied());
    for cat in cats {
        let empty = HashSet::new();
        let a = ids_a.get(cat).unwrap_or(&empty);
        let b = ids_b.get(cat).unwrap_or(&empty);
        let w = weights[cat];
        let inter = a.intersection(b).count() as f64;
        let union = a.union(b).count() as f64;
        shared_w += w * inter;
        union_w += w * union;
        if CONFLICT_CATEGORIES.contains(&cat) && !a.is_empty() && !b.is_empty() && inter == 0.0 {
            conflict = 1.0;
        }
    }
    IdFeatures {
        id_overlap: if union_w > 0.0 {
            shared_w / union_w
        } else {
            0.0
        },
        id_shared_w: shared_w,
        id_conflict: conflict,
    }
}
