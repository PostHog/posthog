//! The parity rules for the person CDC feeds: the
//! `clickhouse_person_distinct_id` rows and `person_merge_events` that the
//! Node Postgres path and `personhog-publisher` both produce, and the
//! `clickhouse_person` rows that Node and the changelog relay both produce.
//! Feeds are compared by end state, not message by message, because the two
//! backends take different paths to the same place.

pub mod compare;
pub mod decode;
pub mod feed;
pub mod person;

pub use compare::{
    accounting_violations, compare_mapping, compare_states, compare_survivor, AccountingViolation,
    Divergence, MappingOutcome, Side, SurvivorOutcome,
};
pub use decode::{DecodeError, DistinctIdRow, MergeEvent, MERGE_EVENT_SCHEMA_VERSION};
pub use feed::{
    DistinctIdKey, FeedState, Mapping, MappingConflict, MergeConflict, MergeLoop, PersonKey,
};
pub use person::{compare_person, PersonFeed, PersonOutcome, PersonRow, PersonSnapshot};
