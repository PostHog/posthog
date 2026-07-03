//! Local performance bench for the Rust anonymizer. Not built or run by CI's `cargo test` (it's an
//! example, so it only compiles when asked). It reads the fixtures the Node bench dumps to /tmp and
//! decomposes where `anonymize_message` spends its time, plus measures the zero-copy (borrowed) floor.
//!
//! Usage:
//!   1. dump fixtures:  pnpm --filter=@posthog/nodejs exec jest anonymize-bench --runInBand   (un-skip it)
//!   2. run this bench: cargo run --release --example anonymize_bench -p replay-anonymizer-node

use std::hint::black_box;
use std::time::Instant;

use replay_anonymizer_node::{anonymize_message, AllowLists};
use simd_json::prelude::*;

fn p50<F: FnMut()>(warmup: usize, n: usize, mut f: F) -> f64 {
    for _ in 0..warmup {
        f();
    }
    let mut times = Vec::with_capacity(n);
    for _ in 0..n {
        let t = Instant::now();
        f();
        times.push(t.elapsed().as_secs_f64() * 1000.0);
    }
    times.sort_by(|a, b| a.partial_cmp(b).unwrap());
    times[n / 2]
}

fn main() {
    let common = [
        "the", "a", "to", "of", "and", "in", "is", "on", "for", "with", "as", "at", "by", "an",
        "be", "this", "that", "it", "from", "or", "you", "your", "we", "our",
    ];
    // Matches the allow list the Node bench uses, so both sides scrub the same fixture identically.
    let content_allow = [
        "dashboard",
        "checkout",
        "settings",
        "campaign",
        "session",
        "workspace",
        "subscription",
        "experiment",
        "funnel",
        "warehouse",
        "customer",
        "onboarding",
        "metric",
        "property",
        "timeline",
    ];
    let text: Vec<String> = common
        .iter()
        .chain(content_allow.iter())
        .map(|s| s.to_string())
        .collect();
    let url: Vec<String> = ["api", "app", "cdn", "static"]
        .iter()
        .map(|s| s.to_string())
        .collect();
    let allow = AllowLists::new(text, url);

    for label in ["medium", "large"] {
        let path = format!("/tmp/replay-bench-{label}.json");
        let Ok(bytes) = std::fs::read(&path) else {
            println!("SKIP {label}: {path} missing — run the Node bench first to dump it");
            continue;
        };
        let mb = bytes.len() as f64 / (1024.0 * 1024.0);
        let n = 40;

        // Full: owned parse + scrub walk + encode (what "Rust owns the parse and serialize" costs today).
        let full = p50(3, n, || {
            let mut b = bytes.clone();
            anonymize_message(&allow, &mut b).unwrap();
        });
        // Owned parse + encode, NO scrub — isolates owned-tree alloc + serialize.
        let owned_pe = p50(3, n, || {
            let mut b = bytes.clone();
            let v = simd_json::to_owned_value(&mut b).unwrap();
            black_box(v.encode());
        });
        // Borrowed (zero-copy) parse + encode, NO scrub — the floor if we stop materializing owned strings.
        let borrowed_pe = p50(3, n, || {
            let mut b = bytes.clone();
            let v = simd_json::to_borrowed_value(&mut b).unwrap();
            black_box(v.encode());
        });
        // Borrowed parse only — pure parse.
        let borrowed_p = p50(3, n, || {
            let mut b = bytes.clone();
            black_box(simd_json::to_borrowed_value(&mut b).unwrap());
        });

        println!("\n===== {label}: {mb:.1} MB =====");
        println!("full  owned parse + scrub + encode   = {full:.1} ms   (generic 'owns the parse+serialize')");
        println!(
            "      owned parse + encode (no scrub) = {owned_pe:.1} ms  -> scrub walk ~= {:.1} ms",
            full - owned_pe
        );
        println!("      borrowed parse + encode         = {borrowed_pe:.1} ms  -> owned-alloc tax ~= {:.1} ms", owned_pe - borrowed_pe);
        println!(
            "      borrowed parse only             = {borrowed_p:.1} ms  -> encode ~= {:.1} ms",
            borrowed_pe - borrowed_p
        );
    }
}
