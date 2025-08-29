use common_types::RawEvent;

use crate::{
    api::CaptureError,
    prometheus::{report_dropped_events, report_quota_limit_exceeded},
    router::State,
    v0_request::ProcessingContext,
};

/// Check if an event is a survey-related event that should be subject to survey quota limiting
fn is_survey_event(event_name: &str) -> bool {
    matches!(
        event_name,
        "survey sent" | "survey shown" | "survey dismissed"
    )
}

/// Check if an event is an AI-related event that should be subject to AI quota limiting
fn is_ai_event(event_name: &str) -> bool {
    event_name.starts_with("$ai_")
}

/// Check for billing quota limiting and filter out billing events if quota exceeded
/// IMPORTANT: this should be the LAST LIMITER CHECK APPLIED in the event processing pipeline!
/// TODO: remove EXCEPTION EVENT filtering and replace with a billing limiter for exceptions
pub async fn check_billing_quota_and_filter(
    state: &State,
    context: &ProcessingContext,
    events: Vec<RawEvent>,
) -> Result<Vec<RawEvent>, CaptureError> {
    let billing_limited = state
        .billing_limiter
        .is_limited(context.token.as_str())
        .await;

    if billing_limited {
        let (retained_events, dropped_events): (Vec<_>, Vec<_>) = events
            .into_iter()
            // TODO: remove retention of $exception events once we have a billing limiter for exceptions
            .partition(|e| {
                e.event == "$exception" || is_survey_event(&e.event) || is_ai_event(&e.event)
            });

        let dropped_count = dropped_events.len() as u64;
        if dropped_count > 0 {
            report_quota_limit_exceeded("billing", dropped_count);
            report_dropped_events("billing_over_quota", dropped_count);
        }

        if retained_events.is_empty() {
            return Err(CaptureError::BillingLimit);
        }

        return Ok(retained_events);
    }

    Ok(events)
}

/// Check for survey quota limiting and filter out survey events if quota exceeded
/// Simple all-or-nothing operation: if survey quota is exceeded, drop all survey events.
pub async fn check_survey_quota_and_filter(
    state: &State,
    context: &ProcessingContext,
    events: Vec<RawEvent>,
) -> Result<Vec<RawEvent>, CaptureError> {
    let survey_limited = state
        .survey_limiter
        .is_limited(context.token.as_str())
        .await;

    if survey_limited {
        // Drop all survey events when quota is exceeded
        let (survey_events, non_survey_events): (Vec<_>, Vec<_>) = events
            .into_iter()
            .partition(|event| is_survey_event(&event.event));

        let dropped_count = survey_events.len() as u64;
        if dropped_count > 0 {
            report_quota_limit_exceeded("survey", dropped_count);
            report_dropped_events("survey_over_quota", dropped_count);
        }

        // If no events remain, return billing limit error
        if non_survey_events.is_empty() {
            return Err(CaptureError::BillingLimit);
        }

        return Ok(non_survey_events);
    }

    Ok(events)
}

/// Check for AI events quota limiting and filter out AI events if quota exceeded
/// Simple all-or-nothing operation: if AI quota is exceeded, drop all AI events.
pub async fn check_llm_events_quota_and_filter(
    state: &State,
    context: &ProcessingContext,
    events: Vec<RawEvent>,
) -> Result<Vec<RawEvent>, CaptureError> {
    let ai_limited = state
        .llm_events_limiter
        .is_limited(context.token.as_str())
        .await;

    if ai_limited {
        // Drop all AI events when quota is exceeded
        let (llm_events, non_llm_events): (Vec<_>, Vec<_>) = events
            .into_iter()
            .partition(|event| is_ai_event(&event.event));

        let dropped_count = llm_events.len() as u64;
        if dropped_count > 0 {
            report_quota_limit_exceeded("llm_events", dropped_count);
            report_dropped_events("llm_events_over_quota", dropped_count);
        }

        // If no events remain, return billing limit error
        if non_llm_events.is_empty() {
            return Err(CaptureError::BillingLimit);
        }

        return Ok(non_llm_events);
    }

    Ok(events)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_survey_event() {
        // Survey events should return true
        assert!(is_survey_event("survey sent"));
        assert!(is_survey_event("survey shown"));
        assert!(is_survey_event("survey dismissed"));

        // Non-survey events should return false
        assert!(!is_survey_event("pageview"));
        assert!(!is_survey_event("$pageview"));
        assert!(!is_survey_event("click"));
        assert!(!is_survey_event("survey_sent")); // underscore variant
        assert!(!is_survey_event("Survey Sent")); // case sensitivity
        assert!(!is_survey_event(""));
    }
}
