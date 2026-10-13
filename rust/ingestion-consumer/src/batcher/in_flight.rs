//! Remembers what each in-flight request carried, because a response names
//! its request only by id.

use std::collections::HashMap;
use std::sync::Arc;

use super::key_queues::KeyRun;
use super::request::RequestClass;
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RequestId(u64);

#[derive(Debug)]
pub struct SentMessage {
    pub partition: i32,
    pub offset: i64,
    pub keyed: bool,
}

impl SentMessage {
    fn of(message: &SerializedKafkaMessage) -> Self {
        Self {
            partition: message.partition,
            offset: message.offset,
            keyed: message.key.is_some(),
        }
    }
}

pub struct SentRun {
    pub routing_key: Arc<str>,
    pub messages: Vec<SentMessage>,
}

/// One run's share of a partial ack.
pub struct RunSplit {
    pub routing_key: Arc<str>,
    pub accepted: Vec<SentMessage>,
    /// How many of `accepted` come before the run's first unfinished message.
    pub accepted_prefix: usize,
    pub unfinished: Vec<SerializedKafkaMessage>,
}

pub struct InFlightRequest {
    pub worker: WorkerId,
    pub class: RequestClass,
    pub message_count: usize,
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
    pub fn split(
        self,
        accepted: u32,
        unfinished: Vec<SerializedKafkaMessage>,
    ) -> Result<Vec<RunSplit>, String> {
        if unfinished.is_empty() || accepted as usize + unfinished.len() != self.message_count {
            return Err(format!(
                "partial ack accepted {accepted} and left {} of {} messages unfinished",
                unfinished.len(),
                self.message_count
            ));
        }
        let mut unfinished = unfinished.into_iter().peekable();
        let splits = self
            .runs
            .into_iter()
            .map(|run| {
                let mut split = RunSplit {
                    routing_key: run.routing_key,
                    accepted: Vec::new(),
                    accepted_prefix: 0,
                    unfinished: Vec::new(),
                };
                for sent in run.messages {
                    let next = unfinished.next_if(|message| {
                        message.partition == sent.partition && message.offset == sent.offset
                    });
                    match next {
                        Some(message) => split.unfinished.push(message),
                        None => {
                            if split.unfinished.is_empty() {
                                split.accepted_prefix += 1;
                            }
                            split.accepted.push(sent);
                        }
                    }
                }
                split
            })
            .collect();
        if let Some(message) = unfinished.next() {
            return Err(format!(
                "partial ack lists {}:{} as unfinished, which the request does not carry at that point",
                message.partition, message.offset
            ));
        }
        Ok(splits)
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
    fn a_partial_splits_each_run_into_accepted_and_unfinished_in_send_order() {
        let splits = request()
            .split(2, vec![message("a", 0, 2), message("b", 0, 10)])
            .expect("matches the request");
        let shapes: Vec<_> = splits
            .iter()
            .map(|split| {
                (
                    &*split.routing_key,
                    split
                        .accepted
                        .iter()
                        .map(|sent| sent.offset)
                        .collect::<Vec<i64>>(),
                    split.accepted_prefix,
                    offsets(&split.unfinished),
                )
            })
            .collect();
        assert_eq!(
            shapes,
            vec![("a", vec![1, 3], 1, vec![2]), ("b", vec![], 0, vec![10])]
        );
    }

    #[rstest]
    #[case::empty(4, vec![])]
    #[case::not_in_the_request(3, vec![message("a", 0, 7)])]
    #[case::duplicate(2, vec![message("a", 0, 2), message("a", 0, 2)])]
    #[case::out_of_send_order(2, vec![message("a", 0, 3), message("a", 0, 2)])]
    #[case::count_mismatch(1, vec![message("a", 0, 2)])]
    fn a_partial_that_does_not_match_the_request_is_an_error(
        #[case] accepted: u32,
        #[case] unfinished: Vec<SerializedKafkaMessage>,
    ) {
        assert!(request().split(accepted, unfinished).is_err());
    }
}
