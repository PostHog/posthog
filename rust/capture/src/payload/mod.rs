//! Payload handling infrastructure for HTTP request processing
//!
//! This module contains shared logic for decompressing, decoding, and parsing
//! HTTP request payloads. It's used by both analytics and recording event endpoints.

pub mod decompression;
pub mod types;

// Re-export commonly used types
pub use decompression::decompress_payload;
pub use types::{Compression, EventFormData, EventQuery};
