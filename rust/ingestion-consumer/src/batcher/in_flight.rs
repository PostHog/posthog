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

pub struct InFlightRequest {
    pub worker: WorkerId,
    pub class: RequestClass,
    pub message_count: usize,
    runs: Vec<SentRun>,
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
    /// Every key's run, in send order, after the worker accepted the whole
    /// request.
    pub fn accepted(self) -> Vec<SentRun> {
        self.runs
    }

    /// The transport hands back every message of a failed request, in send
    /// order, so each key gets back exactly the run it sent.
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
}

#[cfg(test)]
mod tests {
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
}
