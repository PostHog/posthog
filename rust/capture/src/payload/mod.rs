//! Payload handling infrastructure for HTTP request processing
//!
//! This module contains shared logic for decompressing, decoding, and parsing
//! HTTP request payloads. It's used by both analytics and recording event endpoints.

pub mod analytics;
pub mod common;
pub mod decompression;
pub mod recordings;
pub mod types;

// Re-export commonly used types
pub use analytics::handle_event_payload;
pub use common::{extract_and_record_metadata, extract_payload_bytes, RequestMetadata};
pub use decompression::decompress_payload;
pub use recordings::handle_recording_payload;
pub use types::{Compression, EventFormData, EventQuery};
