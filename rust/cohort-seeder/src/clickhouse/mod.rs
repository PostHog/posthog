//! ClickHouse layer: scan planning, row decoding, query attribution, the streaming scanners
//! (behavioral events and person rows), and the client builder. Depends only on `domain` and
//! `config` (plus the `clickhouse` crate); never on `store` or `kafka`.

pub mod client;
pub mod log_comment;
pub mod person_scanner;
pub mod person_sql;
pub mod row;
pub mod scan_volume;
pub mod scanner;
pub mod sql;

pub use client::{
    build_client, ClickHouseClientError, ClickHouseEndpoint, ClickHouseJoinAlgorithm,
};
pub use log_comment::{ScanLogComment, LOG_COMMENT_OPTION};
pub use person_scanner::{PersonRow, PersonScanError, PersonScanner};
pub use person_sql::PersonScanSpec;
pub use scan_volume::ScanKind;
pub use scanner::{ChunkScanner, ScanError, ScanSkipReason};
