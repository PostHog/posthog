//! ClickHouse layer: scan planning, row decoding, the streaming scanner, and the client builder.
//! Depends only on `domain` and `config` (plus the `clickhouse` crate); never on `store` or `kafka`.

pub mod client;
pub mod row;
pub mod scanner;
pub mod sql;

pub use client::{build_client, ClickHouseEndpoint, ClickHouseJoinAlgorithm};
pub use scanner::{ChunkScanner, ScanError};
