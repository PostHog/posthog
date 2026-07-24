//! Template/slot lexical features (pair v1.5) — exact port of features.py
//! slot_features: same tokenizer, same greedy Ratcliff-Obershelp recursion
//! (iteration order matters for block tie-breaking; keep in lockstep).

use regex::Regex;
use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

static SLOT_TOKEN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[A-Za-z0-9_\-\./]+").unwrap());
pub const SLOT_GATE_COS: f64 = 0.12;
const TOKEN_CAP: usize = 400;

fn slot_tokens(text: &str) -> Vec<&str> {
    let snippet_end = text
        .char_indices()
        .nth(3000)
        .map_or(text.len(), |(i, _c)| i);
    SLOT_TOKEN
        .find_iter(&text[..snippet_end])
        .take(TOKEN_CAP)
        .map(|m| m.as_str())
        .collect()
}

#[allow(clippy::too_many_arguments)]
fn match_blocks<'a>(
    a: &[&'a str],
    b: &[&'a str],
    alo: usize,
    ahi: usize,
    blo: usize,
    bhi: usize,
    out: &mut Vec<(usize, usize, usize)>,
) {
    let (mut best_i, mut best_j, mut best_k) = (alo, blo, 0usize);
    let mut b2j: HashMap<&str, Vec<usize>> = HashMap::new();
    for j in blo..bhi {
        b2j.entry(b[j]).or_default().push(j); // ascending j, matching Python
    }
    let mut j2len: HashMap<usize, usize> = HashMap::new();
    for i in alo..ahi {
        let mut new_j2len: HashMap<usize, usize> = HashMap::new();
        if let Some(js) = b2j.get(a[i]) {
            for &j in js {
                let k = if j > 0 {
                    j2len.get(&(j - 1)).copied().unwrap_or(0) + 1
                } else {
                    1
                };
                new_j2len.insert(j, k);
                if k > best_k {
                    best_i = i + 1 - k;
                    best_j = j + 1 - k;
                    best_k = k;
                }
            }
        }
        j2len = new_j2len;
    }
    if best_k == 0 {
        return;
    }
    match_blocks(a, b, alo, best_i, blo, best_j, out);
    out.push((best_i, best_j, best_k));
    match_blocks(a, b, best_i + best_k, ahi, best_j + best_k, bhi, out);
}

fn conflictish(token: &str) -> bool {
    token.chars().any(|c| c.is_ascii_digit()) || token.contains('/')
}

/// (template_sim, slot_conflict_w) — see features.py for semantics.
pub fn slot_features(text_a: &str, text_b: &str) -> (f64, f64) {
    let ta = slot_tokens(text_a);
    let tb = slot_tokens(text_b);
    if ta.is_empty() || tb.is_empty() {
        return (0.0, 0.0);
    }
    let mut blocks = Vec::new();
    match_blocks(&ta, &tb, 0, ta.len(), 0, tb.len(), &mut blocks);
    let matched: usize = blocks.iter().map(|(_i, _j, k)| k).sum();
    let template_sim = 2.0 * matched as f64 / (ta.len() + tb.len()) as f64;
    let mut in_a = vec![false; ta.len()];
    let mut in_b = vec![false; tb.len()];
    for &(i, j, k) in &blocks {
        for d in 0..k {
            in_a[i + d] = true;
            in_b[j + d] = true;
        }
    }
    let slots_a: HashSet<&str> = ta
        .iter()
        .zip(&in_a)
        .filter(|(_t, m)| !**m)
        .map(|(t, _m)| *t)
        .collect();
    let slots_b: HashSet<&str> = tb
        .iter()
        .zip(&in_b)
        .filter(|(_t, m)| !**m)
        .map(|(t, _m)| *t)
        .collect();
    let conflict_w = slots_a
        .symmetric_difference(&slots_b)
        .filter(|t| conflictish(t))
        .count() as f64;
    (template_sim, conflict_w)
}
