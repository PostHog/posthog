//! Header-only preprocess pipeline for the ingestion consumer.
//!
//! Runs a small `common-pipelines` pipeline over each Kafka batch before
//! dispatch: parse headers, deny misrouted event types, apply event
//! restrictions (drop / DLQ / force-overflow). Gated behind `PREPROCESS_MODE`
//! (`off` by default — the pipeline is not constructed and behavior is
//! identical to today). See `common/pipelines/POC_NOTES.md` §consumer for the
//! POC's scope and deviations.

pub mod context;
pub mod deny_events;
pub mod headers;
pub mod metrics_consts;
pub mod parse_headers;
pub mod restrictions;

pub use context::{PreprocessOutput, RawMessage, WithHeaders};
pub use deny_events::DenyEvents;
pub use headers::EventHeaders;
pub use parse_headers::ParseHeaders;
pub use restrictions::ApplyEventRestrictions;
