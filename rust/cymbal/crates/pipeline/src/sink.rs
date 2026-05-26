//! Exception-pipeline sink alias on top of the generic [`cymbal_core::Sink`].
//!
//! The generic ordered-emission mechanics — the [`cymbal_core::Sink`] trait
//! and the [`cymbal_core::OrderedEmitter`] used to enforce input-order
//! delivery on top of an arbitrary sink — live in `cymbal-core` so non-
//! exception pipelines can reuse them. This module preserves the
//! [`EventResultSink`] name as a marker trait pinned to [`EventResult`] so
//! exception-pipeline call sites read at a glance and so the streaming
//! orchestrator can express its bound with the familiar name.
//!
//! Concerns that explicitly do not belong here: the buffering algorithm,
//! stage execution, or the streaming orchestration loop. Those live in
//! [`cymbal_core::emission`], [`cymbal_core::executor`], and
//! [`crate::streaming`] respectively.

use cymbal_core::Sink;
use cymbal_domain::EventResult;

/// Sink for streamed final per-event outcomes.
///
/// Implementations should apply backpressure in [`Sink::emit`]; the gRPC
/// service uses a bounded response channel so a slow client pauses pipeline
/// progress instead of accumulating an unbounded response buffer.
///
/// `EventResultSink` is a marker trait pinned to [`EventResult`]. Consumers
/// implement [`cymbal_core::Sink<EventResult>`] directly; a blanket impl
/// then satisfies the `EventResultSink` bound used by the streaming
/// orchestrator. Trait bounds on streaming entry points can use either
/// name interchangeably.
pub trait EventResultSink: Sink<EventResult> + Send {}

impl<T> EventResultSink for T where T: Sink<EventResult> + Send + ?Sized {}
