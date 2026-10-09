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
    pub fn from_runs(class: RequestClass, runs: Vec<ReadyRun>) -> Self {
        let oldest_arrival = runs
            .iter()
            .map(|ready| ready.first_arrival)
            .min()
            .expect("a request holds at least one run");
        Self {
            class,
            message_count: runs.iter().map(|ready| ready.run.messages.len()).sum(),
            bytes: runs.iter().map(|ready| ready.bytes).sum(),
            oldest_arrival,
            runs: runs.into_iter().map(|ready| ready.run).collect(),
        }
    }
}
