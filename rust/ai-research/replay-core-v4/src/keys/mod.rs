//! The v4 key table in prod-us: one KMS-wrapped key per team per UTC day, and one session key sealed under it.

pub mod batch;
pub mod kms;
#[cfg(test)]
pub(crate) mod memory;
pub mod rows;
pub mod table;
