//! The cohort seeder: backfills behavioral-cohort membership by replaying history.
//!
//! It claims day-chunks from PostgreSQL (`cohort_backfill_*`), scans each chunk's ClickHouse event
//! history, evaluates every event with `cohort-core`'s exact production Stage-1/HogVM code — so the
//! seed matches the live stream processor by construction — aggregates per-`(person, condition, day)`
//! tiles, and produces them paced to the `cohort_stream_seed_events` Kafka topic.
//!
//! Layers, with dependencies strictly downward and no module importing upward:
//! `domain` (pure, depends only on `cohort-core`) ← {`store` (PostgreSQL), `clickhouse`, `kafka`}
//! (IO, each depends on `domain`) ← `app` (the pipeline wiring the IO layers) ← `main`. `config` and
//! `observability` are leaves that the layers above draw on.

pub mod app;
pub mod clickhouse;
pub mod config;
pub mod domain;
pub mod kafka;
pub mod observability;
pub mod store;

#[cfg(feature = "pg-test-support")]
#[doc(hidden)]
pub mod test_support;
