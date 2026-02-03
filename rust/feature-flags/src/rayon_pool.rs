//! Dedicated thread pool for CPU-bound parallel flag evaluation.
//!
//! # Thread budget
//!
//! The total active threads should stay within the CFS quota to avoid throttling:
//!
//! | Pool | Threads | Purpose |
//! |------|---------|---------|
//! | Tokio workers | N (set via `TOKIO_WORKER_THREADS`) | Async I/O, connection pools, request handling |
//! | Rayon eval | M (set via `EVAL_NUM_THREADS`) | CPU-bound parallel flag evaluation |
//!
//! Not all threads are CPU-hot simultaneously: tokio threads mostly wait on I/O, and rayon
//! threads only run during `eval_parallel()` calls. The budget can slightly exceed the quota
//! as long as peak concurrent CPU usage stays within limits.
//!
//! # Important: Set TOKIO_WORKER_THREADS
//!
//! Tokio's `#[tokio::main]` defaults to `num_cpus`, which reflects the HOST CPU count (8-16),
//! not the container's CFS quota. We should set `TOKIO_WORKER_THREADS` in production to match
//! the CFS quota, otherwise tokio will create more threads than the container can efficiently run.

use std::{env, sync::LazyLock};

const DEFAULT_EVAL_NUM_THREADS: usize = 3;
const EVAL_NUM_THREADS_ENV: &str = "EVAL_NUM_THREADS";

static EVAL_POOL: LazyLock<rayon::ThreadPool> = LazyLock::new(|| {
    let num_threads = env::var(EVAL_NUM_THREADS_ENV)
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(DEFAULT_EVAL_NUM_THREADS);

    tracing::info!(
        num_threads,
        "Initializing rayon evaluation thread pool (set {EVAL_NUM_THREADS_ENV} to override)"
    );

    rayon::ThreadPoolBuilder::new()
        .num_threads(num_threads)
        .thread_name(|i| format!("flag-eval-{i}"))
        .build()
        .expect("Failed to build Rayon flag evaluation thread pool")
});

/// Execute CPU-bound parallel work on the evaluation thread pool.
///
/// This handles the tokio/rayon interaction correctly by:
/// 1. Using `block_in_place` to signal tokio that this thread will block
/// 2. Installing the closure on the dedicated, right-sized rayon pool
///
/// The `block_in_place` call allows tokio to move pending tasks to other workers,
/// keeping the async runtime responsive for connection pool operations and I/O.
///
/// # Example
///
/// ```ignore
/// let results = eval_parallel(|| {
///     flags.par_iter().map(|flag| evaluate(flag)).collect()
/// });
/// ```
///
/// # Why not `spawn_blocking`?
///
/// `spawn_blocking` requires `'static + Send` bounds, which would force cloning
/// the entire `FeatureFlagMatcher` and all flag data for every evaluation.
/// `block_in_place` runs in-place on the current thread, allowing borrows.
pub fn eval_parallel<F, R>(f: F) -> R
where
    F: FnOnce() -> R + Send,
    R: Send,
{
    tokio::task::block_in_place(|| EVAL_POOL.install(f))
}
