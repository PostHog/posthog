//! Perf + correctness harness for the geoip transformation on the Rust HogVM: runs the compiled
//! geoip Hog template against fixture event globals in a loop, no napi boundary.
//!
//! Build/run (from rust/common/hogvm/node):
//!   cargo run --release --features noop --bin profile_geoip
//!
//! With no args it uses the fixtures in ../perf/fixtures and the dev mmdb at
//! share/GeoLite2-City.mmdb, checks every warmup result against
//! ../perf/fixtures/geoip-expected.json (hard failure on drift), then reports us/op.
//! Pass `--write-expected` to (re)generate the expected-output fixture after an intentional
//! semantic change. Positional overrides: <bytecode.json> <globals.json> <mmdb> [iters].

use std::time::Instant;

use hogvm_node::{build_program, init, run_batch_program, InitOptions};
use serde_json::Value;

const DEFAULT_ITERS: usize = 100_000;

fn manifest_path(rel: &str) -> String {
    format!("{}/{}", env!("CARGO_MANIFEST_DIR"), rel)
}

fn main() {
    let mut positional: Vec<String> = Vec::new();
    let mut write_expected = false;
    for arg in std::env::args().skip(1) {
        if arg == "--write-expected" {
            write_expected = true;
        } else {
            positional.push(arg);
        }
    }
    let mut positional = positional.into_iter();
    let bytecode_path = positional
        .next()
        .unwrap_or_else(|| manifest_path("../perf/fixtures/geoip-bytecode.json"));
    let globals_path = positional
        .next()
        .unwrap_or_else(|| manifest_path("../perf/fixtures/geoip-globals.json"));
    let mmdb_path = positional
        .next()
        .unwrap_or_else(|| manifest_path("../../../../share/GeoLite2-City.mmdb"));
    let iters: usize = positional
        .next()
        .map(|s| s.parse().expect("iters must be a number"))
        .unwrap_or(DEFAULT_ITERS);
    let expected_path = manifest_path("../perf/fixtures/geoip-expected.json");

    let bytecode: Vec<Value> =
        serde_json::from_str(&std::fs::read_to_string(&bytecode_path).expect("read bytecode"))
            .expect("parse bytecode");
    let globals: Vec<Value> =
        serde_json::from_str(&std::fs::read_to_string(&globals_path).expect("read globals"))
            .expect("parse globals");

    init(InitOptions {
        mmdb_path: Some(mmdb_path),
        known_bot_ua_list: Some(vec![]),
        known_bot_ip_list: Some(vec![]),
    })
    .expect("init");

    let program = build_program(bytecode).expect("valid program");

    // Warmup doubles as the correctness gate: every fixture event's output must match the
    // pinned expected results exactly.
    let mut outputs: Vec<Value> = Vec::with_capacity(globals.len());
    for g in &globals {
        let r = run_batch_program(&program, std::slice::from_ref(g), Some(1_000_000));
        let r = r.into_iter().next().expect("one result");
        assert!(r.error.is_none(), "execution error: {:?}", r.error);
        outputs.push(r.result.expect("result"));
    }

    if write_expected {
        std::fs::write(
            &expected_path,
            serde_json::to_string_pretty(&outputs).expect("serialize expected"),
        )
        .expect("write expected");
        println!("wrote expected outputs to {expected_path}");
        return;
    }

    match std::fs::read_to_string(&expected_path) {
        Ok(raw) => {
            let expected: Vec<Value> = serde_json::from_str(&raw).expect("parse expected");
            assert_eq!(
                expected.len(),
                outputs.len(),
                "expected-output fixture has {} entries, got {} outputs",
                expected.len(),
                outputs.len()
            );
            for (i, (exp, got)) in expected.iter().zip(outputs.iter()).enumerate() {
                assert_eq!(
                    exp, got,
                    "OUTPUT DRIFT on fixture event {i} — the optimization changed semantics"
                );
            }
            println!("correctness check passed ({} fixture events)", outputs.len());
        }
        Err(_) => {
            println!("warning: no expected-output fixture at {expected_path}; run with --write-expected to pin one");
        }
    }

    let start = Instant::now();
    for i in 0..iters {
        let g = &globals[i % globals.len()];
        let r = run_batch_program(&program, std::slice::from_ref(g), Some(1_000_000));
        std::hint::black_box(&r);
    }
    let elapsed = start.elapsed();
    println!(
        "{} iters in {:.2}s -> {:.1} us/op",
        iters,
        elapsed.as_secs_f64(),
        elapsed.as_secs_f64() * 1e6 / iters as f64
    );
}
