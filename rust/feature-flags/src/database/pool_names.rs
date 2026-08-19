//! Canonical names for the four connection pools.
//!
//! These strings are the `pool` label on every database metric the service emits, and they are
//! also handed to `PoolConfig::pool_name`, which labels pool-creation metrics inside
//! `common_database`. A typo does not fail anywhere: it silently starts a second time series
//! under a near-identical name, so dashboards and alerts keep reporting on the original one as
//! if the traffic had vanished. Route every pool label through these constants.

pub const PERSONS_READER: &str = "persons_reader";
pub const PERSONS_WRITER: &str = "persons_writer";
pub const NON_PERSONS_READER: &str = "non_persons_reader";
pub const NON_PERSONS_WRITER: &str = "non_persons_writer";
