//! The v4 recorder: a Kafka consumer beside the replay lanes that records a sample of sessions for AI research,
//! without scrubbing them. The format is in `products/ai_training/docs/replay-data.md`, section "v4 dataset".

pub mod batch;
pub mod config;
pub mod consumer;
pub mod flush;
pub mod index;
pub mod limits;
pub mod process;
pub mod rewrite;
pub mod scrub;
pub mod store;
pub mod teams;
pub mod urls;
pub mod write;
