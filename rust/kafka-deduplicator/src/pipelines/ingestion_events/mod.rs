//! Ingestion events pipeline implementation.
//!
//! This module contains the deduplication logic specific to PostHog's
//! ingestion events (CapturedEvent/RawEvent from the capture service).

mod keys;
mod parser;

pub use parser::IngestionEventParser;
