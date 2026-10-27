//! Follows the Node Postgres path's and `personhog-publisher`'s person CDC
//! feeds and reports as metrics whether they end in the same state. State
//! is in memory under a settle window; the rules are `cdc_parity`.

pub mod config;
pub mod feed;
pub mod join;
pub mod pipeline;
pub mod server;
