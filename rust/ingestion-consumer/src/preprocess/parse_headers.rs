//! `ParseHeaders` step: raw header map -> typed [`EventHeaders`].

use common_pipelines::{Step, StepError, StepResult};

use super::context::{PreprocessOutput, RawMessage, WithHeaders};
use super::headers::EventHeaders;

/// Parses the raw Kafka headers into [`EventHeaders`] and emits per-header
/// presence metrics. Always continues (never a terminal verdict).
pub struct ParseHeaders;

impl<Fx> Step<RawMessage, Fx> for ParseHeaders {
    type Out = WithHeaders;
    type Outputs = PreprocessOutput;

    fn apply(
        &self,
        event: RawMessage,
        _fx: &mut Fx,
    ) -> Result<StepResult<WithHeaders, PreprocessOutput>, StepError> {
        let headers = EventHeaders::parse(&event.headers);
        Ok(StepResult::Continue(WithHeaders { headers }))
    }

    fn name(&self) -> &'static str {
        "parse_headers"
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    #[test]
    fn parses_headers_and_continues() {
        let mut headers = HashMap::new();
        headers.insert("token".to_string(), "phc_abc".to_string());
        headers.insert("event".to_string(), "$pageview".to_string());

        let step = ParseHeaders;
        let result = step
            .apply(RawMessage { headers }, &mut ())
            .expect("no error");
        match result {
            StepResult::Continue(with) => {
                assert_eq!(with.headers.token.as_deref(), Some("phc_abc"));
                assert_eq!(with.headers.event.as_deref(), Some("$pageview"));
            }
            other => panic!("expected Continue, got {other:?}"),
        }
    }
}
