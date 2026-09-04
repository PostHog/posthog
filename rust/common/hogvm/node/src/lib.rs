//! Rust HogVM exposed to Node via napi-rs, for executing ingestion transformations.
//!
//! Two entry points: `executeSync` runs one (bytecode, globals) pair synchronously on the calling
//! thread — the per-event execution path, matching the Node VM's synchronous exec with no
//! threadpool round-trip. `executeBatch` runs one program against many event-globals, crossing
//! the FFI boundary once per batch, off the JS event loop (libuv worker via `AsyncTask`), and can
//! fan out over a rayon thread pool.
//!
//! Transformation host functions (`geoipLookup`, `cleanNullValues`, `isKnownBotUserAgent`,
//! `isKnownBotIp`) mirror `nodejs/src/cdp/hog-transformations/transformation-functions.ts`; call
//! `init` once with the mmdb path and bot lists before executing. A host function this binding
//! can't support fails the execution with an `unsupported_ext_fn:<name>` error so the caller can
//! fall back to the Node VM.

// jemalloc: the interpreter's small-allocation churn was a measured ~33% of self-time under
// glibc malloc. Not via `common_alloc`: node dlopens this cdylib after its other native modules,
// and jemalloc's default initial-exec TLS then needs static TLS space the process may already
// have spent, failing the load with "cannot allocate memory in static TLS block". The
// `disable_initial_exec_tls` feature builds jemalloc with the global-dynamic TLS model instead.
#[global_allocator]
static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;

mod exec;
mod ext_fns;
mod geoip;
mod logs;

#[cfg(not(feature = "noop"))]
use napi::bindgen_prelude::{AsyncTask, FromNapiValue};
use napi::Result as NapiResult;
#[cfg(not(feature = "noop"))]
use napi::{Env, JsUnknown, NapiRaw, Task};
use napi_derive::napi;
use serde_json::Value;

pub use exec::{
    build_program, run_batch, run_batch_program, run_batch_salvaged, HogExecResult,
    MARSHAL_ERROR_PREFIX,
};

#[napi(object)]
pub struct InitOptions {
    pub mmdb_path: Option<String>,
    pub known_bot_ua_list: Option<Vec<String>>,
    pub known_bot_ip_list: Option<Vec<String>>,
}

/// Load process-wide state for the transformation host functions. Idempotent; only the first call
/// takes effect.
#[napi]
pub fn init(options: InitOptions) -> NapiResult<()> {
    if let Some(path) = options.mmdb_path {
        geoip::init_geoip(&path).map_err(napi::Error::from_reason)?;
    }
    ext_fns::set_bot_lists(options.known_bot_ua_list, options.known_bot_ip_list);
    Ok(())
}

#[napi(object)]
pub struct ExecuteBatchOptions {
    /// Fan the batch out over a rayon thread pool instead of running sequentially.
    pub parallel: Option<bool>,
    /// Step budget per execution (the Rust VM has no wall-clock timeout).
    pub max_steps: Option<u32>,
}

#[cfg(not(feature = "noop"))]
pub struct ExecuteBatchTask {
    tokens: Vec<Value>,
    events: Vec<Result<Value, String>>,
    parallel: bool,
    max_steps: Option<usize>,
}

// The `noop` test build strips the generated ToNapiValue impls the Task bound needs; tests
// exercise `run_batch`/`run_batch_salvaged` directly.
#[cfg(not(feature = "noop"))]
impl Task for ExecuteBatchTask {
    type Output = Vec<HogExecResult>;
    type JsValue = Vec<HogExecResult>;

    fn compute(&mut self) -> NapiResult<Self::Output> {
        let tokens = std::mem::take(&mut self.tokens);
        let events = std::mem::take(&mut self.events);
        Ok(run_batch_salvaged(
            &tokens,
            events,
            self.parallel,
            self.max_steps,
        ))
    }

    fn resolve(&mut self, _env: Env, output: Self::Output) -> NapiResult<Self::JsValue> {
        Ok(output)
    }
}

/// Run one Hog program (bytecode tokens) against many event-globals, off the JS event loop.
/// Returns one structured result per event, in input order. An event whose globals can't be
/// converted to JSON (e.g. NaN/Infinity numbers) gets a `marshal_error:`-prefixed error result
/// instead of rejecting the whole call.
#[cfg(not(feature = "noop"))]
#[napi(ts_return_type = "Promise<Array<HogExecResult>>")]
pub fn execute_batch(
    env: Env,
    program: Value,
    events: Vec<JsUnknown>,
    options: Option<ExecuteBatchOptions>,
) -> AsyncTask<ExecuteBatchTask> {
    let tokens = match program {
        Value::Array(tokens) => tokens,
        _ => Vec::new(),
    };
    // Convert on the JS thread (JS values can't cross to the worker), one event at a time so an
    // unrepresentable value poisons only its own event, not the batch. Must be the same strict
    // conversion `executeSync`'s arguments go through (throws on NaN/Infinity) — not
    // `Env::from_js_value`, which silently coerces non-finite numbers to null and would give
    // these events different semantics than the sync path's Node VM fallback.
    let events = events
        .into_iter()
        .map(|event| {
            // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
            unsafe { Value::from_napi_value(env.raw(), event.raw()) }.map_err(|e| e.reason)
        })
        .collect();
    let (parallel, max_steps) = match options {
        Some(o) => (o.parallel.unwrap_or(false), o.max_steps.map(|m| m as usize)),
        None => (false, None),
    };
    AsyncTask::new(ExecuteBatchTask {
        tokens,
        events,
        parallel,
        max_steps,
    })
}

#[napi(object)]
pub struct ExecuteSyncOptions {
    /// Step budget for the execution (the Rust VM has no wall-clock timeout).
    pub max_steps: Option<u32>,
}

/// Run one Hog program against one event-globals synchronously on the calling thread. This is the
/// per-event execution path for ingestion transformations: it matches the Node VM's synchronous
/// exec, with no threadpool round-trip.
#[napi]
pub fn execute_sync(
    program: Value,
    globals: Value,
    options: Option<ExecuteSyncOptions>,
) -> HogExecResult {
    let tokens = match program {
        Value::Array(tokens) => tokens,
        _ => Vec::new(),
    };
    let max_steps = options.and_then(|o| o.max_steps).map(|m| m as usize);
    run_batch(&tokens, std::slice::from_ref(&globals), false, max_steps)
        .into_iter()
        .next()
        .expect("run_batch returns one result per event")
}
