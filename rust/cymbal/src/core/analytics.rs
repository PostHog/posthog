//! PostHog analytics capture for the shared symbolication kernel (symbol-set
//! lifecycle). Issue-lifecycle captures live in `crate::modes::processing::analytics`.

use posthog_rs::Event;

const SYMBOL_SET_SAVED: &str = "error_tracking_symbol_set_saved";
const SYMBOL_SET_DELETED: &str = "error_tracking_symbol_set_deleted";

pub fn capture_symbol_set_saved(team_id: i32, set_ref: &str, storage_ptr: &str, was_retry: bool) {
    let mut event = Event::new_anon(SYMBOL_SET_SAVED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("set_ref", set_ref).unwrap();
    event.insert_prop("storage_ptr", storage_ptr).unwrap();
    event.insert_prop("was_retry", was_retry).unwrap();
    capture_event(event);
}

pub fn capture_symbol_set_deleted(team_id: i32, set_ref: &str, storage_ptr: Option<&str>) {
    let mut event = Event::new_anon(SYMBOL_SET_DELETED);
    event.insert_prop("team_id", team_id).unwrap();
    event.insert_prop("set_ref", set_ref).unwrap();
    if let Some(ptr) = storage_ptr {
        event.insert_prop("storage_ptr", ptr).unwrap();
    }
    capture_event(event);
}

pub(crate) fn capture_event(event: Event) {
    if posthog_rs::global_is_disabled() {
        return;
    }
    posthog_rs::capture(event);
}
