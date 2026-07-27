//! Cross-partition person-merge protocol: migrate per-leaf state from one person to another.

pub mod apply_handler;
pub mod bucket_align;
pub mod compressed_concat;
pub mod drain_handler;
pub mod gc;
pub mod redrive;
pub mod rules;
pub mod tombstone_redirect;
pub mod transfer;
