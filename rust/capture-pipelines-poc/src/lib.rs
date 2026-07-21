//! # capture-pipelines-poc
//!
//! A proof-of-concept for the capture pipelines framework, built with **static
//! dispatch only** — generics and `macro_rules!`, no `Box<dyn …>`, no `async_trait`.
//! It answers the open question in the design: can the framework's composition,
//! effects, observers, and async stages all be expressed without type erasure? Yes.
//!
//! This is a *demonstration crate*: no server, no Kafka, no real config. It compiles,
//! passes tests and `clippy -D warnings`, and reads as the skeleton the real framework
//! would grow from. See `README.md` for how it maps onto the plan and #70814.
//!
//! ## Layout (mirrors the Node ingestion layering)
//!
//! - [`framework`] — the reusable, domain-agnostic machinery. Never references the
//!   domain layers below.
//! - [`events`] — the demo event domain: capability traits, phase/enrichment wrappers,
//!   lane markers, and the boundary [`ParsedEvent`](events::parsed::ParsedEvent).
//! - [`steps`] — one demo step per file (`validate`, `enrich`, `quota`,
//!   `restrictions`, `annotate`).
//! - [`pipeline`] — the composed analytics pipeline: its `Outputs` enum, composed
//!   effects struct, and builder wiring.
//!
//! Dependency direction is one-way: `framework` ← `events` ← `steps` ← `pipeline`.
//!
//! ## Design rule: steps are open by default
//!
//! A step is generic over its input `In`, bounding only the capability traits it
//! reads, and generic over the effects struct `Fx`. It may fix a concrete input or
//! output type **only when there is a good reason, stated in a doc comment** — the
//! legitimate cases being boundary steps that create the initial type (parse:
//! bytes → `ParsedEvent`), steps whose job is type-specific aggregation/folding, and
//! adapters at the pipeline edge. This keeps upstream enrichment from rippling into
//! every downstream signature (see the `open_extension_*` integration test).
//!
//! ## The macros
//!
//! | Macro | Eliminates |
//! |---|---|
//! | [`for_each_capability!`] | listing the capability vocabulary more than once |
//! | [`impl_passthrough_caps!`] (+ `_tagged!`/`_laned!`) | hand-written capability forwarding through wrappers |
//! | [`compose_fx!`] | hand-written `HasSink` wiring for a pipeline's effects struct |
//! | [`impl_observer_tuple!`] | hand-written `Observer` impls for tuple composition |
//!
//! ## Pipeline shapes & combinators
//!
//! Async stages are part of the *composition*, not hand-wired afterward:
//! [`framework::batch`]'s [`compose`] builder fuses sync segments and async stages
//! via nested scopes (`.sequentially(|b| ..)`, `.concurrently(|item| ..)`,
//! `.grouped(key, |group| ..)`) into one flat, monomorphized
//! [`Built`] type — returned behind an opaque `impl BatchPipeline` (see
//! [`pipeline::build_analytics_pipeline`](pipeline::build_analytics_pipeline)) so the
//! builder chain, not a spelled-out `Then<…>` alias, is the pipeline description. The stages run the
//! Node combinators in [`framework::concurrency`] ([`concurrently`],
//! [`concurrently_per_group`], [`sequentially`], [`filter_map`], [`Branching`]);
//! [`framework::retry`] ([`Retry`]/[`RetryExt`]) and [`pipeline::accumulate`] cover the
//! rest. See `README.md`, "Pipeline shapes & combinators", for the full Node mapping.

#![warn(missing_docs)]

pub mod events;
pub mod framework;
pub mod pipeline;
pub mod steps;

// Ergonomic re-exports so the framework's core vocabulary is available at short paths.
pub use framework::batch::{compose, BatchPipeline, Built};
pub use framework::chain::{builder, Chain, Identity, IntoOutputs, Pipeline, PipelineBuilder};
pub use framework::chunk::{run_chunk_stage, run_pipeline, yield_now, ChunkStep};
pub use framework::concurrency::{
    concurrently, concurrently_per_group, filter_map, sequentially, AsyncProcessor, Branching,
};
pub use framework::fail_open::{FailOpen, FallibleStepExt};
pub use framework::fx::{HasSink, Warning, WarningEffects, WarningSink};
pub use framework::observer::{CountingObserver, Observer};
pub use framework::outputs::{MemProducer, MissingTopic, OutputRegistry, Produce};
pub use framework::result::{NoOutputs, Outputs, StepResult, VerdictKind};
pub use framework::retry::{Retry, RetryExt};
pub use framework::step::{FallibleStep, Step};
