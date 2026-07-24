//! Exact port of features.py text_stats / text_pair_features (pair v1.7 dumb
//! text statistics). Per-signal stats are cached per store row alongside the
//! identifier cache; the query side is computed once per incoming signal.

use regex::Regex;
use std::collections::HashSet;
use std::sync::OnceLock;

pub struct TextStats {
    pub len: f64,
    pub ttr: f64,
    pub neg_density: f64,
    pub punct_frac: f64,
    pub upper_frac: f64,
    pub has_stack: f64,
    pub gram3: HashSet<String>,
    pub firstline: HashSet<String>,
}

fn re_word() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[A-Za-z]{2,}").unwrap())
}

fn re_neg() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(
            r"(?i)\b(error|fail|failed|failing|broken|stuck|crash|frustrat|unhappy|complain|unable|cannot|wrong|missing|invalid|denied|slow|bug|blocked)\b",
        )
        .unwrap()
    })
}

fn re_stack() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r" in [\w/.@-]+ line \d+|Traceback|at [\w$.]+\(").unwrap())
}

fn re_ws() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\s+").unwrap())
}

impl TextStats {
    pub fn compute(text: &str) -> Self {
        let t: String = text.chars().take(4000).collect();
        let n = t.chars().count().max(1) as f64;
        let words: Vec<&str> = re_word().find_iter(&t).map(|m| m.as_str()).collect();
        let nw = words.len().max(1) as f64;
        let uniq: HashSet<String> = words.iter().map(|w| w.to_lowercase()).collect();
        let head2000: String = text.chars().take(2000).collect();
        let collapsed = re_ws()
            .replace_all(&head2000.to_lowercase(), " ")
            .to_string();
        let cchars: Vec<char> = collapsed.chars().collect();
        let gram3 = if cchars.len() >= 3 {
            cchars
                .windows(3)
                .map(|w| w.iter().collect::<String>())
                .collect()
        } else {
            HashSet::new()
        };
        let first = text.trim().split('\n').next().unwrap_or("");
        let first: String = first.chars().take(300).collect::<String>().to_lowercase();
        let firstline = re_word()
            .find_iter(&first)
            .map(|m| m.as_str().to_string())
            .collect();
        TextStats {
            len: t.chars().count() as f64,
            ttr: uniq.len() as f64 / nw,
            neg_density: re_neg().find_iter(&t).count() as f64 / nw,
            punct_frac: t
                .chars()
                .filter(|c| !c.is_alphanumeric() && !c.is_whitespace())
                .count() as f64
                / n,
            upper_frac: t.chars().filter(|c| c.is_uppercase()).count() as f64 / n,
            has_stack: f64::from(re_stack().is_match(&t)),
            gram3,
            firstline,
        }
    }
}

fn sjac(a: &HashSet<String>, b: &HashSet<String>) -> f64 {
    let inter = a.intersection(b).count() as f64;
    let union = a.union(b).count() as f64;
    inter / union.max(1.0)
}

fn ratio(a: f64, b: f64) -> f64 {
    a.min(b) / a.max(b).max(1e-9)
}

pub fn text_pair_features(sa: &TextStats, sb: &TextStats) -> [(&'static str, f64); 10] {
    [
        ("gram3_jac", sjac(&sa.gram3, &sb.gram3)),
        ("firstline_jac", sjac(&sa.firstline, &sb.firstline)),
        ("len_ratio", ratio(sa.len, sb.len)),
        (
            "log_len_absdiff",
            ((sa.len + 1.0).ln() - (sb.len + 1.0).ln()).abs(),
        ),
        ("ttr_ratio", ratio(sa.ttr, sb.ttr)),
        ("neg_density_min", sa.neg_density.min(sb.neg_density)),
        ("neg_density_ratio", ratio(sa.neg_density, sb.neg_density)),
        ("punct_frac_ratio", ratio(sa.punct_frac, sb.punct_frac)),
        ("upper_frac_ratio", ratio(sa.upper_frac, sb.upper_frac)),
        ("has_stack_min", sa.has_stack.min(sb.has_stack)),
    ]
}
