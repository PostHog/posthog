//! Filter catalog: the in-memory view of realtime cohorts (TDD §2.7).
//!
//! Loads `posthog_cohort` filters, parses each cohort's tree (without the SQL-only
//! sibling-merge optimization), derives each leaf's `LeafStateKey`, builds the
//! `condition_hash` reverse indices, and detects reference cycles — refreshed every 5 min
//! (±1 min jitter) with an atomic `Arc<FilterCatalog>` swap. Planned submodules (TDD §3):
//! - `manager`         — 5-min refresh + atomic catalog swap (PR 1.3)
//! - `loader`          — `SELECT id, team_id, filters FROM posthog_cohort …` (PR 1.3)
//! - `tree`            — parsed per-cohort filter tree (PR 1.3)
//! - `reverse_index`   — `condition_hash → [LeafStateKey]` and `→ [cohort_id]` (PR 1.3)
//! - `leaf_classifier` — person | behavioral | cohort; skips cohort at Stage 1 (PR 1.3)
//! - `cohort_graph`    — reference graph + Tarjan SCC cycle detection (PR 3.3)
