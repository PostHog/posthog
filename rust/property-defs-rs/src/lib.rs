use metrics_consts::{EMPTY_EVENTS, EVENT_PARSE_ERROR};
use rdkafka::{message::BorrowedMessage, Message};
use tracing::warn;
use types::Event;

pub mod app_context;
pub mod config;
pub mod metrics_consts;
pub mod types;

// This copies event properties, which means the total resident memory usage is higher than we'd like, and that constrains
// our batch size. serde_json provides no zero-copy way to parse a JSON object, so we're stuck with this for now.
pub fn message_to_event(msg: BorrowedMessage) -> Option<Event> {
    let Some(payload) = msg.payload() else {
        warn!("Received empty event");
        metrics::counter!(EMPTY_EVENTS).increment(1);
        return None;
    };

    let event = serde_json::from_slice::<Event>(payload);
    let event = match event {
        Ok(e) => e,
        Err(e) => {
            metrics::counter!(EVENT_PARSE_ERROR).increment(1);
            warn!("Failed to parse event: {:?}", e);
            return None;
        }
    };
    Some(event)
}

pub fn retain_from<T>(buffer: &mut Vec<T>, from: usize, predicate: impl Fn(&T) -> bool) {
    let mut i = from;
    while i < buffer.len() {
        if !predicate(&buffer[i]) {
            buffer.swap_remove(i);
        } else {
            i += 1;
        }
    }
}
