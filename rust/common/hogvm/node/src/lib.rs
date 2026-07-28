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

// Programs registered once by `registerProgram` — validated and token-decoded at registration,
// executed by handle. Skips the per-invocation JS→Rust marshal + copy + decode of the token
// array, so a hogFunction's bytecode is decoded once and reused across every event.
//
// Slots are reused after `releaseProgram`, so a long-lived process that re-registers programs as
// hog functions are edited or evicted doesn't grow the registry without bound. Callers own handle
// lifecycle: a handle must not be executed after it is released (doing so is not unsafe — it
// either errors as unknown or, once the slot is reused, runs the newer program — but it is a
// caller bug).
#[derive(Default)]
struct ProgramRegistry {
    slots: Vec<Option<Result<hogvm::Program, String>>>,
    free: Vec<u32>,
}

static REGISTERED_PROGRAMS: std::sync::RwLock<ProgramRegistry> =
    std::sync::RwLock::new(ProgramRegistry {
        slots: Vec::new(),
        free: Vec::new(),
    });

/// Register a program's bytecode once; returns a handle for `executeRegisteredSync`. Invalid
/// bytecode still gets a handle — executions through it report the validation error.
#[napi]
pub fn register_program(program: Value) -> u32 {
    let tokens = match program {
        Value::Array(tokens) => tokens,
        _ => Vec::new(),
    };
    let built = exec::build_program(tokens);
    let mut registry = REGISTERED_PROGRAMS.write().expect("registry poisoned");
    if let Some(handle) = registry.free.pop() {
        registry.slots[handle as usize] = Some(built);
        return handle;
    }
    registry.slots.push(Some(built));
    (registry.slots.len() - 1) as u32
}

/// Drop a registered program and free its slot for reuse. Releasing an unknown or already-released
/// handle is a no-op, so a caller retrying a cleanup can't corrupt the free list.
#[napi]
pub fn release_program(handle: u32) {
    let mut registry = REGISTERED_PROGRAMS.write().expect("registry poisoned");
    let Some(slot) = registry.slots.get_mut(handle as usize) else {
        return;
    };
    if slot.take().is_some() {
        registry.free.push(handle);
    }
}

// A registered Program clone is two Arc bumps; cloning out keeps the lock scope minimal.
fn get_registered(handle: u32) -> Result<hogvm::Program, String> {
    REGISTERED_PROGRAMS
        .read()
        .expect("registry poisoned")
        .slots
        .get(handle as usize)
        .cloned()
        .flatten()
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
        Ok(program) => {
            exec::run_batch_program(&program, std::slice::from_ref(&globals), false, max_steps)
        }
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
        Ok(program) => exec::run_batch_program(&program, &events, false, max_steps),
        Err(e) => error_results(&e, events.len()),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    // The registry is process-global, so these tests must not run concurrently with each other:
    // they assert on which slot a registration lands in, and cargo runs tests in parallel threads.
    static REGISTRY_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    fn registry_guard() -> std::sync::MutexGuard<'static, ()> {
        // A panicking test poisons the lock; the registry itself stays consistent, so recover
        // rather than cascading a failure into every other test in this module.
        REGISTRY_TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner())
    }

    // "_H" header, version 1, push int 1, RETURN
    fn program(value: i64) -> Value {
        json!(["_H", 1, 33, value, 38])
    }

    #[test]
    fn released_handles_are_reused_so_the_registry_stays_bounded() {
        let _guard = registry_guard();
        // Without slot reuse the registry grows by one entry per re-registration, which for a
        // long-lived process re-registering edited hog functions is an unbounded leak.
        let first = register_program(program(1));
        release_program(first);
        let second = register_program(program(2));
        assert_eq!(first, second);

        // The reused slot must hold the new program, not the released one.
        let result = execute_registered_sync(second, json!({}), None);
        assert_eq!(result.error, None);
        assert_eq!(result.result, Some(json!(2)));
    }

    #[test]
    fn executing_a_released_handle_errors_instead_of_running_a_stale_program() {
        let _guard = registry_guard();
        let handle = register_program(program(1));
        release_program(handle);

        let result = execute_registered_sync(handle, json!({}), None);
        assert!(result.result.is_none());
        assert!(result
            .error
            .as_deref()
            .unwrap()
            .contains("unknown program handle"));
    }

    #[test]
    fn releasing_twice_does_not_hand_the_same_slot_out_to_two_registrations() {
        let _guard = registry_guard();
        // A double release used to be able to push the same handle onto the free list twice, so
        // two live registrations would alias one slot and execute each other's programs.
        let handle = register_program(program(1));
        release_program(handle);
        release_program(handle);

        let a = register_program(program(1));
        let b = register_program(program(2));
        assert_ne!(a, b);

        assert_eq!(
            execute_registered_sync(a, json!({}), None).result,
            Some(json!(1))
        );
        assert_eq!(
            execute_registered_sync(b, json!({}), None).result,
            Some(json!(2))
        );
    }
}
