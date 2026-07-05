//! Column-family registry.

use rocksdb::{
    BlockBasedIndexType, BlockBasedOptions, Cache, ColumnFamilyDescriptor, DBCompressionType,
    Options, SliceTransform,
};

use super::keyspace::PERSON_PREFIX_LEN;
use super::rocks::StoreConfig;
use super::ttl_filter::PersonRecordTtlFactory;

/// Person-clustered per-leaf state: `(partition, team, person, lsk)`.
pub const CF_BEHAVIORAL: &str = "cf_behavioral";
/// One durable record per person, keyed `(partition, team, person)` — collapses a person's
/// person-property leaf state into a single value.
pub const CF_PERSON_RECORDS: &str = "cf_person_records";
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
/// Store-wide metadata (schema version guard). Not partition-prefixed.
pub const CF_META: &str = "cf_meta";

const BLOOM_FILTER_BITS_PER_KEY: f64 = 10.0;

/// Fraction of each `cf_behavioral` memtable reserved for a prefix bloom, so a person-prefix scan can
/// skip memtables that hold none of the person's rows. Small: the on-disk prefix bloom does the heavy
/// lifting; this only trims the write-buffer edge.
const BEHAVIORAL_MEMTABLE_PREFIX_BLOOM_RATIO: f64 = 0.05;

/// Per-CF memtable count, pinned so the memtable-memory multiplier (CF × write_buffer_bytes × this)
/// can't silently double if the write-buffer size is raised.
const MAX_WRITE_BUFFER_NUMBER: i32 = 2;

/// Column family enum.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub enum Cf {
    Behavioral,
    PersonRecords,
    Stage2,
    MergeDrainsApplied,
    PendingTransfers,
    MergeApplied,
    MergeTombstones,
    Meta,
}

impl Cf {
    pub const ALL: [Cf; 8] = [
        Cf::Behavioral,
        Cf::PersonRecords,
        Cf::Stage2,
        Cf::MergeDrainsApplied,
        Cf::PendingTransfers,
        Cf::MergeApplied,
        Cf::MergeTombstones,
        Cf::Meta,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Cf::Behavioral => CF_BEHAVIORAL,
            Cf::PersonRecords => CF_PERSON_RECORDS,
            Cf::Stage2 => CF_STAGE2,
            Cf::MergeDrainsApplied => CF_MERGE_DRAINS_APPLIED,
            Cf::PendingTransfers => CF_PENDING_TRANSFERS,
            Cf::MergeApplied => CF_MERGE_APPLIED,
            Cf::MergeTombstones => CF_MERGE_TOMBSTONES,
            Cf::Meta => CF_META,
        }
    }

    /// Whether this CF's keys carry the partition prefix, so a partition wipe's range delete reclaims
    /// them. Exhaustive (no wildcard arm) so every new CF is forced to declare it — a range delete over
    /// a non-partitioned CF (whose short literal keys collide with an arbitrary partition's slice)
    /// would corrupt store-wide state such as the schema guard.
    pub const fn partitioned(self) -> bool {
        match self {
            Cf::Behavioral
            | Cf::PersonRecords
            | Cf::Stage2
            | Cf::MergeDrainsApplied
            | Cf::PendingTransfers
            | Cf::MergeApplied
            | Cf::MergeTombstones => true,
            Cf::Meta => false,
        }
    }
}

/// A column family safe for raw `put` by pre-encoded key bytes.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub enum OpaqueCf {
    Behavioral,
    Stage2,
}

impl OpaqueCf {
    pub const fn cf(self) -> Cf {
        match self {
            OpaqueCf::Behavioral => Cf::Behavioral,
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
        // matches the point-lookup pattern and is kept even under the prefix extractor so single-key
        // gets still short-circuit.
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

    // Per-CF options that must attach to exactly one column family. The match is the structural
    // guarantee: the TTL compaction filter can only be installed inside the `Cf::PersonRecords` arm, so
    // it can never land on `cf_behavioral` (whose eviction deadlines are the sweep's contract) or any
    // other CF.
    match cf {
        // A fixed-length prefix extractor over the person prefix turns a person's contiguous leaf
        // slice into a bloom-backed prefix seek, so reading one person's leaves touches one or a few
        // data blocks instead of scattering across the CF. Only `cf_behavioral` needs it: it holds many
        // leaves per person, so a person's rows are a range.
        Cf::Behavioral => {
            opts.set_prefix_extractor(SliceTransform::create_fixed_prefix(PERSON_PREFIX_LEN));
            opts.set_memtable_prefix_bloom_ratio(BEHAVIORAL_MEMTABLE_PREFIX_BLOOM_RATIO);
        }
        // `cf_person_records` is one row per person keyed by the 26-byte prefix itself — a prefix
        // extractor over a 26-byte prefix of a 26-byte key is redundant, so it keeps plain point-lookup
        // options with whole-key filtering only. When a TTL is configured, install the compaction
        // filter that drops person records dormant past the TTL; `0` leaves the CF untouched.
        Cf::PersonRecords => {
            if config.person_record_ttl_days != 0 {
                opts.set_compaction_filter_factory(PersonRecordTtlFactory::new(
                    config.person_record_ttl_days,
                ));
            }
        }
        // `cf_meta` and the merge CFs keep plain point-lookup options.
        Cf::Stage2
        | Cf::MergeDrainsApplied
        | Cf::PendingTransfers
        | Cf::MergeApplied
        | Cf::MergeTombstones
        | Cf::Meta => {}
    }

    opts
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cf_names_are_stable() {
        assert_eq!(Cf::Behavioral.as_str(), "cf_behavioral");
        assert_eq!(Cf::PersonRecords.as_str(), "cf_person_records");
        assert_eq!(Cf::Stage2.as_str(), "cf_stage2");
        assert_eq!(Cf::MergeDrainsApplied.as_str(), "cf_merge_drains_applied");
        assert_eq!(Cf::PendingTransfers.as_str(), "cf_pending_transfers");
        assert_eq!(Cf::MergeApplied.as_str(), "cf_merge_applied");
        assert_eq!(Cf::MergeTombstones.as_str(), "cf_merge_tombstones");
        assert_eq!(Cf::Meta.as_str(), "cf_meta");
    }

    #[test]
    fn all_is_exhaustive_and_unique() {
        assert_eq!(Cf::ALL.len(), 8);
        for cf in Cf::ALL {
            assert!(Cf::ALL.iter().filter(|&&c| c == cf).count() == 1);
        }
    }

    #[test]
    fn only_meta_is_non_partitioned() {
        for cf in Cf::ALL {
            assert_eq!(
                cf.partitioned(),
                cf != Cf::Meta,
                "every CF but cf_meta must be partition-prefixed: {cf:?}",
            );
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
