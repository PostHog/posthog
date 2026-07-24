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
//! is fixed everywhere -- partition -> file -> bytes, local before global at each level
//! -- so the two layers cannot deadlock against each other.
//!
//! Limits are injected as an [`Arc<ProcessLimits>`] rather than read from a hidden
//! static, so tests can build isolated instances; the binding crate passes
//! [`ProcessLimits::global()`], a lazily-initialised process-wide singleton configured
//! from environment variables.

use std::sync::{Arc, OnceLock};

use tokio::sync::{OwnedSemaphorePermit, Semaphore};

use crate::errors::{Error, Result};

/// Default process-wide cap on concurrently rewriting partitions.
pub const DEFAULT_PROCESS_MAX_PARALLEL_PARTITIONS: usize = 8;
/// Default process-wide cap on concurrently streaming file readers.
pub const DEFAULT_PROCESS_MAX_PARALLEL_FILES: usize = 16;
/// Default process-wide cap on decompressed survivor bytes in flight.
pub const DEFAULT_PROCESS_MAX_BUFFERED_BYTES: usize = 256 * 1024 * 1024;
/// Default ceiling for the source-size guard (resident source + estimated PK set).
pub const DEFAULT_MAX_SOURCE_BYTES: usize = 2 * 1024 * 1024 * 1024;

/// Process-wide concurrency budgets shared by every concurrent `upsert` call.
pub struct ProcessLimits {
    partitions: Arc<Semaphore>,
    files: Arc<Semaphore>,
    buffer: Arc<Semaphore>,
    /// Capacity of `buffer` in KiB (tokio permits are u32-denominated).
    buffer_cap_kb: u32,
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

impl ProcessLimits {
    /// Build limits with explicit capacities. Zero capacities are clamped to 1 (a
    /// zero-permit semaphore would deadlock every upsert forever).
    pub fn new(max_partitions: usize, max_files: usize, max_buffered_bytes: usize) -> Self {
        let cap_kb = (max_buffered_bytes / 1024).clamp(1, u32::MAX as usize) as u32;
        Self {
            partitions: Arc::new(Semaphore::new(max_partitions.max(1))),
            files: Arc::new(Semaphore::new(max_files.max(1))),
            buffer: Arc::new(Semaphore::new(cap_kb as usize)),
            buffer_cap_kb: cap_kb,
        }
    }

    /// Capacities from `DELTALITE_PROCESS_MAX_PARALLEL_PARTITIONS`,
    /// `DELTALITE_PROCESS_MAX_PARALLEL_FILES` and
    /// `DELTALITE_PROCESS_MAX_BUFFERED_BYTES`, with the module defaults as fallback.
    pub fn from_env() -> Self {
        Self::new(
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
        )
    }

    /// The process-wide singleton, initialised from the environment on first use.
    pub fn global() -> &'static Arc<ProcessLimits> {
        static GLOBAL: OnceLock<Arc<ProcessLimits>> = OnceLock::new();
        GLOBAL.get_or_init(|| Arc::new(ProcessLimits::from_env()))
    }

    /// Acquire one process-global partition permit.
    pub async fn acquire_partition(&self) -> Result<OwnedSemaphorePermit> {
        self.partitions
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| Error::Generic("process partition semaphore closed".into()))
    }

    /// Acquire one process-global file-reader permit.
    pub async fn acquire_file(&self) -> Result<OwnedSemaphorePermit> {
        self.files
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| Error::Generic("process file semaphore closed".into()))
    }

    /// Acquire `kb` KiB of the process-global byte budget; requests larger than the
    /// whole budget are capped so an oversized batch still makes progress.
    pub async fn acquire_buffer_kb(&self, kb: u32) -> Result<OwnedSemaphorePermit> {
        self.buffer
            .clone()
            .acquire_many_owned(kb.min(self.buffer_cap_kb).max(1))
            .await
            .map_err(|_| Error::Generic("process byte-budget semaphore closed".into()))
    }

    /// Capacity of the byte budget in KiB.
    pub fn buffer_cap_kb(&self) -> u32 {
        self.buffer_cap_kb
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

    #[tokio::test]
    async fn zero_capacities_are_clamped_to_one() {
        let limits = ProcessLimits::new(0, 0, 0);
        let _p = limits.acquire_partition().await.unwrap();
        let _f = limits.acquire_file().await.unwrap();
        let _b = limits.acquire_buffer_kb(1).await.unwrap();
    }
}
