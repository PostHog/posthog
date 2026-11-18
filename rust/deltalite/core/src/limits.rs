//! Process-global concurrency limits and the source-size guard.
//!
//! The per-call semaphores (`max_parallel_partitions`, `max_parallel_files`,
//! `max_buffered_bytes`) are constructed inside `upsert()`, so alone they bound one
//! *call*.
//! Production runs ~15 concurrent upserts as Temporal activity threads inside ONE worker
//! process, so a "global" 64 MB byte budget was really 15 x 64 MB, and the process could
//! host `15 x mpp x mpf` concurrent file readers on the shared tokio runtime.
//!
//! Every acquisition therefore goes through BOTH a per-call semaphore (preserving the
//! per-call knobs) and a process-global one from this module, so the process-level bound
//! means what it says regardless of how many upserts run concurrently. Acquisition order
//! is fixed everywhere -- partition -> file -> fetch -> bytes, local before global at
//! each level -- so the two layers cannot deadlock against each other.
//!
//! The fetch budget covers the *compressed* row-group bytes a Parquet reader pulls from
//! storage before it can decode anything: the async reader fetches every projected
//! column chunk of a row group in one go and holds them until that row group is decoded,
//! so a reader of a single-row-group file holds the whole file. The decode budget
//! (`bytes`) never saw those bytes. A reader takes its fetch permit once per file, before
//! the first byte of data is fetched, and keeps it until the stream is dropped; it may
//! take decode permits while holding it, but nothing ever waits on a fetch permit while
//! holding decode budget, so the two budgets cannot form a cycle.
//!
//! Limits are injected as an [`Arc<ProcessLimits>`] rather than read from a hidden
//! static, so tests can build isolated instances; the binding crate passes
//! [`ProcessLimits::global()`], a lazily-initialised process-wide singleton configured
//! from environment variables.
//!
//! Each wait on a process-wide budget has an upper bound
//! (`DELTALITE_PERMIT_WAIT_TIMEOUT_SECS`). The waits are fair, so one call that holds
//! permits and stops making progress blocks every later waiter. The bound changes that
//! hang into an [`Error::Timeout`] that names the budget, and
//! [`ProcessLimits::snapshot`] shows how much of each budget is free.

use std::future::Future;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, OnceLock};
use std::time::Duration;

use tokio::sync::{OwnedSemaphorePermit, Semaphore};

use crate::errors::{Error, Result};

/// Default process-wide cap on concurrently rewriting partitions.
pub const DEFAULT_PROCESS_MAX_PARALLEL_PARTITIONS: usize = 8;
/// Default process-wide cap on concurrently streaming file readers.
pub const DEFAULT_PROCESS_MAX_PARALLEL_FILES: usize = 16;
/// Default process-wide cap on decompressed survivor bytes in flight.
pub const DEFAULT_PROCESS_MAX_BUFFERED_BYTES: usize = 256 * 1024 * 1024;
/// Default process-wide cap on compressed row-group bytes held by readers.
pub const DEFAULT_PROCESS_MAX_FETCH_BYTES: usize = 256 * 1024 * 1024;
/// Default ceiling for the source-size guard (resident source + estimated PK set).
pub const DEFAULT_MAX_SOURCE_BYTES: usize = 2 * 1024 * 1024 * 1024;
/// Default upper bound on one wait for a process-wide budget. It is much longer than a
/// normal wait, which ends when the holders finish their I/O, so it fires only when a
/// holder does not make progress.
pub const DEFAULT_PERMIT_WAIT_TIMEOUT: Duration = Duration::from_secs(30 * 60);
/// Environment override for [`DEFAULT_PERMIT_WAIT_TIMEOUT`], in seconds; `0` removes the
/// bound.
pub const PERMIT_WAIT_TIMEOUT_ENV: &str = "DELTALITE_PERMIT_WAIT_TIMEOUT_SECS";

/// One of the four process-wide budgets.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Budget {
    Partitions,
    Files,
    /// Decoded bytes in flight, in KiB.
    Buffer,
    /// Compressed row-group bytes held by readers, in KiB.
    Fetch,
}

impl Budget {
    /// Name of the budget in errors and in [`LimitsSnapshot`] consumers.
    pub fn name(self) -> &'static str {
        match self {
            Budget::Partitions => "partitions",
            Budget::Files => "files",
            Budget::Buffer => "buffer_kb",
            Budget::Fetch => "fetch_kb",
        }
    }
}

