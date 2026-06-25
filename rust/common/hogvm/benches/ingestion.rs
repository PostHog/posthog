//! Ingestion-batch perf harness (pure-Rust modes) for the HogVM.
//!
//! Models real ingestion: run a non-trivial Hog program (several arraySort/arrayReverse passes
//! over each event's numeric series — see scripts/gen_perf_workload.py) across 10k events in
//! batches of 2k. Measures two pure-Rust modes:
//!   - single: one thread, one ExecutionContext reused across events (globals swapped per event)
//!   - parallel: rayon across chunks, one ExecutionContext per worker chunk
//! and reports throughput (events/s) + the parallel speedup. The Node and Rust-from-Node-FFI
//! modes (the full three-way comparison) are driven by separate harnesses; this is the Rust floor
//! and the parallelism signal.
//!
//! Run: `cargo bench --bench ingestion` (custom harness; see Cargo.toml `[[bench]] harness=false`).

use std::time::Instant;

use hogvm::{sync_execute, ExecutionContext, Program};
use rayon::prelude::*;
use serde_json::{json, Value};

const TOTAL_EVENTS: u64 = 10_000;
const BATCH_SIZE: usize = 2_000;
// Must match scripts/gen_perf_workload.py.
const SERIES_LEN: u64 = 128;

// Deterministic event generator — identical to the Python generator and (later) the Node harness.
fn make_event(e: u64) -> Value {
    let series: Vec<Value> = (0..SERIES_LEN)
        .map(|i| Value::from((e * 131 + i * 977) % 1000))
        .collect();
    json!({ "series": series, "k": e % 257 })
}

fn fresh_ctx(program: &[Value]) -> ExecutionContext {
    let prog = Program::new(program.to_vec()).expect("valid perf program");
    ExecutionContext::with_defaults(prog)
}

// Run a slice of events through one reused context (STL built once, globals swapped per event).
fn run_chunk(program: &[Value], events: &[u64]) -> Vec<Value> {
    let mut ctx = fresh_ctx(program);
    events
        .iter()
        .map(|&e| {
            ctx.globals = make_event(e);
            sync_execute(&ctx, false)
                .unwrap_or_else(|f| panic!("event {e} failed: {}", f.error))
        })
        .collect()
}

fn run_single(program: &[Value], events: &[u64]) -> Vec<Value> {
    run_chunk(program, events)
}

fn run_parallel(program: &[Value], events: &[u64], chunk: usize) -> Vec<Value> {
    events
        .par_chunks(chunk)
        .flat_map_iter(|c| run_chunk(program, c))
        .collect()
}

fn throughput(events: u64, dur: std::time::Duration) -> f64 {
    events as f64 / dur.as_secs_f64()
}

fn time_best<F: Fn() -> Vec<Value>>(reps: usize, f: F) -> std::time::Duration {
    let mut best = std::time::Duration::MAX;
    for _ in 0..reps {
        let t = Instant::now();
        let out = f();
        let d = t.elapsed();
        std::hint::black_box(out);
        best = best.min(d);
    }
    best
}

fn main() {
    let program: Vec<Value> = {
        let raw = include_str!("../tests/static/perf_program.json");
        serde_json::from_str(raw).expect("parse perf_program.json")
    };
    let oracle: Value = {
        let raw = include_str!("../tests/static/perf_oracle.json");
        serde_json::from_str(raw).expect("parse perf_oracle.json")
    };

    // Correctness gate: the first N events must match the reference VM before we trust timings.
    let expected = oracle["results"].as_array().expect("oracle results");
    let sample: Vec<u64> = (0..expected.len() as u64).collect();
    let got = run_single(&program, &sample);
    assert_eq!(&got, expected, "Rust VM diverged from reference on perf workload");
    println!(
        "correctness: first {} events match reference ✓",
        expected.len()
    );

    let events: Vec<u64> = (0..TOTAL_EVENTS).collect();
    let cores = std::thread::available_parallelism().map_or(1, |n| n.get());
    // Give rayon several chunks per core for load balancing, but keep them within a batch.
    let par_chunk = (BATCH_SIZE / 4).max(1);

    println!(
        "\nworkload: {TOTAL_EVENTS} events, batch {BATCH_SIZE}, {SERIES_LEN}-element series | cores: {cores}"
    );

    let reps = 5;
    let single = time_best(reps, || run_single(&program, &events));
    let parallel = time_best(reps, || run_parallel(&program, &events, par_chunk));

    let single_tput = throughput(TOTAL_EVENTS, single);
    let parallel_tput = throughput(TOTAL_EVENTS, parallel);

    println!("\n================ pure-Rust ingestion perf ================");
    println!(
        "single   : {:>8.2} ms  | {:>12.0} events/s",
        single.as_secs_f64() * 1e3,
        single_tput
    );
    println!(
        "parallel : {:>8.2} ms  | {:>12.0} events/s  ({:.2}x over single, {cores} cores)",
        parallel.as_secs_f64() * 1e3,
        parallel_tput,
        parallel_tput / single_tput
    );
    println!("=========================================================");
    println!("\nNote: pure-Node and Rust-from-Node (napi-rs FFI) modes are pending the Node harness;");
    println!("they run this same perf_program.json + event formula for an apples-to-apples comparison.");
}
