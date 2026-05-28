//! Output producer (TDD §2.3, §2.8).
//!
//! Drains per-worker output buffers to the target topics: `cohort_membership_changed`
//! (external read path, schema unchanged), `cohort_cascade_events` (internal cascade), and
//! `cohort_merge_state_transfer` (internal merge drain, gated on `cf_pending_transfers`
//! durability). Produces are flushed before the worker's offset is committed. Planned
//! submodules (TDD §3):
//! - `batcher` — per-worker output buffers (PR 1.8)
//! - `kafka`   — `FutureProducer` wrapper for the target topics (PR 1.8, 3.1, 3.4)
