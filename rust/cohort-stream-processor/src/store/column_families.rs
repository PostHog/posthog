//! Column-family registry.

use rocksdb::{
    BlockBasedIndexType, BlockBasedOptions, Cache, ColumnFamilyDescriptor, DBCompressionType,
    Options,
};

use super::rocks::StoreConfig;
use super::secondary_index::{full_merge, partial_merge, PERSON_INDEX_MERGE_OPERATOR_NAME};

/// Stage 1 per-leaf state.
pub const CF_STAGE1: &str = "cf_stage1";
/// Per-person secondary index.
pub const CF_PERSON_INDEX: &str = "cf_person_index";
/// Stage 2 membership.
pub const CF_STAGE2: &str = "cf_stage2";
/// Merge Phase 1 idempotence: short-circuits re-drained merge messages.
pub const CF_MERGE_DRAINS_APPLIED: &str = "cf_merge_drains_applied";
/// Phase 1 durability outbox: holds packaged merges until the transfer produce is acked.
pub const CF_PENDING_TRANSFERS: &str = "cf_pending_transfers";
/// Phase 2 idempotence: keyed by the triggering merge message's coordinates.
pub const CF_MERGE_APPLIED: &str = "cf_merge_applied";
/// Post-merge straggler redirect: records merged-away persons for late-event redirection.
pub const CF_MERGE_TOMBSTONES: &str = "cf_merge_tombstones";

const BLOOM_FILTER_BITS_PER_KEY: f64 = 10.0;

/// Per-CF memtable count, pinned so the memtable-memory multiplier (CF × write_buffer_bytes × this)
/// can't silently double if the write-buffer size is raised.
const MAX_WRITE_BUFFER_NUMBER: i32 = 2;

/// Column family enum.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub enum Cf {
    Stage1,
    PersonIndex,
    Stage2,
    MergeDrainsApplied,
    PendingTransfers,
    MergeApplied,
    MergeTombstones,
}

impl Cf {
    pub const ALL: [Cf; 7] = [
        Cf::Stage1,
        Cf::PersonIndex,
        Cf::Stage2,
        Cf::MergeDrainsApplied,
        Cf::PendingTransfers,
        Cf::MergeApplied,
        Cf::MergeTombstones,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Cf::Stage1 => CF_STAGE1,
            Cf::PersonIndex => CF_PERSON_INDEX,
            Cf::Stage2 => CF_STAGE2,
            Cf::MergeDrainsApplied => CF_MERGE_DRAINS_APPLIED,
            Cf::PendingTransfers => CF_PENDING_TRANSFERS,
            Cf::MergeApplied => CF_MERGE_APPLIED,
            Cf::MergeTombstones => CF_MERGE_TOMBSTONES,
        }
    }
}

/// A column family safe for raw `put` (excludes `cf_person_index`).
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub enum OpaqueCf {
    Stage1,
    Stage2,
}

impl OpaqueCf {
    pub const fn cf(self) -> Cf {
        match self {
            OpaqueCf::Stage1 => Cf::Stage1,
            OpaqueCf::Stage2 => Cf::Stage2,
        }
    }
}

impl From<OpaqueCf> for Cf {
    fn from(cf: OpaqueCf) -> Cf {
        cf.cf()
    }
}

pub fn descriptors(config: &StoreConfig, cache: &Cache) -> Vec<ColumnFamilyDescriptor> {
    Cf::ALL
        .iter()
        .map(|&cf| ColumnFamilyDescriptor::new(cf.as_str(), cf_options(cf, config, cache)))
        .collect()
}

fn cf_options(cf: Cf, config: &StoreConfig, cache: &Cache) -> Options {
    let mut block_opts = BlockBasedOptions::default();
    block_opts.set_block_cache(cache);
    block_opts.set_bloom_filter(BLOOM_FILTER_BITS_PER_KEY, false);

    if config.tuned_block_options {
        // Cache index/filter blocks and partition them behind a two-level index (required by
        // partitioned filters) so point lookups short-circuit on the bloom. Whole-key filtering
        // matches the point-lookup pattern; there is no prefix extractor.
        block_opts.set_cache_index_and_filter_blocks(true);
        block_opts.set_pin_l0_filter_and_index_blocks_in_cache(true);
        block_opts.set_pin_top_level_index_and_filter(true);
        block_opts.set_partition_filters(true);
        block_opts.set_index_type(BlockBasedIndexType::TwoLevelIndexSearch);
        block_opts.set_whole_key_filtering(true);
    }

    let mut opts = Options::default();
    opts.set_block_based_table_factory(&block_opts);
    opts.set_compression_type(DBCompressionType::Lz4);
    opts.set_write_buffer_size(config.write_buffer_bytes);
    opts.set_max_write_buffer_number(MAX_WRITE_BUFFER_NUMBER);

    // CF options don't inherit from the DB options, so compaction controls must be set per-CF.
    if config.compact_on_deletion {
        opts.add_compact_on_deletion_collector_factory(
            config.compact_on_deletion_window,
            config.compact_on_deletion_num_dels_trigger,
            config.compact_on_deletion_ratio,
        );
    }
    if config.periodic_compaction_seconds != 0 {
        opts.set_periodic_compaction_seconds(config.periodic_compaction_seconds);
    }

    match cf {
        Cf::PersonIndex => {
            opts.set_merge_operator(PERSON_INDEX_MERGE_OPERATOR_NAME, full_merge, partial_merge);
        }
        Cf::Stage1
        | Cf::Stage2
        | Cf::MergeDrainsApplied
        | Cf::PendingTransfers
        | Cf::MergeApplied
        | Cf::MergeTombstones => {}
    }
    opts
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cf_names_are_stable() {
        assert_eq!(Cf::Stage1.as_str(), "cf_stage1");
        assert_eq!(Cf::PersonIndex.as_str(), "cf_person_index");
        assert_eq!(Cf::Stage2.as_str(), "cf_stage2");
        assert_eq!(Cf::MergeDrainsApplied.as_str(), "cf_merge_drains_applied");
        assert_eq!(Cf::PendingTransfers.as_str(), "cf_pending_transfers");
        assert_eq!(Cf::MergeApplied.as_str(), "cf_merge_applied");
        assert_eq!(Cf::MergeTombstones.as_str(), "cf_merge_tombstones");
    }

    #[test]
    fn all_is_exhaustive_and_unique() {
        assert_eq!(Cf::ALL.len(), 7);
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
