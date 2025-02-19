use posthog_rs::Event;
use tracing::error;
use uuid::Uuid;

const ISSUE_CREATED: &str = "error_tracking_issue_created";
const ISSUE_REOPENED: &str = "error_tracking_issue_reopened";
const SYMBOL_SET_SAVED: &str = "error_tracking_symbol_set_saved";

pub fn capture_issue_created(team_id: i32, issue_id: Uuid) {
    // TODO - @david, anything against using the team id here?
    let mut event = Event::new_anon(ISSUE_CREATED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("issue_id", issue_id.to_string()).unwrap();
    spawning_capture(event);
}

pub fn capture_issue_reopened(team_id: i32, issue_id: Uuid) {
    let mut event = Event::new_anon(ISSUE_REOPENED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("issue_id", issue_id.to_string()).unwrap();
    spawning_capture(event);
}

pub fn capture_symbol_set_saved(team_id: i32, set_ref: &str, storage_ptr: &str, was_retry: bool) {
    let mut event = Event::new_anon(SYMBOL_SET_SAVED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("set_ref", set_ref).unwrap();
    event.insert_prop("storage_ptr", storage_ptr).unwrap();
    event.insert_prop("was_retry", was_retry).unwrap();
    spawning_capture(event);
}

pub fn spawning_capture(event: Event) {
    tokio::spawn(async move {
        if let Err(e) = posthog_rs::capture(event).await {
            error!("Error capturing issue created event: {:?}", e);
        }
    });
}
