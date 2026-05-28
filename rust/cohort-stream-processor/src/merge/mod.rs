//! Cross-partition person-merge protocol (TDD §2.5, §4.5, §4.5.1).
//!
//! A two-phase Kafka-mediated drain → transfer → apply migrates per-leaf state from the
//! old person to the merge target when they live on different partitions (~98.4% of
//! merges). Both phases are idempotent under replay and durable across crashes via
//! dedicated RocksDB column families. Planned submodules (TDD §3):
//! - `drain_handler`      — Phase 1 on P_old's worker: pack state + produce transfer (PR 3.1)
//! - `apply_handler`      — Phase 2 on P_new's worker: per-leaf merge + re-evaluate (PR 3.1)
//! - `compressed_concat`  — RLE union of two compressed histories (PR 3.1)
//! - `bucket_align`       — window-aligned element-wise bucket sum (S6b; PR 3.1)
//! - `tombstone_redirect` — redirect late events for merged-away persons (S6a; PR 3.1)
//! - `pending_recovery`   — re-produce orphaned transfers on startup (PR 3.1)
