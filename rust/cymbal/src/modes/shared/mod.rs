//! Pieces shared between run modes. Unlike [`crate::core`], code here may touch
//! Redis and Kafka, so anything a mode needs from another mode lands here rather
//! than being imported across the mode boundary.

pub mod token_bucket;
