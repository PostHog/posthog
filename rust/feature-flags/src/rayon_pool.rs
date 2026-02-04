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
//! # Safety cap
//!
//! If `EVAL_NUM_THREADS` exceeds `std::thread::available_parallelism()` (which respects
//! container CPU limits on Linux), the value is capped and a warning is logged. This
//! prevents misconfiguration from causing thread over-subscription.

use std::{env, sync::LazyLock};

const DEFAULT_EVAL_NUM_THREADS: usize = 1;
const EVAL_NUM_THREADS_ENV: &str = "EVAL_NUM_THREADS";

/// Result of resolving the thread count from environment and available parallelism.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ResolvedThreadCount {
    /// Valid env var value within available parallelism.
    Configured(usize),
    /// Env var value exceeded available parallelism, capped.
    Capped { requested: usize, available: usize },
    /// No env var, invalid value, or zero; using default.
    Default(usize),
}

impl ResolvedThreadCount {
    fn get(&self) -> usize {
        match self {
            Self::Configured(n) | Self::Default(n) => *n,
            Self::Capped { available, .. } => *available,
        }
    }
}

/// Resolves the number of threads from an optional env var value and available parallelism.
fn resolve_thread_count(env_value: Option<&str>, available: usize) -> ResolvedThreadCount {
    let Some(requested) = env_value
        .and_then(|s| s.parse::<usize>().ok())
        .filter(|&n| n > 0)
    else {
        return ResolvedThreadCount::Default(DEFAULT_EVAL_NUM_THREADS);
    };

    if requested > available {
        ResolvedThreadCount::Capped {
            requested,
            available,
        }
    } else {
        ResolvedThreadCount::Configured(requested)
    }
}

/// Returns the available parallelism, respecting container CPU limits on Linux.
fn available_parallelism() -> usize {
    std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or_else(|_| {
            tracing::warn!("Failed to determine available parallelism, falling back to 1");
            1
        })
}

static EVAL_POOL: LazyLock<rayon::ThreadPool> = LazyLock::new(|| {
    let available = available_parallelism();
    let env_value = env::var(EVAL_NUM_THREADS_ENV).ok();
    let resolved = resolve_thread_count(env_value.as_deref(), available);
    let num_threads = resolved.get();

    if let ResolvedThreadCount::Capped { requested, .. } = resolved {
        tracing::warn!(
            requested,
            available,
            num_threads,
            "{EVAL_NUM_THREADS_ENV} exceeds available parallelism, capping"
        );
    }

    tracing::info!(
        num_threads,
        available,
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
/// 2. Installing the closure on the dedicated rayon pool
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

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[rstest]
    #[case::valid_within_limit(Some("4"), 8, ResolvedThreadCount::Configured(4))]
    #[case::valid_at_limit(Some("8"), 8, ResolvedThreadCount::Configured(8))]
    #[case::exceeds_available(Some("16"), 8, ResolvedThreadCount::Capped { requested: 16, available: 8 })]
    #[case::no_env_var(None, 8, ResolvedThreadCount::Default(DEFAULT_EVAL_NUM_THREADS))]
    #[case::empty_string(Some(""), 8, ResolvedThreadCount::Default(DEFAULT_EVAL_NUM_THREADS))]
    #[case::non_numeric(Some("abc"), 8, ResolvedThreadCount::Default(DEFAULT_EVAL_NUM_THREADS))]
    #[case::zero_value(Some("0"), 8, ResolvedThreadCount::Default(DEFAULT_EVAL_NUM_THREADS))]
    #[case::negative_value(Some("-1"), 8, ResolvedThreadCount::Default(DEFAULT_EVAL_NUM_THREADS))]
    #[case::whitespace_only(Some("   "), 8, ResolvedThreadCount::Default(DEFAULT_EVAL_NUM_THREADS))]
    #[case::float_value(Some("4.5"), 8, ResolvedThreadCount::Default(DEFAULT_EVAL_NUM_THREADS))]
    fn test_resolve_thread_count(
        #[case] env_value: Option<&str>,
        #[case] available: usize,
        #[case] expected: ResolvedThreadCount,
    ) {
        assert_eq!(resolve_thread_count(env_value, available), expected);
    }

    #[rstest]
    #[case::configured(ResolvedThreadCount::Configured(4), 4)]
    #[case::capped(ResolvedThreadCount::Capped { requested: 16, available: 8 }, 8)]
    #[case::default(ResolvedThreadCount::Default(1), 1)]
    fn test_resolved_thread_count_get(
        #[case] resolved: ResolvedThreadCount,
        #[case] expected: usize,
    ) {
        assert_eq!(resolved.get(), expected);
    }
}
