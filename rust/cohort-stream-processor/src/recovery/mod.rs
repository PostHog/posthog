//! Cold-start recovery trigger (TDD §3).
//!
//! Kicks off the Temporal backfill workflow that seeds a newly-eligible cohort's history
//! into `cohort_stream_seed_events` so Stage 1 has window history to evaluate against.
//! Planned submodule (TDD §3):
//! - `trigger` — calls Temporal `start_workflow` for cold-start (Phase 6, PR 6.1–6.2)
