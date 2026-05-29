//! Column-family registry (TDD §2.5:300-302).
//!
//! PR 1.2 ships the three state CFs. The four cross-partition-merge CFs (`cf_merge_*`, §4.5.1)
//! are PR 3.1 and slot into [`cf_options`] as one match arm each.

use rocksdb::{BlockBasedOptions, Cache, ColumnFamilyDescriptor, DBCompressionType, Options};

use super::rocks::StoreConfig;
use super::secondary_index::{full_merge, partial_merge, PERSON_INDEX_MERGE_OPERATOR_NAME};

/// Stage 1 per-leaf state: `(partition_id, team_id, leaf_state_key, person_id) → StatefulRecord`.
pub const CF_STAGE1: &str = "cf_stage1";
/// Per-person secondary index used by cross-partition merge migration: `… → set<LeafStateKey>`.
pub const CF_PERSON_INDEX: &str = "cf_person_index";
/// Stage 2 membership: `(partition_id, team_id, cohort_id, person_id) → Stage2State`.
pub const CF_STAGE2: &str = "cf_stage2";

/// Bloom filter bits per key — 10 bits ≈ 1% false-positive rate (matches kafka-deduplicator).
const BLOOM_FILTER_BITS_PER_KEY: f64 = 10.0;

/// The state column families this process owns. Iteration order is the canonical order for
/// fan-out operations (e.g. [`super::rocks::CohortStore::delete_partition`]).
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub enum Cf {
    Stage1,
    PersonIndex,
    Stage2,
}

impl Cf {
    /// Every column family, in canonical order.
    pub const ALL: [Cf; 3] = [Cf::Stage1, Cf::PersonIndex, Cf::Stage2];

    /// The on-disk name RocksDB keys this CF by.
    pub const fn as_str(self) -> &'static str {
        match self {
            Cf::Stage1 => CF_STAGE1,
            Cf::PersonIndex => CF_PERSON_INDEX,
            Cf::Stage2 => CF_STAGE2,
        }
    }
}

/// Build the descriptor for each CF. The shared block `cache` is attached to every CF's block
/// options; RocksDB clones and retains it for the DB's lifetime, so the caller need not.
pub fn descriptors(config: &StoreConfig, cache: &Cache) -> Vec<ColumnFamilyDescriptor> {
    Cf::ALL
        .iter()
        .map(|&cf| ColumnFamilyDescriptor::new(cf.as_str(), cf_options(cf, config, cache)))
        .collect()
}

/// Per-CF options: sound shared defaults (lz4 + bloom + sized block cache), plus the merge
/// operator on `cf_person_index` only. Compaction/write-buffer-manager tuning is deferred to
/// the §5.1 M9 measurement — this ships defaults, not premature knobs.
fn cf_options(cf: Cf, config: &StoreConfig, cache: &Cache) -> Options {
    let mut block_opts = BlockBasedOptions::default();
    block_opts.set_block_cache(cache);
    block_opts.set_bloom_filter(BLOOM_FILTER_BITS_PER_KEY, false);

    let mut opts = Options::default();
    opts.set_block_based_table_factory(&block_opts);
    opts.set_compression_type(DBCompressionType::Lz4);
    opts.set_write_buffer_size(config.write_buffer_bytes);

    match cf {
        Cf::PersonIndex => {
            opts.set_merge_operator(PERSON_INDEX_MERGE_OPERATOR_NAME, full_merge, partial_merge);
        }
        Cf::Stage1 | Cf::Stage2 => {}
    }
    opts
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cf_names_match_the_tdd() {
        assert_eq!(Cf::Stage1.as_str(), "cf_stage1");
        assert_eq!(Cf::PersonIndex.as_str(), "cf_person_index");
        assert_eq!(Cf::Stage2.as_str(), "cf_stage2");
    }

    #[test]
    fn all_is_exhaustive_and_unique() {
        assert_eq!(Cf::ALL.len(), 3);
        for cf in Cf::ALL {
            assert!(Cf::ALL.iter().filter(|&&c| c == cf).count() == 1);
        }
    }

    #[test]
    fn descriptors_cover_every_cf() {
        let config = StoreConfig::default();
        let cache = Cache::new_lru_cache(1024 * 1024);
        let descriptors = descriptors(&config, &cache);
        assert_eq!(descriptors.len(), Cf::ALL.len());
    }
}
