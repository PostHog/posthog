use metrics::counter;

use crate::{
    error::{EventError, UnhandledError},
    metric_consts::{MASKED_EXTENSION_DROPPED_EVENTS, MASKED_EXTENSION_FILTER_OPERATOR},
    stages::pipeline::HandledError,
    types::{
        exception_event::{ExceptionEvent, Parsed},
        operator::{OperatorResult, ValueOperator},
    },
};

// Drops events whose whole JavaScript stack is Safari-masked browser-extension code. Runs
// before resolution so we never fetch source maps for a crash that has no in-app frames and
// cannot become an issue anyone can act on. See `ExceptionList::is_masked_extension_only`.
#[derive(Clone)]
pub struct MaskedExtensionFilter;

impl ValueOperator for MaskedExtensionFilter {
    type Context = ();
    type Item = ExceptionEvent<Parsed>;
    type HandledError = HandledError;
    type UnhandledError = UnhandledError;

    fn name(&self) -> &'static str {
        MASKED_EXTENSION_FILTER_OPERATOR
    }

    async fn execute_value(&self, input: Self::Item, _: ()) -> OperatorResult<Self> {
        if input.exception_list().is_masked_extension_only() {
            counter!(MASKED_EXTENSION_DROPPED_EVENTS).increment(1);
            return Ok(Err(EventError::MaskedExtensionOnly(input.uuid())));
        }

        Ok(Ok(input))
    }
}
