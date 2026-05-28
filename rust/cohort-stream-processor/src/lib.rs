//! `cohort-stream-processor`: the stateful core of the Behavioral Cohorts stream
//! pipeline (TDD §2, §3).
//!
//! It consumes re-keyed events from `cohort_stream_events` (plus the person-merge,
//! cascade, merge-transfer and seed-event topics), maintains per-`(team_id,
//! leaf_state_key, person_id)` state in RocksDB, evaluates cohort membership
//! incrementally (Stage 1 → Stage 2), and emits membership transitions to
//! `cohort_membership_changed`. A periodic sweep handles time-driven eviction;
//! checkpoint + WAL + S3 provide durability.
//!
//! This crate is a skeleton (Phase 0 / M8.d): it compiles and serves the observability
//! surface. The module tree below mirrors TDD §3; each module is filled in by its
//! Phase 1–3 PR (TDD §6).

pub mod config;
pub mod consumers;
pub mod filters;
pub mod hogvm;
pub mod kill_switch;
pub mod merge;
pub mod observability;
pub mod partitions;
pub mod producer;
pub mod recovery;
pub mod stage1;
pub mod stage2;
pub mod store;
pub mod sweep;
