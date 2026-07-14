//! Context types threaded through the preprocess pipeline, and the pipeline's
//! redirect-output enum.

use std::collections::HashMap;

use common_pipelines::Outputs;

use super::headers::EventHeaders;

/// Pipeline input: one Kafka message's raw header map.
///
/// POC note: this is a clone of the message's `HashMap<String, String>` headers.
/// A future intake refactor would hand over borrowed / `Bytes` header slices
/// instead of cloning (see `common/pipelines/POC_NOTES.md` §consumer).
#[derive(Debug)]
pub struct RawMessage {
    pub headers: HashMap<String, String>,
}

/// After `ParseHeaders`: the typed headers the later steps read.
#[derive(Debug)]
pub struct WithHeaders {
    pub headers: EventHeaders,
}

/// The redirect targets the preprocess pipeline can produce.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PreprocessOutput {
    Overflow,
}

impl Outputs for PreprocessOutput {
    fn name(&self) -> &'static str {
        match self {
            PreprocessOutput::Overflow => "overflow",
        }
    }
}
