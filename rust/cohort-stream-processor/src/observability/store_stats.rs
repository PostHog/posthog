//! Periodic publisher of RocksDB store statistics (block-cache tickers, cache usage, per-CF sizes)
//! and the store filesystem's utilization, via the shared sweep machinery. Read latency is timed
//! inline in [`crate::store::rocks`].

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use async_trait::async_trait;
use metrics::{counter, gauge};
use tracing::{debug, warn};

use crate::observability::disk::{sample_store_filesystem, SharedDiskUtilization};
use crate::observability::metrics::{
    STORE_BLOCK_CACHE_DATA_HITS_TOTAL, STORE_BLOCK_CACHE_DATA_MISSES_TOTAL,
    STORE_BLOCK_CACHE_FILTER_HITS_TOTAL, STORE_BLOCK_CACHE_FILTER_MISSES_TOTAL,
    STORE_BLOCK_CACHE_HITS_TOTAL, STORE_BLOCK_CACHE_INDEX_HITS_TOTAL,
    STORE_BLOCK_CACHE_INDEX_MISSES_TOTAL, STORE_BLOCK_CACHE_MISSES_TOTAL,
    STORE_BLOCK_CACHE_USAGE_BYTES, STORE_BLOOM_FILTER_USEFUL_TOTAL, STORE_DISK_AVAILABLE_BYTES,
    STORE_DISK_SAMPLE_ERRORS_TOTAL, STORE_DISK_TOTAL_BYTES, STORE_DISK_UTILIZATION_PCT,
    STORE_ESTIMATE_NUM_KEYS, STORE_LIVE_DATA_BYTES, STORE_SST_BYTES,
};
use crate::store::StoreHandle;
use crate::sweep::Sweeper;

/// Samples the store filesystem each stats tick, publishing the `store_disk_*` gauges plus the
/// shared snapshot the seed consumer's disk gate reads.
pub struct DiskProbe {
    store_path: PathBuf,
    shared: Arc<SharedDiskUtilization>,
    /// At most one statvfs call outstanding: a hung mount must not leak one blocking thread per
    /// tick until the pool is exhausted.
    in_flight: Arc<AtomicBool>,
}

impl DiskProbe {
    pub fn new(store_path: PathBuf, shared: Arc<SharedDiskUtilization>) -> Self {
        Self {
            store_path,
            shared,
            in_flight: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Detached: the sample publishes from inside the blocking task, so a hung statvfs can never
    /// wedge the sweep loop or delay the store snapshot — the shared snapshot's staleness bound
    /// turns the missing refresh into fail-open, and the skipped ticks keep the error counter
    /// climbing so the wedge is visible.
    fn run_once(&self) {
        if self.in_flight.swap(true, Ordering::AcqRel) {
            counter!(STORE_DISK_SAMPLE_ERRORS_TOTAL).increment(1);
            warn!(path = %self.store_path.display(), "previous store filesystem sample still running; skipping this tick");
            return;
        }
        let path = self.store_path.clone();
        let shared = self.shared.clone();
        let in_flight = self.in_flight.clone();
        tokio::task::spawn_blocking(move || {
            let sample = match sample_store_filesystem(&path) {
                Ok(sample) => {
                    gauge!(STORE_DISK_TOTAL_BYTES).set(sample.total_bytes as f64);
                    gauge!(STORE_DISK_AVAILABLE_BYTES).set(sample.available_bytes as f64);
                    gauge!(STORE_DISK_UTILIZATION_PCT).set(sample.used_pct());
                    Some(sample)
                }
                Err(err) => {
                    counter!(STORE_DISK_SAMPLE_ERRORS_TOTAL).increment(1);
                    warn!(error = %err, path = %path.display(), "store filesystem sample failed; the seed disk gate stays fail-open");
                    None
                }
            };
            shared.publish(sample);
            in_flight.store(false, Ordering::Release);
        });
    }
}

/// Publishes [`CohortStore::stats_snapshot`](crate::store::CohortStore::stats_snapshot) onto metrics
/// once per sweep tick, driven by [`run_sweep_loop`](crate::sweep::run_sweep_loop). Goes through the
/// [`StoreHandle`] so its many RocksDB property reads run off the runtime threads.
pub struct StoreStatsSweeper {
    handle: StoreHandle,
    disk: DiskProbe,
}

impl StoreStatsSweeper {
    pub fn new(handle: StoreHandle, disk: DiskProbe) -> Self {
        Self { handle, disk }
    }
}

#[async_trait]
impl Sweeper for StoreStatsSweeper {
    async fn run_once(&self) {
        // Fire-and-forget, so neither the disk sample nor the store snapshot can delay or
        // suppress the other.
        self.disk.run_once();

        let stats = match self.handle.stats_snapshot().await {
            Ok(stats) => stats,
            // Only teardown cancellation errors here; the next tick (if any) re-reads.
            Err(err) => {
                debug!(error = %err, "store stats snapshot skipped (offload cancelled)");
                return;
            }
        };

        // Tickers are cumulative, so publish them verbatim with `absolute`.
        for (name, value) in [
            (STORE_BLOCK_CACHE_HITS_TOTAL, stats.block_cache_hits),
            (STORE_BLOCK_CACHE_MISSES_TOTAL, stats.block_cache_misses),
            (
                STORE_BLOCK_CACHE_DATA_HITS_TOTAL,
                stats.block_cache_data_hits,
            ),
            (
                STORE_BLOCK_CACHE_DATA_MISSES_TOTAL,
                stats.block_cache_data_misses,
            ),
            (
                STORE_BLOCK_CACHE_INDEX_HITS_TOTAL,
                stats.block_cache_index_hits,
            ),
            (
                STORE_BLOCK_CACHE_INDEX_MISSES_TOTAL,
                stats.block_cache_index_misses,
            ),
            (
                STORE_BLOCK_CACHE_FILTER_HITS_TOTAL,
                stats.block_cache_filter_hits,
            ),
            (
                STORE_BLOCK_CACHE_FILTER_MISSES_TOTAL,
                stats.block_cache_filter_misses,
            ),
            (STORE_BLOOM_FILTER_USEFUL_TOTAL, stats.bloom_filter_useful),
        ] {
            counter!(name).absolute(value);
        }

        gauge!(STORE_BLOCK_CACHE_USAGE_BYTES).set(stats.block_cache_usage_bytes as f64);

        for cf in &stats.per_cf {
            // `cf.as_str()` is `&'static str`, so the label is static — no `Arc<str>` needed.
            let label = cf.cf.as_str();
            gauge!(STORE_SST_BYTES, "cf" => label).set(cf.sst_bytes as f64);
            gauge!(STORE_LIVE_DATA_BYTES, "cf" => label).set(cf.live_data_bytes as f64);
            gauge!(STORE_ESTIMATE_NUM_KEYS, "cf" => label).set(cf.num_keys as f64);
        }
    }
}
