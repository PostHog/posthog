//! Stateless Kafka re-keying service for the Behavioral Cohorts stream pipeline.
//!
//! Consumes `clickhouse_events_json` (keyed by `event.uuid`) and re-publishes events for teams
//! with realtime cohorts to `cohort_stream_events`, keyed by `hash(team_id, person_id)`. The
//! re-key gives `cohort-stream-processor` per-`(team_id, person_id)` state affinity so it can
//! scale horizontally.

pub mod config;
pub mod consumer;
pub mod event;
pub mod filter_team_index;
pub mod observability;
pub mod producer;
