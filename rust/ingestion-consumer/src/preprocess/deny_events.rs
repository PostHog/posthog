//! `DenyEvents` step: DLQ misrouted event types by header `event` name.

use std::collections::HashSet;

use common_pipelines::{Step, StepError, StepResult};

use super::context::{PreprocessOutput, WithHeaders};

/// Event names that belong to other consumers and must not reach the analytics
/// worker path. Mirrors the Node.js analytics deny list.
pub const DEFAULT_DENY_LIST: [&str; 3] = ["$exception", "$$client_ingestion_warning", "$$heatmap"];

/// DLQs any event whose header `event` name is in the deny list. Events with no
/// `event` header pass through (no name to match). Mirrors the Node.js
/// `createDenyEventsStep`.
pub struct DenyEvents {
    denied: HashSet<String>,
}

impl DenyEvents {
    pub fn new<I, S>(denied: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        Self {
            denied: denied.into_iter().map(Into::into).collect(),
        }
    }

    /// The default analytics deny list.
    pub fn with_defaults() -> Self {
        Self::new(DEFAULT_DENY_LIST.iter().map(|s| s.to_string()))
    }
}

impl<Fx> Step<WithHeaders, Fx> for DenyEvents {
    type Out = WithHeaders;
    type Outputs = PreprocessOutput;

    fn apply(
        &self,
        event: WithHeaders,
        _fx: &mut Fx,
    ) -> Result<StepResult<WithHeaders, PreprocessOutput>, StepError> {
        if let Some(name) = event.headers.event.as_deref() {
            if self.denied.contains(name) {
                return Ok(StepResult::dlq("event_in_denylist"));
            }
        }
        Ok(StepResult::Continue(event))
    }

    fn name(&self) -> &'static str {
        "deny_events"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::preprocess::headers::EventHeaders;

    fn with_event(event: Option<&str>) -> WithHeaders {
        WithHeaders {
            headers: EventHeaders {
                event: event.map(str::to_string),
                ..Default::default()
            },
        }
    }

    #[test]
    fn denylisted_event_goes_to_dlq() {
        let step = DenyEvents::with_defaults();
        for name in DEFAULT_DENY_LIST {
            let result = step.apply(with_event(Some(name)), &mut ()).unwrap();
            match result {
                StepResult::Dlq { reason, .. } => assert_eq!(reason, "event_in_denylist"),
                other => panic!("expected Dlq for {name}, got {other:?}"),
            }
        }
    }

    #[test]
    fn allowed_event_continues() {
        let step = DenyEvents::with_defaults();
        let result = step.apply(with_event(Some("$pageview")), &mut ()).unwrap();
        assert!(matches!(result, StepResult::Continue(_)));
    }

    #[test]
    fn missing_event_header_continues() {
        let step = DenyEvents::with_defaults();
        let result = step.apply(with_event(None), &mut ()).unwrap();
        assert!(matches!(result, StepResult::Continue(_)));
    }
}
