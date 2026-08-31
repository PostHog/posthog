//! Kafka consumption core for stateful services.
//!
//! The design is the domain side of `rust/ingestion-consumer/docs/driver-model.md`
//! (§3.1-§3.7), whose §8 is the vocabulary authority: the top-level component
//! is the consumer loop, a driver is the single owner of one unit's state, and
//! a group is one routing key's messages from one poll.

pub mod accumulator;
pub mod charge;
pub mod commit;
pub mod config;
pub mod ledger;
pub mod manager;
pub mod partition;
pub mod types;
