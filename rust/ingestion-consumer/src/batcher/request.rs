//! A request on the wire: claimed key runs of one class.

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Instant;

use super::key_queues::{payload_bytes, KeyRun, ReadyRun};

/// Applies to every message of a request, so a request never mixes classes.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RequestClass {
    pub assignment_epoch: u64,
    pub replay: bool,
}

#[derive(Debug)]
pub struct Request {
    pub class: RequestClass,
    pub runs: Vec<KeyRun>,
    pub message_count: usize,
    pub bytes: usize,
    pub oldest_arrival: Instant,
}

impl Request {
    pub fn from_run(ready: ReadyRun) -> Self {
        Self {
            class: ready.class,
            message_count: ready.run.messages.len(),
            bytes: ready.bytes,
            oldest_arrival: ready.first_arrival,
            runs: vec![ready.run],
        }
    }
}

/// The caller must release the claim of every key in `emptied_keys`.
pub(crate) fn purge_request(
    request: &mut Request,
    revoked: &HashSet<(&str, i32)>,
    emptied_keys: &mut Vec<Arc<str>>,
) {
    let mut purged = 0usize;
    request.runs.retain_mut(|run| {
        let before = run.messages.len();
        run.messages
            .retain(|message| !revoked.contains(&(&*message.topic, message.partition)));
        purged += before - run.messages.len();
        if run.messages.is_empty() {
            emptied_keys.push(Arc::clone(&run.routing_key));
            false
        } else {
            true
        }
    });
    request.message_count = request.message_count.saturating_sub(purged);
    request.bytes = request
        .runs
        .iter()
        .map(|run| payload_bytes(&run.messages))
        .sum();
}
