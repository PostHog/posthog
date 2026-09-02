//! Store-filesystem utilization sampling — the seed consumer's disk-backpressure input.
//!
//! The [`StoreStatsSweeper`](crate::observability::store_stats::StoreStatsSweeper) samples and
//! publishes into a [`SharedDiskUtilization`]; the seed consumer reads the latest snapshot each
//! cycle. `None` (no successful sample yet, the last sample failed, or the last sample is older
//! than the staleness bound) is **fail-open**: absence can never pause — a broken or wedged probe
//! must never wedge seeding.

use std::io;
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use arc_swap::ArcSwapOption;

/// One filesystem sample. `available_bytes` is `f_bavail`-based (bytes available to unprivileged
/// writes), matching df. Kubelet's `used_bytes` is `f_bfree`-based, so on a filesystem with a
/// root reserve this reads a few points higher than kubelet's used/capacity ratio.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct DiskUtilization {
    pub total_bytes: u64,
    pub available_bytes: u64,
}

impl DiskUtilization {
    /// Used share in percent, 0–100. Root-reserved blocks count as used (the `f_bavail` view), so
    /// this reads slightly higher than raw free space — conservative in the pause direction.
    pub fn used_pct(&self) -> f64 {
        if self.total_bytes == 0 {
            return 0.0;
        }
        let used = self.total_bytes.saturating_sub(self.available_bytes);
        (used as f64 / self.total_bytes as f64) * 100.0
    }
}

/// Sample the filesystem holding `path` via `statvfs`. Byte sizes use `f_frsize` (the fragment
/// size), which is the unit `f_blocks`/`f_bavail` are counted in — `f_bsize` is only the
/// preferred I/O size and differs on some filesystems.
#[cfg(unix)]
// The statvfs field widths are platform-dependent (u32 vs u64), so these widening conversions
// are identity on some targets.
#[allow(clippy::useless_conversion)]
pub fn sample_store_filesystem(path: &Path) -> io::Result<DiskUtilization> {
    let stat = nix::sys::statvfs::statvfs(path)
        .map_err(|errno| io::Error::from_raw_os_error(errno as i32))?;
    let fragment_size = u64::from(stat.fragment_size());
    Ok(DiskUtilization {
        total_bytes: u64::from(stat.blocks()).saturating_mul(fragment_size),
        available_bytes: u64::from(stat.blocks_available()).saturating_mul(fragment_size),
    })
}

#[cfg(not(unix))]
pub fn sample_store_filesystem(_path: &Path) -> io::Result<DiskUtilization> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "statvfs is unavailable on this platform",
    ))
}

/// The latest disk sample: sweeper-written, seed-consumer-read. A sample older than
/// `max_sample_age` reads as `None`, so a wedged sweep loop cannot latch the gate on a stale
/// reading — staleness fails open like any other probe failure.
#[derive(Debug)]
pub struct SharedDiskUtilization {
    sample: ArcSwapOption<StampedSample>,
    max_sample_age: Duration,
}

#[derive(Debug)]
struct StampedSample {
    utilization: DiskUtilization,
    sampled_at: Instant,
}

impl SharedDiskUtilization {
    pub fn new(max_sample_age: Duration) -> Self {
        Self {
            sample: ArcSwapOption::empty(),
            max_sample_age,
        }
    }

    /// Publish the newest sample; `None` records a failed sample (fail-open for the gate).
    pub fn publish(&self, sample: Option<DiskUtilization>) {
        self.sample.store(sample.map(|utilization| {
            Arc::new(StampedSample {
                utilization,
                sampled_at: Instant::now(),
            })
        }));
    }

    pub fn latest(&self) -> Option<DiskUtilization> {
        let sample = self.sample.load();
        let sample = sample.as_deref()?;
        (sample.sampled_at.elapsed() < self.max_sample_age).then_some(sample.utilization)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Pins the percentage arithmetic (an available/total swap or a fragment-size mixup would show
    /// up as a nonsense share) and the zero-total guard.
    #[test]
    fn used_pct_is_the_unavailable_share_and_zero_total_is_zero() {
        let sample = DiskUtilization {
            total_bytes: 100,
            available_bytes: 25,
        };
        assert_eq!(sample.used_pct(), 75.0);

        let empty = DiskUtilization {
            total_bytes: 0,
            available_bytes: 0,
        };
        assert_eq!(empty.used_pct(), 0.0);

        // Available beyond total (never expected from statvfs) saturates to 0% used, not a panic.
        let odd = DiskUtilization {
            total_bytes: 10,
            available_bytes: 20,
        };
        assert_eq!(odd.used_pct(), 0.0);
    }

    /// Catches unit/field mixups (`f_bsize` vs `f_frsize`, blocks vs bytes): a real filesystem
    /// must report a sane, internally-consistent sample.
    #[cfg(unix)]
    #[test]
    fn sample_store_filesystem_on_tempdir() {
        let dir = tempfile::tempdir().unwrap();
        let sample = sample_store_filesystem(dir.path()).unwrap();
        assert!(sample.total_bytes > 0, "a real filesystem has capacity");
        assert!(
            sample.available_bytes <= sample.total_bytes,
            "available cannot exceed total",
        );
        let pct = sample.used_pct();
        assert!((0.0..=100.0).contains(&pct), "share out of range: {pct}");
    }

    #[test]
    fn shared_snapshot_publishes_and_clears() {
        let shared = SharedDiskUtilization::new(Duration::MAX);
        assert_eq!(shared.latest(), None, "fail-open before any sample");

        let sample = DiskUtilization {
            total_bytes: 50,
            available_bytes: 10,
        };
        shared.publish(Some(sample));
        assert_eq!(shared.latest(), Some(sample));

        shared.publish(None);
        assert_eq!(
            shared.latest(),
            None,
            "a failed sample returns to fail-open"
        );
    }

    /// A wedged sweep loop stops republishing; the last sample must expire into `None` rather
    /// than latch the gate on a stale reading.
    #[test]
    fn a_sample_older_than_the_bound_reads_as_none() {
        let shared = SharedDiskUtilization::new(Duration::ZERO);
        shared.publish(Some(DiskUtilization {
            total_bytes: 50,
            available_bytes: 10,
        }));
        assert_eq!(shared.latest(), None, "at or past the bound is stale");
    }
}
