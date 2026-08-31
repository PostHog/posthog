//! Kafka consumption core for stateful services.
//!
//! The vocabulary follows `rust/ingestion-consumer/docs/driver-model.md` §8:
//! the top-level component is the consumer loop, a driver is the single owner
//! of one unit's state, and a group is one routing key's messages from one poll.

pub mod charge;
pub mod config;
pub mod ledger;
pub mod types;

pub use charge::Charge;
pub use config::ConsumerConfigBuilder;
pub use ledger::{OffsetLedger, TakenFrontier};
pub use types::Offset;
