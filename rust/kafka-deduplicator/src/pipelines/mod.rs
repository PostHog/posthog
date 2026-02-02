//! Pipeline-specific implementations for the deduplicator.
//!
//! Each pipeline module contains event-specific logic for:
//! - Deduplication key extraction
//! - Metadata creation and storage
//! - Similarity calculation
//! - Metrics emission
//!
//! # Structure
//!
//! Each pipeline is a submodule with its own internal structure:
//! ```text
//! pipelines/
//! └── ingestion_events/
//!     ├── mod.rs      # Pipeline module root
//!     └── keys.rs     # DeduplicationKeyExtractor impl
//! ```

pub mod ingestion_events;
