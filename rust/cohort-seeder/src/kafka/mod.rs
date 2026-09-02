//! Kafka layer: the seed-tile producer client, the produce pacer, and the completion observers — the
//! seed-group offset reader (liveness) and the marker-topic watcher (authority). Depends
//! only on `domain` (plus the shared metric-name constants); never on `store`.

pub mod committed;
pub mod markers;
pub mod pacing;
pub mod producer;

pub use committed::{SeedGroupOffsetError, SeedGroupOffsetReader};
pub use markers::{MarkerWatcher, WatchError, WatchItem};
pub use pacing::TilePacer;
pub use producer::{EnqueueError, SeedTileProducer};
