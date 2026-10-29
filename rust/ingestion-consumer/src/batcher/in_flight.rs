//! Remembers what each in-flight request carried, because a response names
//! its request only by id.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use super::key_queues::KeyRun;
use super::request::RequestClass;
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RequestId(u64);

impl RequestId {
    pub fn as_u64(self) -> u64 {
        self.0
    }
}

#[derive(Debug)]
pub struct SentMessage {
    pub partition: i32,
    pub generation: u64,
    pub offset: i64,
    pub keyed: bool,
}

impl SentMessage {
    fn of(message: &SerializedKafkaMessage) -> Self {
        Self {
            partition: message.partition,
            generation: message.generation,
            offset: message.offset,
            keyed: message.key.is_some(),
        }
    }
}

/// The partition the key's order watermark tracks.
fn first_keyed_partition(messages: &[SentMessage]) -> Option<i32> {
    messages
        .iter()
        .find(|message| message.keyed)
        .map(|message| message.partition)
}

pub struct SentRun {
    pub routing_key: Arc<str>,
    pub messages: Vec<SentMessage>,
}

impl SentRun {
    pub fn first_keyed_partition(&self) -> Option<i32> {
        first_keyed_partition(&self.messages)
    }
}

/// One run's share of a partial ack.
pub struct PartialRun {
    pub routing_key: Arc<str>,
    /// Taken from the whole run, because the first keyed message may itself
    /// be unfinished.
    pub first_keyed_partition: Option<i32>,
    pub accepted: Vec<SentMessage>,
    pub unfinished: Vec<SerializedKafkaMessage>,
}

pub struct InFlightRequest {
    pub worker: WorkerId,
    pub class: RequestClass,
    pub message_count: usize,
    pub sent_at: Instant,
    runs: Vec<SentRun>,
}

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
        sent_at: Instant,
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
                sent_at,
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
    pub fn accepted(self) -> Vec<SentRun> {
        self.runs
    }

    /// The transport hands back every message of a failed request in send
    /// order, so the runs are cut by length.
    pub fn hand_back(self, messages: Vec<SerializedKafkaMessage>) -> Result<Vec<KeyRun>, String> {
        if messages.len() != self.message_count {
            return Err(format!(
                "transport handed back {} of {} messages of a failed request",
                messages.len(),
                self.message_count
            ));
        }
        let mut messages = messages.into_iter();
        Ok(self
            .runs
            .into_iter()
            .map(|run| KeyRun {
                messages: messages.by_ref().take(run.messages.len()).collect(),
                routing_key: run.routing_key,
            })
            .collect())
    }

    /// The transport hands back the unfinished messages in send order. They
    /// need not be the last messages of a run, because a worker may process
    /// one key's messages in independent groups.
    pub fn partially_accepted(
        self,
        accepted_count: u32,
        unfinished: Vec<SerializedKafkaMessage>,
    ) -> Result<Vec<PartialRun>, String> {
        if unfinished.is_empty() || accepted_count as usize + unfinished.len() != self.message_count
        {
            return Err(format!(
                "partial ack accepted {accepted_count} and left {} of {} messages unfinished",
                unfinished.len(),
                self.message_count
            ));
        }
        let mut unfinished = unfinished.into_iter().peekable();
        let partial_runs = self
            .runs
            .into_iter()
            .map(|run| {
                let mut partial_run = PartialRun {
                    routing_key: run.routing_key,
                    first_keyed_partition: first_keyed_partition(&run.messages),
                    accepted: Vec::new(),
                    unfinished: Vec::new(),
                };
                for sent in run.messages {
                    let next = unfinished.next_if(|message| {
                        message.partition == sent.partition && message.offset == sent.offset
                    });
                    match next {
                        Some(message) => partial_run.unfinished.push(message),
                        None => partial_run.accepted.push(sent),
                    }
                }
                partial_run
            })
            .collect();
        if let Some(message) = unfinished.next() {
            return Err(format!(
                "partial ack lists {}:{} as unfinished, which the request does not carry at that point",
                message.partition, message.offset
            ));
        }
        Ok(partial_runs)
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
        unbudgeted: false,
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

    fn request() -> InFlightRequest {
        let mut requests = InFlightRequests::new();
        let id = requests.register(
            WorkerId::from("w"),
            FRESH,
            Instant::now(),
            &[run("a", &[1, 2, 3]), run("b", &[10])],
        );
        requests.take(id).expect("registered")
    }

    #[test]
    fn a_failed_request_hands_each_key_back_its_run() {
        let request = request();
        let handed_back = vec![
            message("a", 0, 1),
            message("a", 0, 2),
            message("a", 0, 3),
            message("b", 0, 10),
        ];
        let runs = request.hand_back(handed_back).expect("every message");
        let shapes: Vec<_> = runs
            .iter()
            .map(|run| (&*run.routing_key, offsets(&run.messages)))
            .collect();
        assert_eq!(shapes, vec![("a", vec![1, 2, 3]), ("b", vec![10])]);
    }

    #[test]
    fn a_hand_back_missing_messages_is_an_error() {
        assert!(request().hand_back(vec![message("a", 0, 1)]).is_err());
    }

    #[test]
    fn a_partial_sorts_each_run_into_accepted_and_unfinished_in_send_order() {
        let partial_runs = request()
            .partially_accepted(2, vec![message("a", 0, 2), message("b", 0, 10)])
            .expect("matches the request");
        let shapes: Vec<_> = partial_runs
            .iter()
            .map(|run| {
                (
                    &*run.routing_key,
                    run.accepted
                        .iter()
                        .map(|sent| sent.offset)
                        .collect::<Vec<i64>>(),
                    offsets(&run.unfinished),
                )
            })
            .collect();
        assert_eq!(
            shapes,
            vec![("a", vec![1, 3], vec![2]), ("b", vec![], vec![10])]
        );
    }

    #[test]
    fn a_partial_matches_a_message_the_request_carries_twice_by_occurrence() {
        let mut requests = InFlightRequests::new();
        let id = requests.register(
            WorkerId::from("w"),
            FRESH,
            Instant::now(),
            &[run("a", &[1, 2, 1])],
        );
        let request = requests.take(id).expect("registered");
        let partial_runs = request
            .partially_accepted(2, vec![message("a", 0, 1)])
            .expect("matches the request");
        let run = &partial_runs[0];
        let accepted: Vec<i64> = run.accepted.iter().map(|sent| sent.offset).collect();
        assert_eq!((accepted, offsets(&run.unfinished)), (vec![2, 1], vec![1]));
    }

    #[rstest]
    #[case::empty(4, vec![])]
    #[case::not_in_the_request(3, vec![message("a", 0, 7)])]
    #[case::duplicate(2, vec![message("a", 0, 2), message("a", 0, 2)])]
    #[case::out_of_send_order(2, vec![message("a", 0, 3), message("a", 0, 2)])]
    #[case::count_mismatch(1, vec![message("a", 0, 2)])]
    fn a_partial_that_does_not_match_the_request_is_an_error(
        #[case] accepted_count: u32,
        #[case] unfinished: Vec<SerializedKafkaMessage>,
    ) {
        assert!(request()
            .partially_accepted(accepted_count, unfinished)
            .is_err());
    }
}