/// Free and total permits of one budget, and the acquisitions that wait for it. A
/// waiter that needs more permits than are free takes the free ones and waits for the
/// rest, so `available` can be 0 while a part of the budget belongs to a waiter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BudgetSnapshot {
    pub available: usize,
    pub total: usize,
    pub waiters: usize,
}

/// [`BudgetSnapshot`] of each process-wide budget.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LimitsSnapshot {
    pub partitions: BudgetSnapshot,
    pub files: BudgetSnapshot,
    pub buffer_kb: BudgetSnapshot,
    pub fetch_kb: BudgetSnapshot,
}

impl LimitsSnapshot {
    pub fn get(&self, budget: Budget) -> BudgetSnapshot {
        match budget {
            Budget::Partitions => self.partitions,
            Budget::Files => self.files,
            Budget::Buffer => self.buffer_kb,
            Budget::Fetch => self.fetch_kb,
        }
    }
}

/// One process-wide semaphore and the count of the acquisitions that wait for it.
#[derive(Debug)]
struct Pool {
    semaphore: Arc<Semaphore>,
    total: u32,
    waiters: AtomicUsize,
}

impl Pool {
    fn new(total: u32) -> Self {
        Self {
            semaphore: Arc::new(Semaphore::new(total as usize)),
            total,
            waiters: AtomicUsize::new(0),
        }
    }

    fn snapshot(&self) -> BudgetSnapshot {
        BudgetSnapshot {
            available: self.semaphore.available_permits(),
            total: self.total as usize,
            waiters: self.waiters.load(Ordering::Relaxed),
        }
    }
}

/// Counts one waiter of a [`Pool`] until dropped, also when the wait is cancelled.
struct Waiting<'a>(&'a AtomicUsize);

impl<'a> Waiting<'a> {
    fn new(waiters: &'a AtomicUsize) -> Self {
        waiters.fetch_add(1, Ordering::Relaxed);
        Self(waiters)
    }
}

impl Drop for Waiting<'_> {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::Relaxed);
    }
}

/// Process-wide concurrency budgets shared by every concurrent `upsert` call.
#[derive(Debug)]
pub struct ProcessLimits {
    partitions: Pool,
    files: Pool,
    /// Capacity in KiB (tokio permits are u32-denominated).
    buffer: Pool,
    /// Capacity in KiB.
    fetch: Pool,
    /// Upper bound on one wait for any of the budgets; `None` waits without a bound.
    wait_timeout: Option<Duration>,
}

fn cap_kb(bytes: usize) -> u32 {
    (bytes / 1024).clamp(1, u32::MAX as usize) as u32
}

/// Seconds from the environment variable `name` as a duration: unset or invalid gives
/// `default`, and `0` gives `None` (no bound).
pub(crate) fn env_secs(name: &str, default: Duration) -> Option<Duration> {
    secs_setting(name, std::env::var(name).ok().as_deref(), default)
}

fn secs_setting(name: &str, value: Option<&str>, default: Duration) -> Option<Duration> {
    let Some(v) = value else {
        return Some(default);
    };
    match v.trim().parse::<u64>() {
        Ok(0) => None,
        Ok(n) => Some(Duration::from_secs(n)),
        Err(_) => {
            tracing::warn!(var = name, value = %v, "invalid value, using default");
            Some(default)
        }
    }
}

pub(crate) fn env_usize(name: &str, default: usize) -> usize {
    match std::env::var(name) {
        Ok(v) => match v.trim().parse::<usize>() {
            Ok(n) if n > 0 => n,
            _ => {
                tracing::warn!(var = name, value = %v, "invalid value, using default");
                default
            }
        },
        Err(_) => default,
    }
}

/// Whether the setting `value` of an on/off kill switch keeps the feature on: `0`,
/// `false`, `off` and `no` turn it off; unset or any other value keeps it on.
pub(crate) fn switch_setting(value: Option<&str>) -> bool {
    match value {
        Some(v) => !matches!(
            v.trim().to_ascii_lowercase().as_str(),
            "0" | "false" | "off" | "no"
        ),
        None => true,
    }
}

/// [`switch_setting`] of the environment variable `name`.
pub(crate) fn env_switch(name: &str) -> bool {
    switch_setting(std::env::var(name).ok().as_deref())
}

