use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use super::key_queues::KeyRun;
use super::request::RequestClass;
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RequestId(u64);

#[derive(Debug)]
pub struct SentMessage {
    pub topic: Arc<str>,
    pub partition: i32,
    pub offset: i64,
    pub keyed: bool,
}

impl SentMessage {
    fn of(message: &SerializedKafkaMessage) -> Self {
        Self {
            topic: message.topic.clone(),
            partition: message.partition,
            offset: message.offset,
            keyed: message.key.is_some(),
        }
    }
}

struct SentRun {
    routing_key: Arc<str>,
    messages: Vec<SentMessage>,
}

pub struct InFlightRequest {
    pub worker: WorkerId,
    pub class: RequestClass,
    pub message_count: usize,
    runs: Vec<SentRun>,
}

pub struct KeyOutcome {
    pub routing_key: Arc<str>,
    pub accepted: Vec<SentMessage>,
    pub unprocessed: Vec<SerializedKafkaMessage>,
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum ResolveError {
    #[error("unprocessed message {topic}/{partition}@{offset} was not in the request")]
    Unknown {
        topic: String,
        partition: i32,
        offset: i64,
    },
    #[error("unprocessed message {topic}/{partition}@{offset} appears more than once")]
    Duplicate {
        topic: String,
        partition: i32,
        offset: i64,
    },
    #[error("unprocessed messages of key {routing_key} are not a suffix of its run")]
    NotASuffix { routing_key: String },
}

/// A response references its request by id only, so this keeps what each
/// request carried.
#[derive(Default)]
pub struct InFlightRequests {
    next_id: u64,
    requests: HashMap<RequestId, InFlightRequest, ahash::RandomState>,
}

impl InFlightRequests {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.requests.len()
    }

    pub fn is_empty(&self) -> bool {
        self.requests.is_empty()
    }

    pub fn register(
        &mut self,
        worker: WorkerId,
        class: RequestClass,
        runs: &[KeyRun],
    ) -> RequestId {
        let id = RequestId(self.next_id);
        self.next_id += 1;
        let runs: Vec<SentRun> = runs
            .iter()
            .map(|run| SentRun {
                routing_key: Arc::clone(&run.routing_key),
                messages: run.messages.iter().map(SentMessage::of).collect(),
            })
            .collect();
        let message_count = runs.iter().map(|run| run.messages.len()).sum();
        self.requests.insert(
            id,
            InFlightRequest {
                worker,
                class,
                message_count,
                runs,
            },
        );
        id
    }

    pub fn take(&mut self, id: RequestId) -> Option<InFlightRequest> {
        self.requests.remove(&id)
    }
}

