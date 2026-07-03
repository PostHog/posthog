//! Benchmark against real production session blocks. Payloads are rebuilt textually from the
//! ml-mirror S3 blocks (byte-preserving event content; see the session notes), one payload per
//! session block, in /tmp/prod-payloads/*.bin. Reports per-message stats across the corpus for the
//! production entry (byte walk), the walk-off simd path, and (with `--features mlhog-bench`) the
//! MLHog v2 engine on the identical contract.
//!
//! Run: cargo run --release --features mlhog-bench --example prod_bench -p replay-anonymizer-node

use std::hint::black_box;
use std::time::Instant;

use replay_anonymizer_node::{
    anonymize_kafka_payload_opts, AllowLists, AnonymizeOpts, Route,
};

fn main() {
    let mut paths: Vec<_> = std::fs::read_dir("/tmp/prod-payloads")
        .expect("run the fetch script first")
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().map(|x| x == "bin").unwrap_or(false))
        .collect();
    paths.sort();
    let payloads: Vec<Vec<u8>> = paths.iter().map(|p| std::fs::read(p).unwrap()).collect();
    let total_mb: f64 = payloads.iter().map(|p| p.len() as f64).sum::<f64>() / (1024.0 * 1024.0);
    println!("{} payloads, {total_mb:.0} MB total", payloads.len());

    // Realistic allow lists (same shape as the other benches).
    let allow = AllowLists::new(
        [
            "the", "a", "to", "of", "and", "in", "is", "on", "for", "with", "as", "at", "by",
            "an", "be", "this", "that", "it", "from", "or", "you", "your", "we", "our",
            "dashboard", "checkout", "settings", "campaign", "session", "workspace",
            "subscription", "experiment", "funnel", "warehouse", "customer", "onboarding",
            "metric", "property", "timeline",
        ],
        ["api", "app", "cdn", "static"],
    );

    bench("crate (byte walk)", &allow, &payloads, AnonymizeOpts::default());
    bench(
        "crate (walk off) ",
        &allow,
        &payloads,
        AnonymizeOpts {
            adaptive_routing: true,
            byte_walk: false,
        },
    );
    #[cfg(feature = "mlhog-bench")]
    bench_mlhog(&allow, &payloads);
}

fn bench(label: &str, allow: &AllowLists, payloads: &[Vec<u8>], opts: AnonymizeOpts) {
    // Warmup round.
    run_round(allow, payloads, opts);
    const ROUNDS: usize = 3;
    let mut per_msg: Vec<f64> = Vec::with_capacity(payloads.len());
    let mut ok = 0usize;
    let mut failed = 0usize;
    let mut tree_routed = 0usize;
    let t0 = Instant::now();
    for round in 0..ROUNDS {
        for p in payloads {
            let mut b = p.clone();
            let t = Instant::now();
            let r = anonymize_kafka_payload_opts(allow, &mut b, opts);
            let ms = t.elapsed().as_secs_f64() * 1000.0;
            if round == 0 {
                per_msg.push(ms);
                match &r {
                    Ok(m) => {
                        ok += 1;
                        if m.route == Route::Tree {
                            tree_routed += 1;
                        }
                    }
                    Err(_) => failed += 1,
                }
            }
            black_box(r).ok();
        }
    }
    let total_s = t0.elapsed().as_secs_f64() / ROUNDS as f64;
    report(label, &mut per_msg, total_s, payloads, ok, failed, Some(tree_routed));
}

#[cfg(feature = "mlhog-bench")]
fn bench_mlhog(allow: &AllowLists, payloads: &[Vec<u8>]) {
    use replay_anonymizer_node::mlhog::engine;
    run_round_mlhog(allow, payloads);
    const ROUNDS: usize = 3;
    let mut per_msg: Vec<f64> = Vec::with_capacity(payloads.len());
    let mut ok = 0usize;
    let mut failed = 0usize;
    let t0 = Instant::now();
    for round in 0..ROUNDS {
        for p in payloads {
            let mut b = p.clone();
            let t = Instant::now();
            let r = engine::anonymize_kafka_payload(allow, &mut b);
            let ms = t.elapsed().as_secs_f64() * 1000.0;
            if round == 0 {
                per_msg.push(ms);
                match &r {
                    Ok(_) => ok += 1,
                    Err(_) => failed += 1,
                }
            }
            black_box(r).ok();
        }
    }
    let total_s = t0.elapsed().as_secs_f64() / ROUNDS as f64;
    report("mlhog v2 engine  ", &mut per_msg, total_s, payloads, ok, failed, None);
}

fn run_round(allow: &AllowLists, payloads: &[Vec<u8>], opts: AnonymizeOpts) {
    for p in payloads {
        let mut b = p.clone();
        black_box(anonymize_kafka_payload_opts(allow, &mut b, opts)).ok();
    }
}

#[cfg(feature = "mlhog-bench")]
fn run_round_mlhog(allow: &AllowLists, payloads: &[Vec<u8>]) {
    use replay_anonymizer_node::mlhog::engine;
    for p in payloads {
        let mut b = p.clone();
        black_box(engine::anonymize_kafka_payload(allow, &mut b)).ok();
    }
}

#[allow(clippy::too_many_arguments)]
fn report(
    label: &str,
    per_msg: &mut [f64],
    total_s: f64,
    payloads: &[Vec<u8>],
    ok: usize,
    failed: usize,
    tree_routed: Option<usize>,
) {
    per_msg.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = per_msg.len();
    let sum: f64 = per_msg.iter().sum();
    let total_mb: f64 = payloads.iter().map(|p| p.len() as f64).sum::<f64>() / (1024.0 * 1024.0);
    let route = tree_routed
        .map(|t| format!(", routed tree: {t}"))
        .unwrap_or_default();
    println!(
        "{label}: avg {:.2} ms/msg, p50 {:.2}, p95 {:.2}, p99 {:.2} | {:.0} MB/s | ok {ok}, failed {failed}{route}",
        sum / n as f64,
        per_msg[n / 2],
        per_msg[n * 95 / 100],
        per_msg[n * 99 / 100],
        total_mb / total_s,
    );
}