impl ProcessLimits {
    /// Build limits with explicit capacities and the default fetch budget. Zero
    /// capacities are clamped to 1 (a zero-permit semaphore would deadlock every upsert
    /// forever).
    pub fn new(max_partitions: usize, max_files: usize, max_buffered_bytes: usize) -> Self {
        Self::with_fetch(
            max_partitions,
            max_files,
            max_buffered_bytes,
            DEFAULT_PROCESS_MAX_FETCH_BYTES,
        )
    }

    /// [`ProcessLimits::new`] with an explicit fetch budget.
    pub fn with_fetch(
        max_partitions: usize,
        max_files: usize,
        max_buffered_bytes: usize,
        max_fetch_bytes: usize,
    ) -> Self {
        let count = |n: usize| n.clamp(1, u32::MAX as usize) as u32;
        Self {
            partitions: Pool::new(count(max_partitions)),
            files: Pool::new(count(max_files)),
            buffer: Pool::new(cap_kb(max_buffered_bytes)),
            fetch: Pool::new(cap_kb(max_fetch_bytes)),
            wait_timeout: Some(DEFAULT_PERMIT_WAIT_TIMEOUT),
        }
    }

    /// Replace the upper bound on one wait for a budget; `None` removes it.
    pub fn with_wait_timeout(mut self, wait_timeout: Option<Duration>) -> Self {
        self.wait_timeout = wait_timeout;
        self
    }

    /// Capacities from `DELTALITE_PROCESS_MAX_PARALLEL_PARTITIONS`,
    /// `DELTALITE_PROCESS_MAX_PARALLEL_FILES`, `DELTALITE_PROCESS_MAX_BUFFERED_BYTES` and
    /// `DELTALITE_PROCESS_MAX_FETCH_BYTES`, and the wait bound from
    /// [`PERMIT_WAIT_TIMEOUT_ENV`], with the module defaults as fallback.
    pub fn from_env() -> Self {
        Self::with_fetch(
            env_usize(
                "DELTALITE_PROCESS_MAX_PARALLEL_PARTITIONS",
                DEFAULT_PROCESS_MAX_PARALLEL_PARTITIONS,
            ),
            env_usize(
                "DELTALITE_PROCESS_MAX_PARALLEL_FILES",
                DEFAULT_PROCESS_MAX_PARALLEL_FILES,
            ),
            env_usize(
                "DELTALITE_PROCESS_MAX_BUFFERED_BYTES",
                DEFAULT_PROCESS_MAX_BUFFERED_BYTES,
            ),
            env_usize(
                "DELTALITE_PROCESS_MAX_FETCH_BYTES",
                DEFAULT_PROCESS_MAX_FETCH_BYTES,
            ),
        )
        .with_wait_timeout(env_secs(
            PERMIT_WAIT_TIMEOUT_ENV,
            DEFAULT_PERMIT_WAIT_TIMEOUT,
        ))
    }

