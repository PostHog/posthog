//! Rust HogVM exposed to Node via napi-rs, for executing ingestion transformations.
//!
//! `executeSync` runs one (bytecode, globals) pair synchronously on the calling thread — the
//! primary-execution path, matching the Node VM's synchronous exec with no threadpool round-trip.
//! Executions are sub-millisecond and bounded by the step budget, so blocking the event loop is
//! no worse than the Node VM path it replaces.
//!
//! Transformation host functions (`geoipLookup`, `cleanNullValues`, `isKnownBotUserAgent`,
//! `isKnownBotIp`) mirror `nodejs/src/cdp/hog-transformations/transformation-functions.ts`; call
//! `init` once with the mmdb path and bot lists before executing. A host function this binding
//! can't support fails the execution with an `unsupported_ext_fn:<name>` error so the caller can
//! fall back to the Node VM.

// Workspace-standard allocator (jemalloc): the interpreter's small-allocation churn was a
// measured ~33% of self-time under glibc malloc. Applies to this cdylib's Rust allocations,
// same as every other PostHog Rust service.
common_alloc::used!();

mod exec;
mod ext_fns;
mod geoip;
mod logs;

use napi::Result as NapiResult;
use napi_derive::napi;
use serde_json::Value;

pub use exec::{build_program, run_batch, run_batch_program, HogExecResult};

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
    run_batch(&tokens, std::slice::from_ref(&globals), max_steps)
        .into_iter()
        .next()
        .expect("run_batch returns one result per event")
}

// Programs registered once by `registerProgram` — validated and token-decoded at registration,
// executed by handle. Skips the per-invocation JS→Rust marshal + copy + decode of the token
// array, so a hogFunction's bytecode is decoded once and reused across every event.
static REGISTERED_PROGRAMS: std::sync::RwLock<Vec<Result<hogvm::Program, String>>> =
    std::sync::RwLock::new(Vec::new());

/// Register a program's bytecode once; returns a handle for `executeRegisteredSync`. Invalid
/// bytecode still gets a handle — executions through it report the validation error.
#[napi]
pub fn register_program(program: Value) -> u32 {
    let tokens = match program {
        Value::Array(tokens) => tokens,
        _ => Vec::new(),
    };
    let mut programs = REGISTERED_PROGRAMS.write().expect("registry poisoned");
    programs.push(exec::build_program(tokens));
    (programs.len() - 1) as u32
}

// A registered Program clone is two Arc bumps; cloning out keeps the lock scope minimal.
fn get_registered(handle: u32) -> Result<hogvm::Program, String> {
    REGISTERED_PROGRAMS
        .read()
        .expect("registry poisoned")
        .get(handle as usize)
        .cloned()
        .unwrap_or_else(|| Err(format!("unknown program handle {handle}")))
}

fn error_results(error: &str, count: usize) -> Vec<HogExecResult> {
    (0..count)
        .map(|_| HogExecResult {
            result: None,
            error: Some(error.to_string()),
            duration_us: 0.0,
            logs: Vec::new(),
            logs_truncated: false,
        })
        .collect()
}

/// `executeSync` against a program registered with `registerProgram`.
#[napi]
pub fn execute_registered_sync(
    handle: u32,
    globals: Value,
    options: Option<ExecuteSyncOptions>,
) -> HogExecResult {
    let max_steps = options.and_then(|o| o.max_steps).map(|m| m as usize);
    let results = match get_registered(handle) {
        Ok(program) => exec::run_batch_program(&program, std::slice::from_ref(&globals), max_steps),
        Err(e) => error_results(&e, 1),
    };
    results.into_iter().next().expect("one result per event")
}

/// Batch variant: one napi crossing for many events, amortizing the marshalling overhead.
#[napi]
pub fn execute_registered_batch_sync(
    handle: u32,
    events: Vec<Value>,
    options: Option<ExecuteSyncOptions>,
) -> Vec<HogExecResult> {
    let max_steps = options.and_then(|o| o.max_steps).map(|m| m as usize);
    match get_registered(handle) {
        Ok(program) => exec::run_batch_program(&program, &events, max_steps),
        Err(e) => error_results(&e, events.len()),
    }
}
