//! `cohort-stream-processor`: the stateful core of the Behavioral Cohorts stream pipeline.
//!
//! It consumes re-keyed events from `cohort_stream_events`, maintains per-`(team_id,
//! leaf_state_key, person_id)` state in RocksDB, evaluates cohort membership incrementally, and
//! emits membership transitions. A periodic sweep handles time-driven eviction.

pub mod cascade;
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
pub mod workers;
