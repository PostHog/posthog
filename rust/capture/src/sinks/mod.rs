pub mod kafka;
pub mod noop;
pub mod print;
pub mod producer;
pub mod s3;
pub mod sink;
#[cfg(test)]
pub(crate) mod test_sink;
pub mod topics;

pub use sink::{fold_results, AddressedPayload, Outcome, Sink, SinkResult};
