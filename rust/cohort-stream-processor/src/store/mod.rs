//! RocksDB state store and durability (TDD §2.5).
//!
//! Wraps a single per-process RocksDB holding the seven column families of the state
//! model, with partition-id-prefixed keys and a secondary person index. Extends
//! `rust/kafka-deduplicator`'s store with a CF-aware atomic `put_batch`. WAL is async
//! (`set_sync(false)`); durability comes from the checkpoint cadence plus Kafka replay.
//! Planned submodules (TDD §3):
//! - `rocks` — RocksDB wrapper + multi-CF `WriteBatch` (PR 1.2)
//! - `column_families` — `cf_stage1`, `cf_person_index`, `cf_stage2`, and the four merge CFs (PR 1.2, 3.1)
//! - `keys` — typed, partition-prefixed key encoders (PR 1.2)
//! - `secondary_index` — `cf_person_index` maintenance via a merge operator (PR 1.2)
//! - `durability` — checkpoint + WAL + PVC-then-S3 recovery, lifted from `kafka-deduplicator/src/checkpoint/` (PR 3.5)
