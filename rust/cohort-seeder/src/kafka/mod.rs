//! Kafka layer: the seed-tile producer client and the produce pacer. Depends only on `domain` (plus
//! the shared metric-name constants); never on `store`.

pub mod pacing;
pub mod producer;

pub use pacing::TilePacer;
pub use producer::{EnqueueError, SeedTileProducer};
