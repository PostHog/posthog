//! The file processing behind PostHog error tracking uploads.
//!
//! PostHog stores a symbol set under a chunk id and a content hash, and refuses a second upload
//! of the same chunk id with a different hash. Every tool that uploads symbol sets must therefore
//! write the same bytes for the same input. This crate holds the code that decides those bytes,
//! so posthog-cli and hog-worker share one source for it.
//!
//! The crate reads and writes local files only. Network calls, authentication, command line
//! parsing and terminal output belong to the binaries.

pub mod debug_symbols;
pub mod dsym;
pub mod files;
pub mod proguard;
pub mod sourcemaps;
pub mod upload;

pub use upload::{ReleaseMode, SymbolSetUpload};
