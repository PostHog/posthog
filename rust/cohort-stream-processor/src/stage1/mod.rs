//! Stage 1: per-leaf incremental state (TDD §4.1).
//!
//! Evaluates each event's HogVM bytecode and maintains per-`(team_id, leaf_state_key,
//! person_id)` counters/booleans in RocksDB `cf_stage1`, emitting a transition only when
//! a leaf predicate flips. State is keyed by a derived `leaf_state_key`, not
//! `condition_hash` alone, because the bytecode omits the window and threshold (§4.1.0).
//! Submodules (TDD §3):
//! - `key`                — `LeafStateKey` derivation + `Stage1Key` (§4.1.0; PR 1.3)
//! - `state`              — `StateVariant`, `Stage1State` (M1 variants), `StatefulRecord` + codec (PR 1.6)
//! - `pick_state`         — `TimeInterval`, `EvictionWindow`, `pick_state_variant` (§4.1.1; PR 1.6, 2.1)
//! - `predicate`          — leaf membership predicate over `Stage1State` (PR 1.6)
//! - `transition`         — typed transition events (PR 1.6)
//! - `time`               — `clickhouse_timestamp_to_millis` event-timestamp parsing (PR 1.6)
//! - `bucket_tz`          — calendar-day-in-team-timezone bucket math (D9; PR 2.1, deferred)
//! - `compressed_history` — RLE storage for long windows (D10; PR 2.1, deferred)

pub mod key;
pub mod pick_state;
pub mod predicate;
pub mod state;
pub mod time;
pub mod transition;

pub use pick_state::{pick_state_variant, EvictionWindow, TimeInterval, UnsupportedVariant};
pub use predicate::predicate;
pub use state::{Stage1State, StateCodecError, StateVariant, StatefulRecord};
pub use time::clickhouse_timestamp_to_millis;
pub use transition::{LeafTransition, TransitionKind};
