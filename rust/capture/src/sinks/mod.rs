pub mod kafka;
pub mod producer;
pub mod s3;
pub mod sink;

pub use sink::{fold_results, Outcome, SinkResult};
