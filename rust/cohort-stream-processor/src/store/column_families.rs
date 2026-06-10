//! Column-family registry.

use rocksdb::{BlockBasedOptions, Cache, ColumnFamilyDescriptor, DBCompressionType, Options};

use super::rocks::StoreConfig;
use super::secondary_index::{full_merge, partial_merge, PERSON_INDEX_MERGE_OPERATOR_NAME};

/// Stage 1 per-leaf state: `(partition_id, team_id, leaf_state_key, person_id) → StatefulRecord`.
pub const CF_STAGE1: &str = "cf_stage1";
/// Per-person secondary index: `… → set<LeafStateKey>`.
pub const CF_PERSON_INDEX: &str = "cf_person_index";
/// Stage 2 membership: `(partition_id, team_id, cohort_id, person_id) → Stage2State`.
pub const CF_STAGE2: &str = "cf_stage2";
/// Cross-partition merge protocol (TDD §4.5.1), Phase 1 idempotence: `(partition_id, team_id,
/// P_old, merge_msg_partition, merge_msg_offset) → drained_at_ms`. Short-circuits a re-drained merge
/// message.
pub const CF_MERGE_DRAINS_APPLIED: &str = "cf_merge_drains_applied";
/// Phase 1 durability outbox: `(partition_id, team_id, P_old) → PendingTransfer`. Holds a packaged
/// merge between the drain `WriteBatch` and the successful produce to `cohort_merge_state_transfer`;
/// scanned on startup so an orphaned drain is re-produced.
pub const CF_PENDING_TRANSFERS: &str = "cf_pending_transfers";
/// Phase 2 idempotence: `(partition_id, team_id, P_new, transfer_partition, transfer_offset) →
/// applied_at_ms`. Short-circuits a re-applied transfer message.
pub const CF_MERGE_APPLIED: &str = "cf_merge_applied";
/// Post-merge straggler redirect (closes S6a): `(partition_id, team_id, P_old) → Tombstone`. Records
/// merged-away persons so a late `cohort_stream_events` message for P_old is redirected to P_new.
pub const CF_MERGE_TOMBSTONES: &str = "cf_merge_tombstones";

/// 10 bits ≈ 1% false-positive rate.
const BLOOM_FILTER_BITS_PER_KEY: f64 = 10.0;

/// `Cf::ALL` iteration order is the canonical fan-out order (e.g. `delete_partition`).
///
/// The four `Merge*` families (TDD §4.5.1) are plain put/delete CFs — only [`Cf::PersonIndex`] runs a
/// merge operator — so they are written by the typed `BatchBuilder` ops, never `put_raw`.
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

/// A column family whose value is caller-owned opaque bytes — safe for a raw `put`.
///
/// `cf_person_index` is deliberately *not* a variant: it is merge-only (value format owned by the
/// merge operator), so excluding it makes a raw put to the merge CF fail to compile rather than
/// silently corrupt the set.
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

    let mut opts = Options::default();
    opts.set_block_based_table_factory(&block_opts);
    opts.set_compression_type(DBCompressionType::Lz4);
    opts.set_write_buffer_size(config.write_buffer_bytes);

    match cf {
        Cf::PersonIndex => {
            opts.set_merge_operator(PERSON_INDEX_MERGE_OPERATOR_NAME, full_merge, partial_merge);
        }
        // Plain put/delete CFs — no merge operator (the merge families track offsets/payloads, not
        // a merge-collapsed set).
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
    fn cf_names_match_the_tdd() {
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