    /// The process-wide singleton, initialised from the environment on first use.
    pub fn global() -> &'static Arc<ProcessLimits> {
        static GLOBAL: OnceLock<Arc<ProcessLimits>> = OnceLock::new();
        GLOBAL.get_or_init(|| Arc::new(ProcessLimits::from_env()))
    }

    fn pool(&self, budget: Budget) -> &Pool {
        match budget {
            Budget::Partitions => &self.partitions,
            Budget::Files => &self.files,
            Budget::Buffer => &self.buffer,
            Budget::Fetch => &self.fetch,
        }
    }

    /// Free and total permits of every budget, and the acquisitions that wait for each.
    pub fn snapshot(&self) -> LimitsSnapshot {
        LimitsSnapshot {
            partitions: self.partitions.snapshot(),
            files: self.files.snapshot(),
            buffer_kb: self.buffer.snapshot(),
            fetch_kb: self.fetch.snapshot(),
        }
    }

    /// Take `n` permits of `budget`, or fail with [`Error::Timeout`] after the wait bound.
    /// A cancelled acquisition gives back the permits it had collected.
    async fn acquire(&self, budget: Budget, n: u32) -> Result<OwnedSemaphorePermit> {
        let pool = self.pool(budget);
        let _waiting = Waiting::new(&pool.waiters);
        let wait = pool.semaphore.clone().acquire_many_owned(n);
        let closed = || Error::Generic(format!("process {} semaphore closed", budget.name()));
        let Some(limit) = self.wait_timeout else {
            return wait.await.map_err(|_| closed());
        };
        match tokio::time::timeout(limit, wait).await {
            Ok(permit) => permit.map_err(|_| closed()),
            Err(_) => Err(self.timeout_error(budget, n, limit)),
        }
    }

    fn timeout_error(&self, budget: Budget, wanted: u32, limit: Duration) -> Error {
        let s = self.pool(budget).snapshot();
        Error::Timeout(format!(
            "waited more than {}s for {wanted} permit(s) of the process-wide {} budget: \
             {} of {} free, {} waiter(s). A call that holds this budget does not make \
             progress. {PERMIT_WAIT_TIMEOUT_ENV} sets this bound.",
            limit.as_secs(),
            budget.name(),
            s.available,
            s.total,
            s.waiters,
        ))
    }

    /// Run `wait`, an acquisition that ends in a wait for `budget`, under the same bound
    /// as one process-wide wait. Callers use it to bound a per-call wait that comes
    /// before the process-wide one.
    pub(crate) async fn bounded<T>(
        &self,
        budget: Budget,
        wanted: u32,
        wait: impl Future<Output = Result<T>>,
    ) -> Result<T> {
        let Some(limit) = self.wait_timeout else {
            return wait.await;
        };
        match tokio::time::timeout(limit, wait).await {
            Ok(r) => r,
            Err(_) => Err(self.timeout_error(budget, wanted, limit)),
        }
    }

    /// Acquire one process-global partition permit.
    pub async fn acquire_partition(&self) -> Result<OwnedSemaphorePermit> {
        self.acquire(Budget::Partitions, 1).await
    }

    /// Acquire one process-global file-reader permit.
    pub async fn acquire_file(&self) -> Result<OwnedSemaphorePermit> {
        self.acquire(Budget::Files, 1).await
    }

    /// Acquire `kb` KiB of the process-global byte budget; requests larger than the
    /// whole budget are capped so an oversized batch still makes progress.
    pub async fn acquire_buffer_kb(&self, kb: u32) -> Result<OwnedSemaphorePermit> {
        self.acquire(Budget::Buffer, kb.min(self.buffer.total).max(1))
            .await
    }

    /// Try to reserve `kb` KiB without waiting. Callers that can fall back to a
    /// streaming path use this to avoid deadlocking when several operations each hold
    /// part of the process budget and need one more allocation to finish.
    pub fn try_acquire_buffer_kb(&self, kb: u32) -> Option<OwnedSemaphorePermit> {
        self.buffer
            .semaphore
            .clone()
            .try_acquire_many_owned(kb.min(self.buffer.total).max(1))
            .ok()
    }

    /// Capacity of the byte budget in KiB.
    pub fn buffer_cap_kb(&self) -> u32 {
        self.buffer.total
    }

    /// Acquire `kb` KiB of the process-global fetch budget, capped at its capacity so a
    /// row group larger than the whole budget still proceeds (alone).
    pub async fn acquire_fetch_kb(&self, kb: u32) -> Result<OwnedSemaphorePermit> {
        self.acquire(Budget::Fetch, kb.min(self.fetch.total).max(1))
            .await
    }

    /// Capacity of the fetch budget in KiB.
    pub fn fetch_cap_kb(&self) -> u32 {
        self.fetch.total
    }
}

/// Estimate of what an upsert will keep resident for the whole rewrite: the cast source
/// batches (shared with the caller, but counted -- deltalite holds them alive) plus the
/// row-encoded PK hash set (~key bytes + per-entry overhead).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SourceFootprint {
    /// Total Arrow buffer bytes across the cast source batches.
    pub source_bytes: usize,
    /// Estimated resident bytes of the PK hash set once built.
    pub pk_set_bytes: usize,
}

impl SourceFootprint {
    /// Combined estimate compared against the guard ceiling.
    pub fn total(&self) -> usize {
        self.source_bytes.saturating_add(self.pk_set_bytes)
    }
}

/// Per-`HashSet`-entry overhead: `Vec<u8>` header (24) + hash-table slot bookkeeping.
const PK_ENTRY_OVERHEAD: usize = 48;

/// Estimate the PK-set size from the source's PK columns: encoded key width is
/// approximated by the columns' in-memory bytes per row, which upper-bounds the
/// row-encoding for fixed-width types and tracks it closely for strings.
pub fn estimate_pk_set_bytes(pk_bytes: usize, rows: usize) -> usize {
    pk_bytes.saturating_add(rows.saturating_mul(PK_ENTRY_OVERHEAD))
}

