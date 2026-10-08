//! A request on the wire: claimed key runs of one class.

use std::time::Instant;

use super::key_queues::{KeyRun, ReadyRun};

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
