//! Stage 1: per-leaf incremental state (TDD §4.1).
//!
//! Evaluates each event's HogVM bytecode and maintains per-`(team_id, leaf_state_key,
//! person_id)` counters/booleans in RocksDB `cf_stage1`, emitting a transition only when
//! a leaf predicate flips. State is keyed by a derived `leaf_state_key`, not
//! `condition_hash` alone, because the bytecode omits the window and threshold (§4.1.0).
//! Planned submodules (TDD §3):
//! - `key`                — `LeafStateKey` derivation + `Stage1Key` (§4.1.0; PR 1.3)
//! - `state`              — `Stage1State` enum + per-interval representations (PR 1.6, 2.1)
//! - `pick_state`         — choose a state variant from the window spec (§4.1.1; PR 2.1)
//! - `predicate`          — count ≥/≤/=/… N evaluation (PR 1.6)
//! - `transition`         — typed transition events (PR 1.6)
//! - `bucket_tz`          — calendar-day-in-team-timezone bucket math (D9; PR 2.1)
//! - `compressed_history` — RLE storage for long windows (D10; PR 2.1)
