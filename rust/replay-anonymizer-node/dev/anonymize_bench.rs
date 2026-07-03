//! Local performance bench for the Rust anonymizer. Not built or run by CI's `cargo test` (it's an
//! example, so it only compiles when asked). It reads the fixtures the Node bench dumps to /tmp and
//! compares the production streaming path (`anonymize_kafka_payload`) against the tree walk, plus
//! decomposes where the tree spends its time (parse / scrub / encode) via the zero-copy floors.
//!
//! Usage:
//!   1. dump fixtures:  pnpm --filter=@posthog/nodejs exec jest anonymize-bench --runInBand   (un-skip it)
//!   2. run this bench: cargo run --release --example anonymize_bench -p replay-anonymizer-node

use std::hint::black_box;
use std::time::Instant;

use replay_anonymizer_node::{
    anonymize_kafka_payload, anonymize_kafka_payload_opts, anonymize_message, AllowLists,
    AnonymizeOpts, Ctx,
};
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

    // Pass-through-heavy regime: mousemove/scroll events dominate real sessions by count; the
    // streaming path memcpys them without ever parsing. Synthesized here (the Node generator is
    // DOM-only).
    {
        let mousemove = r#"{"type":3,"timestamp":1700000000000,"data":{"source":1,"positions":[{"x":100.5,"y":200.25,"id":42,"timeOffset":-20},{"x":101.5,"y":201.25,"id":42,"timeOffset":-10}]}}"#;
        let scroll =
            r#"{"type":3,"timestamp":1700000000001,"data":{"source":3,"id":7,"x":0,"y":1423}}"#;
        let input = r#"{"type":3,"timestamp":1700000000002,"data":{"source":5,"id":9,"text":"some secret words typed here","isChecked":false}}"#;
        let mut items = Vec::new();
        for i in 0..12_000 {
            items.push(match i % 10 {
                9 => input,
                n if n % 2 == 0 => mousemove,
                _ => scroll,
            });
        }
        let inner = format!(
            r#"{{"event":"$snapshot_items","properties":{{"$snapshot_items":[{}],"$session_id":"bench","$window_id":"w1"}}}}"#,
            items.join(",")
        );
        let payload =
            serde_json::to_string(&serde_json::json!({"distinct_id": "bench-user", "data": inner}))
                .unwrap()
                .into_bytes();
        let mb = payload.len() as f64 / (1024.0 * 1024.0);
        let n = 40;
        let stream = p50(3, n, || {
            let mut b = payload.clone();
            black_box(anonymize_kafka_payload(&allow, &mut b).unwrap());
        });
        let no_walk = AnonymizeOpts {
            adaptive_routing: false,
            byte_walk: false,
        };
        let stream_simd = p50(3, n, || {
            let mut b = payload.clone();
            black_box(anonymize_kafka_payload_opts(&allow, &mut b, no_walk).unwrap());
        });
        let ctx = Ctx::new(&allow);
        let tree = p50(3, n, || {
            black_box(
                replay_anonymizer_node::snapshot::anonymize_via_tree(
                    &ctx,
                    "bench-user",
                    inner.as_bytes(),
                )
                .unwrap(),
            );
        });
        println!("\n===== mousemove-heavy: {mb:.1} MB, 12k events =====");
        println!("STREAM anonymize_kafka_payload       = {stream:.1} ms   (byte walk)");
        println!("       simd scrub route (walk off)   = {stream_simd:.1} ms");
        println!("TREE   anonymize_via_tree            = {tree:.1} ms   (no outer parse)");
    }

    for label in ["medium", "large"] {
        let path = format!("/tmp/replay-bench-{label}.json");
        let Ok(bytes) = std::fs::read(&path) else {
            println!("SKIP {label}: {path} missing — run the Node bench first to dump it");
            continue;
        };
        let mb = bytes.len() as f64 / (1024.0 * 1024.0);
        let n = 40;

        // Rebuild the Kafka payload shape from the dumped `{ windowId: Event[] }` message: flatten
        // the windows into one $snapshot_items array (timestamps injected when the generator didn't
        // set them) and wrap it in the outer `{distinct_id, data}` envelope.
        let message: serde_json::Value = serde_json::from_slice(&bytes).expect("parse dump");
        let mut items: Vec<serde_json::Value> = Vec::new();
        for events in message.as_object().expect("dump is an object").values() {
            items.extend(events.as_array().cloned().unwrap_or_default());
        }
        for (i, ev) in items.iter_mut().enumerate() {
            if let Some(obj) = ev.as_object_mut() {
                obj.entry("timestamp")
                    .or_insert(serde_json::json!(1_700_000_000_000i64 + i as i64));
            }
        }
        let inner = serde_json::to_string(&serde_json::json!({
            "event": "$snapshot_items",
            "properties": {
                "$snapshot_items": items,
                "$session_id": "bench-session",
                "$window_id": "bench-window",
                "$snapshot_source": "web",
                "$lib": "posthog-js",
            }
        }))
        .unwrap();
        let payload = serde_json::to_string(&serde_json::json!({
            "distinct_id": "bench-user",
            "data": inner,
        }))
        .unwrap()
        .into_bytes();

        // Production streaming path: envelope scan + pass-through memcpy + per-data-span splice.
        let route = {
            let mut b = payload.clone();
            anonymize_kafka_payload(&allow, &mut b).unwrap().route
        };
        let stream = p50(3, n, || {
            let mut b = payload.clone();
            black_box(anonymize_kafka_payload(&allow, &mut b).unwrap());
        });
        let no_walk = AnonymizeOpts {
            adaptive_routing: false,
            byte_walk: false,
        };
        let stream_simd = p50(3, n, || {
            let mut b = payload.clone();
            black_box(anonymize_kafka_payload_opts(&allow, &mut b, no_walk).unwrap());
        });
        // Streaming minus the outer-envelope parse: what the scan+splice itself costs (plus one
        // buffer clone — the in-place path consumes its input).
        let stream_inner = p50(3, n, || {
            let mut b = inner.as_bytes().to_vec();
            black_box(
                replay_anonymizer_node::snapshot::anonymize_snapshot_data(
                    &allow,
                    "bench-user",
                    &mut b,
                )
                .unwrap(),
            );
        });
        // Tree fallback/reference path over the same payload's inner event json.
        let ctx = Ctx::new(&allow);
        let tree = p50(3, n, || {
            black_box(
                replay_anonymizer_node::snapshot::anonymize_via_tree(
                    &ctx,
                    "bench-user",
                    inner.as_bytes(),
                )
                .unwrap(),
            );
        });

        // Full: borrowed parse + scrub walk + encode of the raw `{windowId: Event[]}` dump (the old
        // drop-in shape, minus the FFI string round-trip).
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
        // Borrowed parse + the dedupe walk — isolates what JSON.parse-duplicate-key repair costs.
        let borrowed_p_dedupe = p50(3, n, || {
            let mut b = bytes.clone();
            let mut v = simd_json::to_borrowed_value(&mut b).unwrap();
            replay_anonymizer_node::json::dedupe_in_place(&mut v).unwrap();
            black_box(v);
        });

        println!("\n===== {label}: {mb:.1} MB =====");
        println!(
            "STREAM anonymize_kafka_payload       = {stream:.1} ms   (production byte path, routed: {})",
            route.as_str()
        );
        println!("       simd scrub route (walk off)   = {stream_simd:.1} ms");
        println!(
            "       inner only (no outer parse)   = {stream_inner:.1} ms   -> outer envelope parse ~= {:.1} ms",
            stream - stream_inner
        );
        println!("TREE   anonymize_via_tree            = {tree:.1} ms   (reference/fallback)");
        println!(
            "full  borrowed parse + scrub + encode = {full:.1} ms   (whole-message tree walk)"
        );
        println!(
            "      owned parse + encode (no scrub) = {owned_pe:.1} ms  -> scrub walk ~= {:.1} ms",
            full - owned_pe
        );
        println!("      borrowed parse + encode         = {borrowed_pe:.1} ms  -> owned-alloc tax ~= {:.1} ms", owned_pe - borrowed_pe);
        println!(
            "      borrowed parse only             = {borrowed_p:.1} ms  -> encode ~= {:.1} ms",
            borrowed_pe - borrowed_p
        );
        println!(
            "      borrowed parse + dedupe         = {borrowed_p_dedupe:.1} ms  -> dedupe walk ~= {:.1} ms",
            borrowed_p_dedupe - borrowed_p
        );
    }
}
