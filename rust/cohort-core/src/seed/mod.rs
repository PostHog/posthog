//! The seed wire contract shared by the backfill seeder (producer) and the stream processor
//! (consumer): the [`SeedTile`] day-tile, its id newtypes, and the tolerant [`decode_seed`] entry
//! point. Lives here — not in the seeder crate — for the same reason as [`crate::events`]: both
//! processes must agree on these bytes, and the processor cannot depend on the seeder.
//!
//! The JSON layout is frozen; the golden test in [`tile`] is the byte-level regression gate. New
//! fields must be additive and skipped when absent-equivalent (see `redirect_hops`) so tiles
//! produced by older seeders keep parsing and older consumers keep ignoring newer producers.

pub mod decode;
pub mod ids;
pub mod tile;

pub use decode::{decode_seed, DecodedSeed};
pub use ids::{ClaimEpoch, ConditionHash, ConditionHashError, RunId, SChunkMs};
pub use tile::SeedTile;
