use posthog_rs::Event;
use uuid::Uuid;

use crate::core::analytics::capture_event;

const ISSUE_CREATED: &str = "error_tracking_issue_created";
const ISSUE_REOPENED: &str = "error_tracking_issue_reopened";

pub fn capture_issue_created(team_id: i32, issue_id: Uuid, sentry_integration: bool) {
    let mut event = Event::new_anon(ISSUE_CREATED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("issue_id", issue_id.to_string()).unwrap();
    event
        .insert_prop("sentry_integration", sentry_integration)
        .unwrap();
    capture_event(event);
}

pub fn capture_issue_reopened(team_id: i32, issue_id: Uuid) {
    let mut event = Event::new_anon(ISSUE_REOPENED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("issue_id", issue_id.to_string()).unwrap();
    capture_event(event);
}
