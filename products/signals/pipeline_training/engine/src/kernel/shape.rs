//! Layer-3 shape metrics (EVAL.md): computed in-engine at end of run so every sweep member is
//! scored for free, written straight to the perf DB.

use std::collections::HashMap;

pub fn shape_metrics(assignment: &HashMap<String, String>) -> Vec<(&'static str, f64)> {
    let mut sizes: HashMap<&str, usize> = HashMap::new();
    for report in assignment.values() {
        *sizes.entry(report.as_str()).or_default() += 1;
    }
    let mut counts: Vec<usize> = sizes.values().copied().collect();
    counts.sort_unstable_by(|a, b| b.cmp(a));
    let total: usize = counts.iter().sum();
    if total == 0 {
        return vec![];
    }
    let top_share = |fraction: f64| {
        let n = ((counts.len() as f64) * fraction).round().max(1.0) as usize;
        counts.iter().take(n).sum::<usize>() as f64 / total as f64
    };
    let singletons = counts.iter().filter(|&&c| c == 1).count();
    let concentration = counts
        .iter()
        .map(|&count| (count as f64 / total as f64).powi(2))
        .sum::<f64>();
    let mut asc = counts.clone();
    asc.sort_unstable();
    let pct = |q: f64| asc[(((asc.len() - 1) as f64) * q).round() as usize] as f64;
    vec![
        ("shape_n_reports", counts.len() as f64),
        ("shape_max_report", counts[0] as f64),
        ("shape_p50_report", pct(0.50)),
        ("shape_p90_report", pct(0.90)),
        ("shape_p95_report", pct(0.95)),
        ("shape_p99_report", pct(0.99)),
        ("shape_largest_share", counts[0] as f64 / total as f64),
        ("shape_top1pct_share", top_share(0.01)),
        ("shape_top5pct_share", top_share(0.05)),
        ("shape_top10pct_share", top_share(0.10)),
        (
            "shape_singleton_rate",
            singletons as f64 / counts.len() as f64,
        ),
        (
            "shape_singleton_signal_share",
            singletons as f64 / total as f64,
        ),
        ("shape_effective_reports", 1.0 / concentration),
        ("shape_creation_rate", counts.len() as f64 / total as f64),
    ]
}
