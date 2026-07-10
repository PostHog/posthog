//! Rust HogVM exposed to Node via napi-rs, for executing ingestion transformations.
//!
//! Two entry points: `executeSync` runs one (bytecode, globals) pair on the calling thread — the
//! primary-execution path, equivalent to the Node VM's synchronous exec. `executeBatch` crosses
//! the FFI boundary once per batch, runs off the JS event loop (libuv worker via `AsyncTask`), and
//! can fan out over a rayon thread pool — the shadow-comparison path, where the Node VM stays
//! authoritative and results are only compared.
//!
//! Transformation host functions (`geoipLookup`, `cleanNullValues`, `isKnownBotUserAgent`,
//! `isKnownBotIp`) mirror `nodejs/src/cdp/hog-transformations/transformation-functions.ts`; call
//! `init` once with the mmdb path and bot lists before executing. A host function this binding
//! can't support fails the execution with an `unsupported_ext_fn:<name>` error so the caller can
//! classify it as skipped rather than as a mismatch.

mod exec;
mod ext_fns;
mod geoip;
mod logs;

#[cfg(not(feature = "noop"))]
use napi::bindgen_prelude::AsyncTask;
use napi::Result as NapiResult;
#[cfg(not(feature = "noop"))]
use napi::{Env, Task};
use napi_derive::napi;
use serde_json::Value;

pub use exec::{run_batch, HogExecResult};

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
    events: Vec<Value>,
    parallel: bool,
    max_steps: Option<usize>,
}

// The `noop` test build strips the generated ToNapiValue impls the Task bound needs; tests
// exercise `run_batch` directly.
#[cfg(not(feature = "noop"))]
impl Task for ExecuteBatchTask {
    type Output = Vec<HogExecResult>;
    type JsValue = Vec<HogExecResult>;

    fn compute(&mut self) -> NapiResult<Self::Output> {
        let tokens = std::mem::take(&mut self.tokens);
        let events = std::mem::take(&mut self.events);
        Ok(run_batch(&tokens, &events, self.parallel, self.max_steps))
    }

    fn resolve(&mut self, _env: Env, output: Self::Output) -> NapiResult<Self::JsValue> {
        Ok(output)
    }
}

/// Run one Hog program (bytecode tokens) against many event-globals, off the JS event loop.
/// Returns one structured result per event, in input order.
#[cfg(not(feature = "noop"))]
#[napi(ts_return_type = "Promise<Array<HogExecResult>>")]
pub fn execute_batch(
    program: Value,
    events: Vec<Value>,
    options: Option<ExecuteBatchOptions>,
) -> AsyncTask<ExecuteBatchTask> {
    let options = options.unwrap_or(ExecuteBatchOptions {
        parallel: None,
        max_steps: None,
    });
    let tokens = match program {
        Value::Array(tokens) => tokens,
        _ => Vec::new(),
    };
    AsyncTask::new(ExecuteBatchTask {
        tokens,
        events,
        parallel: options.parallel.unwrap_or(false),
        max_steps: options.max_steps.map(|m| m as usize),
    })
}

#[napi(object)]
pub struct ExecuteSyncOptions {
    /// Step budget for the execution (the Rust VM has no wall-clock timeout).
    pub max_steps: Option<u32>,
}

/// Run one Hog program against one event-globals synchronously on the calling thread. This is the
/// primary-execution path for ingestion transformations: it matches the Node VM's synchronous
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
