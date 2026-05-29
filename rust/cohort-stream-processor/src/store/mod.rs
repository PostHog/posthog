//! RocksDB state store and durability (TDD §2.5).
//!
//! A single per-process RocksDB holding the column families of the state model, with
//! `partition_id`-prefixed keys and a per-person secondary index. WAL is async
//! (`set_sync(false)`); durability comes from the checkpoint cadence plus Kafka replay.
//!
//! Built as a **bespoke wrapper directly on the `rocksdb` crate** rather than an extension of
//! `rust/kafka-deduplicator/src/rocksdb/store.rs` (a deliberate deviation from TDD §2.5:308 —
//! one DB per process here vs one store per partition there means the dedup store's shared
//! static cache/write-buffer machinery buys us nothing, and it uses no merge operator).
//!
//! Submodules (TDD §3):
//! - `rocks` — RocksDB wrapper + multi-CF `WriteBatch` (PR 1.2)
//! - `column_families` — `cf_stage1`, `cf_person_index`, `cf_stage2`, and the four merge CFs (PR 1.2, 3.1)
//! - `keys` — typed, partition-prefixed key encoders (PR 1.2)
//! - `secondary_index` — `cf_person_index` maintenance via a merge operator (PR 1.2)
//! - `durability` — checkpoint + WAL + PVC-then-S3 recovery (PR 3.5)

pub mod column_families;
pub mod keys;
pub mod rocks;
pub mod secondary_index;

pub use column_families::{Cf, CF_PERSON_INDEX, CF_STAGE1, CF_STAGE2, OpaqueCf};
pub use keys::{PersonIndexKey, Stage2Key};
pub use rocks::{BatchBuilder, CohortStore, StoreConfig, StoreError};
pub use secondary_index::{decode_person_index, IndexOp, PERSON_INDEX_MERGE_OPERATOR_NAME};

// `Stage1Key` and `LeafStateKey` are defined in `stage1::key` (§4.1.0); re-exported here so the
// store's keys are reachable through one path.
pub use crate::stage1::key::{LeafStateKey, Stage1Key};
