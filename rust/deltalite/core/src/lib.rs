//! deltalite -- a purpose-built streaming partition upsert on top of the `deltalake`
//! crate, replacing delta-rs's SQL MERGE for PostHog's warehouse-sync incremental path.
//!
//! Storage and protocol (log, checkpoints, Parquet writing, Add-action statistics,
//! S3 conditional-put commits, conflict resolution) all come from `deltalake`. Only the
//! *merge execution* is replaced: MERGE runs a DataFusion hash join whose memory scales
//! with the scanned target and which deadlocks under a bounded memory pool
//! (delta-io/delta-rs#4614); deltalite builds a PK hash set over the (small) source,
//! streams the (large) target a row group at a time, drops replaced rows, writes
//! survivors plus source rows, and commits every partition in ONE atomic commit. Peak
//! memory is bounded by the source and the concurrency knobs, never by table size.
//!
//! Semantics contract (equal to the production merge, proven by the differential parity
//! suite in `rust/deltalite/python/tests/`):
//!
//! - Row identity is `(primary_keys..., partition)`; a PK whose partition value changed
//!   inserts into the new partition and leaves the old row behind.
//! - SQL NULL semantics on primary keys: a NULL in any PK component never matches and
//!   always inserts.
//! - Matched target rows are replaced wholesale by the source row
//!   (`when_matched_update_all`); unmatched source rows insert; unmatched target rows
//!   survive verbatim.
//! - Duplicate source PK tuples are rejected (stricter than MERGE, deliberately --
//!   MERGE silently double-inserts non-matching duplicates).
//! - Tables with deletion vectors or column mapping (including the legacy
//!   `minReaderVersion=2/minWriterVersion=5` form) are refused.
//!
//! This crate is pure Rust; the Python bindings live in the sibling `deltalite-python`
//! crate (built with maturin, imported as `deltalite`).

pub mod errors;
pub mod limits;
pub mod pkset;
pub mod schema;
pub mod store;
pub mod table;
pub mod upsert;

pub use errors::{Error, Result};
pub use limits::ProcessLimits;
pub use table::{open_table, open_table_multipart, MultipartConfig};
pub use upsert::{upsert, PruneStrategy, UpsertOptions, UpsertStats};
