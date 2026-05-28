//! Per-batch canonical structured log (TDD §8.2).
//!
//! Implemented alongside the worker: one wide event per processed batch capturing
//! partition, message counts, Stage 1 / Stage 2 transition counts, sweep evictions,
//! HogVM timings, and offsets — the single line an operator reads to understand a batch.
