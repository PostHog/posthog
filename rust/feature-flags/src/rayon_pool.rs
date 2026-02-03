use std::{env, sync::LazyLock};

const DEFAULT_EVAL_NUM_THREADS: usize = 3;
const EVAL_NUM_THREADS: &str = "EVAL_NUM_THREADS";

static EVAL_POOL: LazyLock<rayon::ThreadPool> = LazyLock::new(|| {
    let num_threads = env::var(EVAL_NUM_THREADS)
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(DEFAULT_EVAL_NUM_THREADS);

    rayon::ThreadPoolBuilder::new()
        .num_threads(num_threads)
        .thread_name(|i| format!("flag-eval-{i}"))
        .build()
        .expect("Failed to build Rayon flag evaluation thread pool")
});

/// Execute CPU-bound parallel work on the evaluation thread pool.
///
/// This handles the tokio/rayon interaction correctly by:
/// 1. Using `block_in_place` to avoid blocking tokio worker threads
/// 2. Installing the closure on the dedicated rayon pool
///
/// # Example
/// ```
/// let results = eval_parallel(|| {
///     items.par_iter().map(|item| process(item)).collect()
/// });
/// ```
pub fn eval_parallel<F, R>(f: F) -> R
where
    F: FnOnce() -> R + Send,
    R: Send,
{
    tokio::task::block_in_place(|| EVAL_POOL.install(f))
}
