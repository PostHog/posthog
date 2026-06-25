//! Rust HogVM exposed to Node via napi-rs.
//!
//! `executeBatch` is the realistic Rust-from-Node ingestion path: Node hands a batch of events
//! (their globals) across the FFI boundary, Rust runs the same Hog program over all of them on its
//! own `rayon` thread pool, and returns the per-event results. The win vs pure Node is the native
//! parallelism; the cost is marshalling the batch across the boundary — the harness measures both.

use hogvm::{sync_execute, ExecutionContext, Program};
use napi_derive::napi;
use rayon::prelude::*;
use serde_json::Value;

/// Run one Hog program (bytecode tokens) against many event-globals, in parallel.
/// Returns one result per event (null for any event that errors). One ExecutionContext is built
/// per worker chunk and its globals are swapped per event, so the STL map is not rebuilt per event.
#[napi]
pub fn execute_batch(program: Value, events: Vec<Value>) -> Vec<Value> {
    let Value::Array(tokens) = program else {
        return vec![Value::Null; events.len()];
    };

    const CHUNK: usize = 500;
    events
        .par_chunks(CHUNK)
        .flat_map_iter(|chunk| {
            let prog = Program::new(tokens.clone()).expect("valid program");
            let mut ctx = ExecutionContext::with_defaults(prog);
            let mut out = Vec::with_capacity(chunk.len());
            for ev in chunk {
                ctx.globals = ev.clone();
                out.push(sync_execute(&ctx, false).unwrap_or(Value::Null));
            }
            out.into_iter()
        })
        .collect()
}
