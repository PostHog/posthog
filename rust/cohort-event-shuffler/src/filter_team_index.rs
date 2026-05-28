//! In-memory index of teams with ≥1 realtime-supported cohort (TDD §2.2).
//!
//! Implemented in PR 1.1: polls `posthog_cohort` every 5 minutes and exposes an
//! atomically-swapped `Arc<HashSet<TeamId>>` that the consumer consults before
//! forwarding an event, mirroring the team gating in
//! `realtime-supported-filter-manager-cdp.ts`.
