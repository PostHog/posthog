//! The v4 key table in prod-us: one KMS-wrapped key per team per UTC month, and one session key sealed under it.

pub mod kms;
pub mod rows;
