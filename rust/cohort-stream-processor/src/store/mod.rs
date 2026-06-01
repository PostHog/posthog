//! RocksDB state store and durability.
//!
//! A single per-process RocksDB holding the three state column families, with
//! `partition_id`-prefixed keys and a per-person secondary index. WAL is async
//! (`set_sync(false)`); durability comes from the checkpoint cadence plus Kafka replay.

pub mod column_families;
pub mod keys;
pub mod rocks;
pub mod secondary_index;

pub use column_families::{Cf, OpaqueCf, CF_PERSON_INDEX, CF_STAGE1, CF_STAGE2};
pub use keys::{PersonIndexKey, Stage2Key};
pub use rocks::{BatchBuilder, CohortStore, StoreConfig, StoreError};
pub use secondary_index::{decode_person_index, IndexOp, PERSON_INDEX_MERGE_OPERATOR_NAME};

// Defined in `stage1::key`; re-exported so the store's keys are reachable through one path.
pub use crate::stage1::key::{LeafStateKey, Stage1Key};
