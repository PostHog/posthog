pub mod kafka;
pub mod noop;
pub mod print;
pub mod producer;
pub mod s3;
pub mod sink;
#[cfg(test)]
pub(crate) mod test_sink;

pub use sink::{fold_results, Outcome, PreparedPayload, Sink, SinkResult};
