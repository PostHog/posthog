//! Async chunk combinators — the structurally-impactful Node builders, with static
//! dispatch.
//!
//! These mirror the Node framework's `concurrently` / `concurrentlyPerGroup` /
//! `sequentially` / `branching` chunk builders, built over `futures` stream combinators
//! (the design, §1.5, says to *buy* these rather than hand-roll Node's
//! `InterleavingChunkPipeline` synchronization engine).
//!
//! They operate on an [`AsyncProcessor`](processor::AsyncProcessor) — a per-item async
//! transform with **no `&mut Fx`**. That is deliberate: concurrent per-item effects
//! would need synchronization, whereas the framework's model collects effects at chunk
//! boundaries (design §3.4), so per-item concurrent work stays effect-free.
//!
//! ## Ordering vs Node
//!
//! Node's grouping builder emits results in *group-completion* order (unordered between
//! groups). This POC instead reassembles results **positionally** — verdict `i` always
//! corresponds to input `i` — because the framework records verdicts by position across
//! stages (the same-length invariant). Within a group, items are still processed
//! strictly in order, exactly as Node does.

pub mod branching;
pub mod concurrently;
pub mod grouping;
pub mod processor;

pub use branching::Branching;
pub use concurrently::{concurrently, filter_map, sequentially};
pub use grouping::concurrently_per_group;
pub use processor::AsyncProcessor;