impl InFlightRequest {
    /// Every key of the request gets an outcome, in send order. A key's
    /// unprocessed messages must be a suffix of the run it sent, because the
    /// worker processes a key's messages in order. A response that breaks
    /// this is a protocol error.
    pub fn resolve(
        self,
        unprocessed: Vec<SerializedKafkaMessage>,
    ) -> Result<Vec<KeyOutcome>, ResolveError> {
        if unprocessed.is_empty() {
            return Ok(self
                .runs
                .into_iter()
                .map(|run| KeyOutcome {
                    routing_key: run.routing_key,
                    accepted: run.messages,
                    unprocessed: Vec::new(),
                })
                .collect());
        }
        let mut position: HashMap<(&str, i32, i64), (usize, usize)> = HashMap::new();
        for (run_index, run) in self.runs.iter().enumerate() {
            for (message_index, message) in run.messages.iter().enumerate() {
                position.insert(
                    (&*message.topic, message.partition, message.offset),
                    (run_index, message_index),
                );
            }
        }

        let mut unprocessed_by_run: Vec<Vec<(usize, SerializedKafkaMessage)>> =
            self.runs.iter().map(|_| Vec::new()).collect();
        let mut seen: HashSet<(usize, usize)> = HashSet::new();
        for message in unprocessed {
            let Some(&(run_index, message_index)) =
                position.get(&(&*message.topic, message.partition, message.offset))
            else {
                return Err(ResolveError::Unknown {
                    topic: message.topic.to_string(),
                    partition: message.partition,
                    offset: message.offset,
                });
            };
            if !seen.insert((run_index, message_index)) {
                return Err(ResolveError::Duplicate {
                    topic: message.topic.to_string(),
                    partition: message.partition,
                    offset: message.offset,
                });
            }
            unprocessed_by_run[run_index].push((message_index, message));
        }

        drop(position);
        self.runs
            .into_iter()
            .zip(unprocessed_by_run)
            .map(|(run, mut unprocessed)| {
                unprocessed.sort_by_key(|(message_index, _)| *message_index);
                let first_unprocessed = run.messages.len() - unprocessed.len();
                let is_suffix = unprocessed
                    .iter()
                    .enumerate()
                    .all(|(rank, (message_index, _))| *message_index == first_unprocessed + rank);
                if !is_suffix {
                    return Err(ResolveError::NotASuffix {
                        routing_key: run.routing_key.to_string(),
                    });
                }
                let mut accepted = run.messages;
                accepted.truncate(first_unprocessed);
                Ok(KeyOutcome {
                    routing_key: run.routing_key,
                    accepted,
                    unprocessed: unprocessed
                        .into_iter()
                        .map(|(_, message)| message)
                        .collect(),
                })
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use rstest::rstest;

    use super::*;
    use crate::batcher::test_support::{message, offsets};

    const FRESH: RequestClass = RequestClass {
        assignment_epoch: 0,
        replay: false,
    };

    fn run(key: &str, offsets: &[i64]) -> KeyRun {
        KeyRun {
            routing_key: key.into(),
            messages: offsets
                .iter()
                .map(|&offset| message(key, 0, offset))
                .collect(),
        }
    }

    fn request() -> (InFlightRequests, RequestId) {
        let mut requests = InFlightRequests::new();
        let id = requests.register(
            WorkerId::from("w"),
            FRESH,
            &[run("a", &[1, 2, 3]), run("b", &[10])],
        );
        (requests, id)
    }

    #[test]
    fn a_partial_response_splits_each_key_into_accepted_prefix_and_unprocessed_suffix() {
        let (mut requests, id) = request();
        let request = requests.take(id).expect("registered");
        assert_eq!(request.message_count, 4);

        let outcomes = request
            .resolve(vec![message("a", 0, 3), message("a", 0, 2)])
            .expect("a suffix");
        let shapes: Vec<_> = outcomes
            .iter()
            .map(|outcome| {
                (
                    &*outcome.routing_key,
                    outcome
                        .accepted
                        .iter()
                        .map(|m| m.offset)
                        .collect::<Vec<_>>(),
                    offsets(&outcome.unprocessed),
                )
            })
            .collect();
        assert_eq!(
            shapes,
            vec![("a", vec![1], vec![2, 3]), ("b", vec![10], vec![])]
        );
    }

    #[rstest]
    #[case::skips_an_accepted_message(
        vec![message("a", 0, 2)],
        ResolveError::NotASuffix { routing_key: "a".into() },
    )]
    #[case::outside_the_request(
        vec![message("a", 0, 99)],
        ResolveError::Unknown { topic: "events".into(), partition: 0, offset: 99 },
    )]
    #[case::more_copies_than_the_run_holds(
        vec![message("b", 0, 10), message("b", 0, 10)],
        ResolveError::Duplicate { topic: "events".into(), partition: 0, offset: 10 },
    )]
    fn a_response_outside_the_contract_is_a_protocol_error(
        #[case] unprocessed: Vec<SerializedKafkaMessage>,
        #[case] expected: ResolveError,
    ) {
        let (mut requests, id) = request();
        let request = requests.take(id).expect("registered");
        assert_eq!(request.resolve(unprocessed).err(), Some(expected));
    }
}