/// Resolve the guard ceiling: explicit argument > `DELTALITE_MAX_SOURCE_BYTES` env >
/// [`DEFAULT_MAX_SOURCE_BYTES`]. An explicit `Some(0)` disables the guard.
pub fn resolve_max_source_bytes(explicit: Option<usize>) -> Option<usize> {
    let v = match explicit {
        Some(v) => v,
        None => env_usize("DELTALITE_MAX_SOURCE_BYTES", DEFAULT_MAX_SOURCE_BYTES),
    };
    (v > 0).then_some(v)
}

/// Reject a source whose estimated footprint exceeds the ceiling. This is the clean
/// front-door failure that replaces "RSS grows until the pod OOMs": the target side of
/// an upsert is memory-bounded by construction, the source side is linear in the
/// caller's batch, and nothing else refuses an oversized one.
pub fn check_source_size(footprint: &SourceFootprint, ceiling: Option<usize>) -> Result<()> {
    let Some(max) = ceiling else { return Ok(()) };
    if footprint.total() > max {
        return Err(Error::SourceTooLarge(format!(
            "source batch is too large for this upsert: ~{} MB resident ({} MB of \
             source data + ~{} MB of primary-key set) exceeds the {} MB ceiling. \
             Split the batch into smaller pieces, or raise the ceiling via the \
             max_source_bytes argument / DELTALITE_MAX_SOURCE_BYTES.",
            footprint.total() / (1024 * 1024),
            footprint.source_bytes / (1024 * 1024),
            footprint.pk_set_bytes / (1024 * 1024),
            max / (1024 * 1024),
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn total_saturates_instead_of_overflowing() {
        let f = SourceFootprint {
            source_bytes: usize::MAX,
            pk_set_bytes: 10,
        };
        assert_eq!(f.total(), usize::MAX);
    }

    #[test]
    fn guard_rejects_only_above_the_ceiling() {
        let small = SourceFootprint {
            source_bytes: 100,
            pk_set_bytes: 50,
        };
        assert!(check_source_size(&small, Some(150)).is_ok());
        let err = check_source_size(&small, Some(149)).unwrap_err();
        assert!(matches!(err, Error::SourceTooLarge(_)), "{err}");
        assert_eq!(err.kind(), "source_too_large");
    }

    #[test]
    fn guard_disabled_by_none_ceiling() {
        let huge = SourceFootprint {
            source_bytes: usize::MAX,
            pk_set_bytes: 0,
        };
        assert!(check_source_size(&huge, None).is_ok());
    }

    #[test]
    fn explicit_zero_disables_and_explicit_value_wins() {
        assert_eq!(resolve_max_source_bytes(Some(0)), None);
        assert_eq!(resolve_max_source_bytes(Some(123)), Some(123));
        // No env var set in tests: default applies.
        assert_eq!(
            resolve_max_source_bytes(None),
            Some(DEFAULT_MAX_SOURCE_BYTES)
        );
    }

    #[test]
    fn pk_estimate_includes_per_entry_overhead() {
        assert_eq!(estimate_pk_set_bytes(1000, 10), 1000 + 480);
        assert_eq!(estimate_pk_set_bytes(0, 0), 0);
    }

    #[tokio::test]
    async fn buffer_requests_are_capped_at_capacity() {
        let limits = ProcessLimits::new(1, 1, 64 * 1024); // 64 KiB
                                                          // A request far larger than the budget still succeeds (capped), so an
                                                          // oversized batch can make progress instead of deadlocking.
        let permit = limits.acquire_buffer_kb(u32::MAX).await.unwrap();
        drop(permit);
        let p1 = limits.acquire_buffer_kb(32).await.unwrap();
        let p2 = limits.acquire_buffer_kb(32).await.unwrap();
        // Budget exhausted: a third acquire must not be immediately ready.
        let pending = tokio::time::timeout(
            std::time::Duration::from_millis(50),
            limits.acquire_buffer_kb(1),
        )
        .await;
        assert!(pending.is_err(), "budget should be exhausted");
        drop(p1);
        drop(p2);
    }

    async fn take(limits: &ProcessLimits, budget: Budget, n: u32) -> Result<OwnedSemaphorePermit> {
        match budget {
            Budget::Partitions => limits.acquire_partition().await,
            Budget::Files => limits.acquire_file().await,
            Budget::Buffer => limits.acquire_buffer_kb(n).await,
            Budget::Fetch => limits.acquire_fetch_kb(n).await,
        }
    }

    const ALL_BUDGETS: [Budget; 4] = [
        Budget::Partitions,
        Budget::Files,
        Budget::Buffer,
        Budget::Fetch,
    ];

    #[tokio::test(start_paused = true)]
    async fn a_wait_past_the_bound_fails_names_the_budget_and_leaves_no_waiter() {
        for budget in ALL_BUDGETS {
            let limits = ProcessLimits::with_fetch(1, 1, 64 * 1024, 64 * 1024)
                .with_wait_timeout(Some(Duration::from_secs(30)));
            let total = limits.snapshot().get(budget).total as u32;
            let held = take(&limits, budget, total).await.unwrap();

            let err = take(&limits, budget, 1).await.unwrap_err();
            assert_eq!(err.kind(), "timeout", "{budget:?}");
            let msg = err.to_string();
            assert!(msg.contains(budget.name()), "{msg}");
            assert!(msg.contains(&format!("0 of {total} free")), "{msg}");
            assert!(msg.contains("1 waiter(s)"), "{msg}");
            assert_eq!(limits.snapshot().get(budget).waiters, 0, "{budget:?}");

            drop(held);
            assert!(take(&limits, budget, 1).await.is_ok(), "{budget:?}");
        }
    }

    #[tokio::test(start_paused = true)]
    async fn no_bound_waits_past_the_default_bound() {
        let limits = ProcessLimits::with_fetch(1, 1, 1024, 1024).with_wait_timeout(None);
        let _held = limits.acquire_partition().await.unwrap();
        let wait =
            tokio::time::timeout(DEFAULT_PERMIT_WAIT_TIMEOUT * 2, limits.acquire_partition()).await;
        assert!(wait.is_err(), "the acquisition must still wait");
    }

    #[test]
    fn wait_bound_setting_parses_seconds_and_zero_turns_it_off() {
        let default = Duration::from_secs(1800);
        let cases = [
            (None, Some(default)),
            (Some("0"), None),
            (Some(" 45 "), Some(Duration::from_secs(45))),
            (Some("-1"), Some(default)),
            (Some("ten"), Some(default)),
        ];
        for (value, expected) in cases {
            assert_eq!(secs_setting("X", value, default), expected, "{value:?}");
        }
    }

    #[tokio::test]
    async fn snapshot_reports_free_permits_and_waiters() {
        let limits = Arc::new(ProcessLimits::with_fetch(2, 3, 8 * 1024, 4 * 1024));
        let full = limits.snapshot();
        for (budget, total) in [
            (Budget::Partitions, 2),
            (Budget::Files, 3),
            (Budget::Buffer, 8),
            (Budget::Fetch, 4),
        ] {
            let s = full.get(budget);
            assert_eq!(
                (s.available, s.total, s.waiters),
                (total, total, 0),
                "{budget:?}"
            );
        }

        let held = limits.acquire_buffer_kb(6).await.unwrap();
        let waiter = tokio::spawn({
            let limits = limits.clone();
            async move { limits.acquire_buffer_kb(4).await.map(drop) }
        });
        while limits.snapshot().buffer_kb.waiters == 0 {
            tokio::task::yield_now().await;
        }
        assert_eq!(limits.snapshot().buffer_kb.waiters, 1);

        drop(held);
        waiter.await.unwrap().unwrap();
        assert_eq!(limits.snapshot(), full);
    }

    #[tokio::test]
    async fn zero_capacities_are_clamped_to_one() {
        let limits = ProcessLimits::with_fetch(0, 0, 0, 0);
        let _p = limits.acquire_partition().await.unwrap();
        let _f = limits.acquire_file().await.unwrap();
        let _b = limits.acquire_buffer_kb(1).await.unwrap();
        let _x = limits.acquire_fetch_kb(1).await.unwrap();
    }

    #[tokio::test]
    async fn fetch_requests_are_capped_and_exclusive_when_oversized() {
        let limits = ProcessLimits::with_fetch(1, 1, 1024 * 1024, 64 * 1024);
        assert_eq!(limits.fetch_cap_kb(), 64);
        // Larger than the whole budget: proceeds, holding all of it.
        let whole = limits.acquire_fetch_kb(10_000).await.unwrap();
        let pending = tokio::time::timeout(
            std::time::Duration::from_millis(50),
            limits.acquire_fetch_kb(1),
        )
        .await;
        assert!(pending.is_err(), "an oversized holder must run alone");
        drop(whole);
        let _p = limits.acquire_fetch_kb(1).await.unwrap();
    }
}
