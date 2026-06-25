//! Rust HogVM exposed to Node via napi-rs.
//!
//! `executeBatch` is the realistic Rust-from-Node ingestion path: Node hands a batch of events
//! (their globals) across the FFI boundary, Rust runs the same Hog program over all of them, and
//! returns the per-event results. The `parallel` flag selects single-threaded execution (which
//! isolates the pure boundary-marshalling cost) vs a `rayon` thread pool (native parallelism). The
//! harness measures both so the FFI rows are comparable to the in-process single/parallel rows.

use hogvm::{sync_execute, ExecutionContext, Program};
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
