//! Header-only preprocess pipeline for the ingestion consumer.
//!
//! Runs a small `common-pipelines` pipeline over each Kafka batch before
//! dispatch: parse headers, deny misrouted event types, apply event
//! restrictions (drop / DLQ / force-overflow). Gated behind `PREPROCESS_MODE`
//! (`off` by default — the pipeline is not constructed and behavior is
//! identical to today). See `common/pipelines/POC_NOTES.md` §consumer for the
//! POC's scope and deviations.

pub mod headers;
pub mod metrics_consts;

pub use headers::EventHeaders;
