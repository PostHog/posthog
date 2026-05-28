//! Stage 2: per-person Boolean composition of a cohort's leaves (TDD §2.7, §4.2).
//!
//! Walks the original (non-sibling-merged) cohort filter tree, combines Stage 1 leaf bits
//! with the AND/OR/NOT semantics ported from `hogql_cohort_query.py:493-614`, applies the
//! cascade + cycle/depth/fan-out caps and the kill switch, then emits membership flips.
//! Planned submodules (TDD §3):
//! - `state`       — `Stage2State` (PR 3.2)
//! - `evaluator`   — per-person Boolean composition, output is bool not SQL (PR 3.2)
//! - `cohort_tree` — in-memory AND/OR/NOT tree; does NOT apply sibling-merge (§2.7; PR 3.2)
//! - `cascade`     — depth cap + fan-out cap + runtime cycle exclusion (§2.7.1; PR 3.3)
//! - `excluded`    — excluded-reason enum + metric emission (D13; PR 3.3)
