//! Periodic publisher of RocksDB store statistics (block-cache tickers, cache usage, per-CF sizes)
//! via the shared sweep machinery. Read latency is timed inline in [`crate::store::rocks`].

use async_trait::async_trait;
use metrics::{counter, gauge};

use crate::observability::metrics::{
    STORE_BLOCK_CACHE_DATA_HITS_TOTAL, STORE_BLOCK_CACHE_DATA_MISSES_TOTAL,
    STORE_BLOCK_CACHE_FILTER_HITS_TOTAL, STORE_BLOCK_CACHE_FILTER_MISSES_TOTAL,
    STORE_BLOCK_CACHE_HITS_TOTAL, STORE_BLOCK_CACHE_INDEX_HITS_TOTAL,
    STORE_BLOCK_CACHE_INDEX_MISSES_TOTAL, STORE_BLOCK_CACHE_MISSES_TOTAL,
    STORE_BLOCK_CACHE_USAGE_BYTES, STORE_BLOOM_FILTER_USEFUL_TOTAL, STORE_ESTIMATE_NUM_KEYS,
    STORE_LIVE_DATA_BYTES, STORE_SST_BYTES,
};
use crate::store::CohortStore;
use crate::sweep::Sweeper;

/// Publishes [`CohortStore::stats_snapshot`] onto metrics once per sweep tick, driven by
/// [`run_sweep_loop`](crate::sweep::run_sweep_loop).
pub struct StoreStatsSweeper {
    store: CohortStore,
}

impl StoreStatsSweeper {
    pub fn new(store: CohortStore) -> Self {
        Self { store }
    }
}

#[async_trait]
impl Sweeper for StoreStatsSweeper {
    async fn run_once(&self) {
        let stats = self.store.stats_snapshot();

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
