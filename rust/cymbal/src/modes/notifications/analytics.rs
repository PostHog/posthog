use posthog_rs::Event;
use uuid::Uuid;

use crate::core::analytics::capture_event;

const ISSUE_CREATED: &str = "error_tracking_issue_created";
const ISSUE_REOPENED: &str = "error_tracking_issue_reopened";

/// Exception dimensions carried on `error_tracking_issue_created`, so a spike in
/// issue creation can be broken down (which SDK, which exception type, which
/// fingerprint version) from the metric itself instead of a manual SQL dig.
#[derive(Debug, Default)]
pub struct IssueCreatedDimensions {
    pub sentry_integration: bool,
    pub exception_type: Option<String>,
    pub lib: Option<String>,
    pub fingerprint_version: Option<&'static str>,
}

pub fn capture_issue_created(team_id: i32, issue_id: Uuid, dimensions: IssueCreatedDimensions) {
    let mut event = Event::new_anon(ISSUE_CREATED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("issue_id", issue_id.to_string()).unwrap();
    event
        .insert_prop("sentry_integration", dimensions.sentry_integration)
        .unwrap();
    if let Some(exception_type) = dimensions.exception_type {
        event.insert_prop("exception_type", exception_type).unwrap();
    }
    if let Some(lib) = dimensions.lib {
        event.insert_prop("lib", lib).unwrap();
    }
    if let Some(version) = dimensions.fingerprint_version {
        event.insert_prop("fingerprint_version", version).unwrap();
    }
    capture_event(event);
}

pub fn capture_issue_reopened(team_id: i32, issue_id: Uuid) {
    let mut event = Event::new_anon(ISSUE_REOPENED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("issue_id", issue_id.to_string()).unwrap();
    capture_event(event);
}
