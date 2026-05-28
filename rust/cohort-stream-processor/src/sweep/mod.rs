//! Time-driven eviction sweep (TDD §2.6, decision D11).
//!
//! A periodic timer walks a per-worker eviction heap; each entry past its deadline plus
//! `safety_margin_ms` is routed back to its owning worker, which drops the stale bucket,
//! recomputes the predicate, and emits a `left` transition if it flipped. There is no
//! per-team watermark — eviction is wall-clock plus safety margin. Planned submodules:
//! - `scheduler`     — periodic sweep timer (PR 2.2)
//! - `eviction_heap` — per-worker `BinaryHeap<Reverse<(deadline_ms, Stage1Key)>>` (PR 2.2)
