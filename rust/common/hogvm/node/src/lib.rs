//! Rust HogVM exposed to Node via napi-rs.
//!
//! `executeBatch` is the realistic Rust-from-Node ingestion path: Node hands a batch of events
//! (their globals) across the FFI boundary, Rust runs the same Hog program over all of them, and
//! returns the per-event results. The `parallel` flag selects single-threaded execution (which
//! isolates the pure boundary-marshalling cost) vs a `rayon` thread pool (native parallelism). The
//! harness measures both so the FFI rows are comparable to the in-process single/parallel rows.

use hogvm::{sync_execute, ExecutionContext, Program};
use napi::bindgen_prelude::Float64Array;
use napi_derive::napi;
use rayon::prelude::*;
use serde_json::Value;

// Run a slice of events through one reused ExecutionContext (STL built once, globals swapped per
// event), returning one result per event (null for any event that errors).
fn run_chunk(tokens: &[Value], chunk: &[Value]) -> Vec<Value> {
    let prog = Program::new(tokens.to_vec()).expect("valid program");
    let mut ctx = ExecutionContext::with_defaults(prog);
    let mut out = Vec::with_capacity(chunk.len());
    for ev in chunk {
        ctx.globals = ev.clone();
        out.push(sync_execute(&ctx, false).unwrap_or(Value::Null));
    }
    out
}

/// Run one Hog program (bytecode tokens) against many event-globals. With `parallel`, fan out over
/// a rayon thread pool (one ExecutionContext per worker chunk); otherwise run sequentially on the
/// calling thread with a single reused context. Either way the JS event array is marshalled across
/// the napi boundary first (serde) — that cost is identical for both, and isolating it is the point
/// of the single-threaded measurement.
#[napi]
pub fn execute_batch(program: Value, events: Vec<Value>, parallel: bool) -> Vec<Value> {
    let Value::Array(tokens) = program else {
        return vec![Value::Null; events.len()];
    };

    if !parallel {
        return run_chunk(&tokens, &events);
    }

    const CHUNK: usize = 500;
    events
        .par_chunks(CHUNK)
        .flat_map_iter(|chunk| run_chunk(&tokens, chunk).into_iter())
        .collect()
}

/// The marshalling-lean ingestion path. Instead of crossing the napi boundary as a JS array of
/// objects (which napi must walk element-by-element into `serde_json::Value` — the dominant FFI
/// cost), the caller packs the whole batch into two contiguous `Float64Array`s — every event's
/// `series` back-to-back, plus one `k` per event — which transfer as a single bulk copy. Rust
/// rebuilds each event's globals from the flat slice (native, no boundary crossing) and returns the
/// per-event scalar results as one `Float64Array`. This is workload-shaped (it knows the perf
/// event schema `{series, k}`); a production version would pass each product's fixed schema flat.
#[napi]
pub fn execute_batch_flat(
    program: Value,
    series: Float64Array,
    ks: Float64Array,
    series_len: u32,
    parallel: bool,
) -> Float64Array {
    let Value::Array(tokens) = program else {
        return Float64Array::new(vec![f64::NAN; ks.len()]);
    };
    let series_len = series_len as usize;
    let series: &[f64] = series.as_ref();
    let ks: &[f64] = ks.as_ref();
    let n = ks.len();

    // Reconstruct one event's globals from the flat slice and run it, returning the scalar result.
    let run = |range: std::ops::Range<usize>| -> Vec<f64> {
        let prog = Program::new(tokens.clone()).expect("valid program");
        let mut ctx = ExecutionContext::with_defaults(prog);
        let mut out = Vec::with_capacity(range.len());
        for e in range {
            let base = e * series_len;
            let series_arr: Vec<Value> = series[base..base + series_len]
                .iter()
                .map(|&x| Value::from(x as i64))
                .collect();
            ctx.globals = serde_json::json!({ "series": series_arr, "k": ks[e] as i64 });
            let res = sync_execute(&ctx, false).unwrap_or(Value::Null);
            out.push(
                res.as_i64()
                    .map(|i| i as f64)
                    .or_else(|| res.as_f64())
                    .unwrap_or(f64::NAN),
            );
        }
        out
    };

    const CHUNK: usize = 500;
    let results: Vec<f64> = if parallel {
        let ranges: Vec<std::ops::Range<usize>> = (0..n)
            .step_by(CHUNK)
            .map(|s| s..(s + CHUNK).min(n))
            .collect();
        ranges
            .par_iter()
            .flat_map_iter(|r| run(r.clone()))
            .collect()
    } else {
        run(0..n)
    };

    Float64Array::new(results)
}
