//! Time-driven eviction: the deadline-ordered queue the sweep drains and the periodic timer that
//! drives it.
//!
//! The event path (Stage 1) computes an `earliest_eviction_at_ms` on every behavioral state but
//! never reads a wall clock (`stage1/state.rs`). This module is the time-driven half that does:
//!
//! - [`EvictionQueue`] — the per-worker, deadline-ordered structure, drained soonest-first.
//! - [`run_sweep_loop`] — the periodic timer that, each tick, asks a [`Sweeper`] to drain due keys.
//! - [`due_before_ms`] — the `now − safety_margin` cutoff the worker feeds to
//!   [`EvictionQueue::pop_due`].

pub mod dispatch;
pub mod eviction_queue;
pub mod scheduler;

pub use dispatch::DispatchSweeper;
pub use eviction_queue::EvictionQueue;
pub use scheduler::{due_before_ms, run_sweep_loop, run_sweep_loop_delayed, Sweeper};
