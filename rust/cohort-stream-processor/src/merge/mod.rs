//! Cross-partition person-merge protocol: migrate per-leaf state from one person to another.
//!
//! Implements the Kafka-free core of TDD §4.5.1 (Slice C1): the wire/CF value types ([`transfer`]),
//! the pure per-leaf merge rules ([`rules`], with the dense [`bucket_align`] and sparse
//! [`compressed_concat`] math), and — added alongside — the tombstone-redirect resolution and the
//! sink-free drain/apply handlers. The Kafka consumers, producers, and assignment mirroring that
//! drive these handlers land in Slice C2; until then the protocol is dormant — nothing produces a
//! merge event or writes a tombstone.

pub mod apply_handler;
pub mod bucket_align;
pub mod compressed_concat;
pub mod drain_handler;
pub mod rules;
pub mod tombstone_redirect;
pub mod transfer;
