//! `common-pipelines` — a small framework for PostHog ingestion pipelines.
//!
//! This is a proof-of-concept implementation of the design in
//! `rust-ingestion-pipelines-design.md`. It provides the core vocabulary
//! (per-event verdicts), synchronous per-event and asynchronous per-chunk step
//! traits, a batch executor, a fail-open combinator, an effects/plugin/observer
//! layer, and result handling that produces DLQ/redirect messages with
//! Node-compatible provenance headers.
//!
//! See `POC_NOTES.md` for deviations from the design doc.

pub mod effects;
pub mod fail_open;
pub mod metrics_consts;
pub mod outputs;
pub mod plugin;
pub mod result;
pub mod step;

pub use effects::{DeferredProduce, EffectQueue, OutputRef};
pub use fail_open::{FailOpen, FailOpenExt};
pub use outputs::{
    handle_results, EffectProducer, HandleSummary, MockProducer, OutputRegistry, OutputTarget,
    RawRecord, RdKafkaEffectProducer, SentMessage,
};
pub use plugin::{HasSink, MetricsObserver, Observer, Plugin};
pub use result::{NoOutputs, Outputs, StepError, StepResult};
pub use step::{
    ChunkOutcome, ChunkStep, ItemOutcome, Pipeline, PipelineBuilder, Step, Verdict, VerdictKind,
};
