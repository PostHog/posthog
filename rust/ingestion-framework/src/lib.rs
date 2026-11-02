//! Rust port of the Node ingestion pipeline framework in
//! `nodejs/src/ingestion/framework`. The two are kept in step: same concepts, same names
//! (snake_case), same semantics. `PARITY.md` maps each TypeScript file to its module and
//! lists every known difference.

pub mod batching;
pub mod branching;
pub mod budget;
pub mod builders;
pub mod chunk_pipeline;
pub mod concurrent;
pub mod context;
pub mod errors;
pub mod fan_out_fan_in;
pub mod filter_map;
pub mod grouping;
pub mod helpers;
pub mod interleaving;
mod js_json;
pub mod metrics;
pub mod outputs;
pub mod per_element;
pub mod pipeline;
pub mod result_handling;
pub mod results;
pub mod retry;
pub mod side_effect_handling;
pub mod side_effects;
pub mod steps;
pub mod sync;
pub mod timeout_barrier;
pub mod warning_handling;

pub use batching::{
    AfterBatchInput, AfterBatchOutput, BatchResult, BatchingPipeline, BatchingPipelineOptions,
    BeforeBatchInput, BeforeBatchOutput, FeedRejectionKind, FeedResult, WithBatch,
};
pub use budget::BatchBudget;
pub use builders::{
    before_batch_step, new_batching_pipeline, new_chunk_pipeline, new_pipeline,
    passthrough_after_batch_step, ChunkPipelineBuilder, PipelineBuilder, StartPipelineBuilder,
};
pub use chunk_pipeline::{ChunkPipeline, ChunkPipelineUnwrapper, DynChunkPipeline};
pub use context::{
    create_ok_context, ChunkResults, OkResultWithContext, PipelineContext, PipelineWarning,
    ResultWithContext, WarningDetails,
};
pub use errors::{is_retriable, PipelineError};
pub use outputs::{
    HasMessage, HasTeamId, Headers, IngestionOutputs, KafkaMessage, MemoryOutputs, OutputMessage,
    DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT,
};
pub use per_element::per_element;
pub use pipeline::{DynPipeline, Pipeline};
pub use result_handling::PipelineConfig;
pub use results::{
    dlq, drop, ok, redirect, redirect_with, timeout, NonOk, Outcome, PipelineResult,
    PipelineResultType,
};
pub use retry::RetryOptions;
pub use side_effect_handling::SideEffectHandlingConfig;
pub use side_effects::{PromiseScheduler, SideEffect, SideEffectScheduler};
pub use steps::{chunk_step, step, ChunkProcessingStep, ProcessingStep};
