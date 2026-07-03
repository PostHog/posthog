//! Side-by-side benchmark: the verbatim MLHog v2 byte-scanning scrubber (`src/mlhog/`, bench-only)
//! against this crate's paths, on the same fixtures. MLHog's unit of work is one event line (its
//! pipeline reads JSONL), so events are pre-serialized outside the timed loop and the walk is timed
//! per message worth of lines — comparable to this crate's "inner only" numbers, which also pay
//! envelope scanning and metadata extraction on top.
//!
//! Run: cargo run --release --features mlhog-bench --example mlhog_bench -p replay-anonymizer-node
//! (fixtures come from un-skipping the Node bench; see dev/anonymize_bench.rs)

use std::hint::black_box;
use std::time::Instant;

use replay_anonymizer_node::mlhog::dict::AllowLists;
use replay_anonymizer_node::mlhog::v2::V2Worker;
use replay_anonymizer_node::mlhog::Ctx;

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
    // Same allow lists as dev/anonymize_bench.rs, so the scrub workload matches.
    let common = [
        "the", "a", "to", "of", "and", "in", "is", "on", "for", "with", "as", "at", "by", "an",
        "be", "this", "that", "it", "from", "or", "you", "your", "we", "our",
    ];
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
    let allow = AllowLists::new(
        common.iter().chain(content_allow.iter()).copied(),
        ["api", "app", "cdn", "static"],
    );
    let ctx = Ctx::new(&allow);

    // Mousemove-heavy synthetic lines (matches anonymize_bench.rs's regime).
    {
        let mousemove = r#"{"type":3,"timestamp":1700000000000,"data":{"source":1,"positions":[{"x":100.5,"y":200.25,"id":42,"timeOffset":-20},{"x":101.5,"y":201.25,"id":42,"timeOffset":-10}]}}"#;
        let scroll =
            r#"{"type":3,"timestamp":1700000000001,"data":{"source":3,"id":7,"x":0,"y":1423}}"#;
        let input = r#"{"type":3,"timestamp":1700000000002,"data":{"source":5,"id":9,"text":"some secret words typed here","isChecked":false}}"#;
        let mut lines: Vec<Vec<u8>> = Vec::new();
        for i in 0..12_000 {
            lines.push(
                match i % 10 {
                    9 => input,
                    n if n % 2 == 0 => mousemove,
                    _ => scroll,
                }
                .as_bytes()
                .to_vec(),
            );
        }
        bench_lines("mousemove-heavy", &ctx, &lines);
    }

    for label in ["medium", "large"] {
        let path = format!("/tmp/replay-bench-{label}.json");
        let Ok(bytes) = std::fs::read(&path) else {
            println!("SKIP {label}: {path} missing — run the Node bench first to dump it");
            continue;
        };
        // `preserve_order` keeps the fixture's real (JSON.stringify insertion) key order.
        let message: serde_json::Value = serde_json::from_slice(&bytes).expect("parse dump");
        let mut lines: Vec<Vec<u8>> = Vec::new();
        for events in message.as_object().expect("dump is an object").values() {
            for ev in events.as_array().cloned().unwrap_or_default() {
                lines.push(serde_json::to_vec(&ev).unwrap());
            }
        }
        bench_lines(label, &ctx, &lines);
    }
}

fn bench_lines(label: &str, ctx: &Ctx<'_>, lines: &[Vec<u8>]) {
    let total: usize = lines.iter().map(Vec::len).sum();
    let mb = total as f64 / (1024.0 * 1024.0);
    let mut worker = V2Worker::default();
    let mut out = Vec::with_capacity(total + total / 8);
    let ms = p50(3, 40, || {
        out.clear();
        for line in lines {
            worker.scrub_line(ctx, line, &mut out);
        }
        black_box(&out);
    });
    println!(
        "MLHOG v2 {label:>16}: {mb:.1} MB, {} events = {ms:.1} ms  ({:.0} MB/s)",
        lines.len(),
        mb / (ms / 1000.0)
    );
}
