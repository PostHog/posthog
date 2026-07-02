//! Stage 1: per-`(team_id, leaf_state_key, person_id)` incremental state, emitting a transition
//! when a leaf predicate flips. State is keyed by a derived `leaf_state_key`, not `condition_hash`
//! alone, because the bytecode omits the window and threshold.

pub mod bucket_tz;
pub mod compressed_history;
pub mod daily;
pub mod key;
pub mod pick_state;
pub mod predicate;
pub mod state;
pub mod time;
pub mod transition;

pub use pick_state::{
    pick_state_variant, EvictionWindow, PredicateOp, TimeInterval, UnsupportedVariant,
};
pub use predicate::{compressed_predicate, daily_predicate, predicate};
pub use state::{AppliedOffsets, Stage1State, StateCodecError, StateVariant, StatefulRecord};
pub use time::clickhouse_timestamp_to_millis;
pub use transition::{LeafTransition, TransitionKind};
