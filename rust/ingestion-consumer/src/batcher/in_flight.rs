//! A response references its request by id only. Resolving it maps the
//! returned messages back to their keys and checks the per-key contract: a
//! key's returned messages are a suffix of the run it sent, because the
//! worker processes a key's messages in order. A response that breaks the
//! contract is a protocol error.

use std::collections::{HashMap, HashSet};

use super::key_queues::KeyRun;
use super::request_class::RequestClass;
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RequestId(u64);

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SentMessage {
    pub topic: String,
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
    routing_key: String,
    messages: Vec<SentMessage>,
}

pub struct InFlightRequest {
    pub worker: WorkerId,
    pub class: RequestClass,
    pub message_count: usize,
    runs: Vec<SentRun>,
}

pub struct KeyOutcome {
    pub routing_key: String,
    pub accepted: Vec<SentMessage>,
    pub returned: Vec<SerializedKafkaMessage>,
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum ResolveError {
    #[error("returned message {topic}/{partition}@{offset} was not in the request")]
    Unknown {
        topic: String,
        partition: i32,
        offset: i64,
    },
    #[error("returned message {topic}/{partition}@{offset} appears more than once")]
    Duplicate {
        topic: String,
        partition: i32,
        offset: i64,
    },
    #[error("returned messages of key {routing_key} are not a suffix of its run")]
    NotASuffix { routing_key: String },
}

#[derive(Default)]
pub struct InFlightRequests {
    next_id: u64,
    requests: HashMap<RequestId, InFlightRequest>,
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
                routing_key: run.routing_key.clone(),
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
    /// Every key of the request gets an outcome, in send order.
    pub fn resolve(
        &self,
        returned: Vec<SerializedKafkaMessage>,
    ) -> Result<Vec<KeyOutcome>, ResolveError> {
        let mut position: HashMap<(&str, i32, i64), (usize, usize)> = HashMap::new();
        for (run_index, run) in self.runs.iter().enumerate() {
            for (message_index, message) in run.messages.iter().enumerate() {
                position.insert(
                    (message.topic.as_str(), message.partition, message.offset),
                    (run_index, message_index),
                );
            }
        }

        let mut returned_by_run: Vec<Vec<(usize, SerializedKafkaMessage)>> =
            self.runs.iter().map(|_| Vec::new()).collect();
        let mut seen: HashSet<(usize, usize)> = HashSet::new();
        for message in returned {
            let Some(&(run_index, message_index)) =
                position.get(&(message.topic.as_str(), message.partition, message.offset))
            else {
                return Err(ResolveError::Unknown {
                    topic: message.topic,
                    partition: message.partition,
                    offset: message.offset,
                });
            };
            if !seen.insert((run_index, message_index)) {
                return Err(ResolveError::Duplicate {
                    topic: message.topic,
                    partition: message.partition,
                    offset: message.offset,
                });
            }
            returned_by_run[run_index].push((message_index, message));
        }

        self.runs
            .iter()
            .zip(returned_by_run)
            .map(|(run, mut returned)| {
                returned.sort_by_key(|(message_index, _)| *message_index);
                let first_returned = run.messages.len() - returned.len();
                let is_suffix = returned
                    .iter()
                    .enumerate()
                    .all(|(rank, (message_index, _))| *message_index == first_returned + rank);
                if !is_suffix {
                    return Err(ResolveError::NotASuffix {
                        routing_key: run.routing_key.clone(),
                    });
                }
                Ok(KeyOutcome {
                    routing_key: run.routing_key.clone(),
                    accepted: run.messages[..first_returned].to_vec(),
                    returned: returned.into_iter().map(|(_, message)| message).collect(),
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
            routing_key: key.to_string(),
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
    fn a_partial_response_splits_each_key_into_accepted_prefix_and_returned_suffix() {
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
                    outcome.routing_key.as_str(),
                    outcome
                        .accepted
                        .iter()
                        .map(|m| m.offset)
                        .collect::<Vec<_>>(),
                    offsets(&outcome.returned),
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
        ResolveError::NotASuffix { routing_key: "a".to_string() },
    )]
    #[case::outside_the_request(
        vec![message("a", 0, 99)],
        ResolveError::Unknown { topic: "events".to_string(), partition: 0, offset: 99 },
    )]
    #[case::more_copies_than_the_run_holds(
        vec![message("b", 0, 10), message("b", 0, 10)],
        ResolveError::Duplicate { topic: "events".to_string(), partition: 0, offset: 10 },
    )]
    fn a_response_outside_the_contract_is_a_protocol_error(
        #[case] returned: Vec<SerializedKafkaMessage>,
        #[case] expected: ResolveError,
    ) {
        let (mut requests, id) = request();
        let request = requests.take(id).expect("registered");
        assert_eq!(request.resolve(returned).err(), Some(expected));
    }
}
