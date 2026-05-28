//! `cohort-event-shuffler`: a stateless Kafka re-keying service for the Behavioral
//! Cohorts stream pipeline.
//!
//! It consumes `clickhouse_events_json` (keyed by `event.uuid`) and re-publishes the
//! subset of events belonging to teams with realtime cohorts to `cohort_stream_events`,
//! keyed by `hash(team_id, person_id)`. The re-key gives `cohort-stream-processor`'s
//! Stage 1 state affinity per `(team_id, person_id)`, which is what lets Stage 1 scale
//! horizontally (TDD §2.2, decision D3).
//!
//! This crate is a skeleton (Phase 0 / M8.d): it compiles and serves the observability
//! surface. The consume → filter → re-key → produce path lands in PR 1.1 (TDD §6.1).

pub mod config;
pub mod consumer;
pub mod filter_team_index;
pub mod observability;
pub mod producer;
