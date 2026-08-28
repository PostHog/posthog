//! ClickHouse layer: scan planning, row decoding, the streaming scanners (behavioral events and
//! person rows), and the client builder. Depends only on `domain` and `config` (plus the
//! `clickhouse` crate); never on `store` or `kafka`.

pub mod client;
pub mod person_scanner;
pub mod person_sql;
pub mod row;
pub mod scanner;
pub mod sql;

pub use client::{
    build_client, ClickHouseClientError, ClickHouseEndpoint, ClickHouseJoinAlgorithm,
};
pub use person_scanner::{PersonRow, PersonScanError, PersonScanner};
pub use person_sql::PersonScanSpec;
pub use scanner::{ChunkScanner, ScanError};
