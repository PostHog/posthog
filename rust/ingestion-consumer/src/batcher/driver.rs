//! Runs the batcher state machine on one task and performs its effects.

use std::collections::HashSet;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use common_kafka_consumer::{AssignmentEpoch, GroupCompletion};
use futures::future::{BoxFuture, FutureExt};
use futures::stream::{FuturesUnordered, StreamExt};
use metrics::{counter, histogram};
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tracing::error;

use super::in_flight::RequestId;
use super::key_queues::KeyRun;
use super::state_machine::{BatcherStateMachine, Effects, FailureCause, SendRequest};
use super::worker_pool::WorkerPoolSource;
use super::{make_batch_id, BatcherOutputs};
use crate::grpc_transport::GrpcTransport;
use crate::order_sentinel::{KeyOrderSentinel, SendKind, SentinelBatch};
use crate::transport::SendError;
use crate::types::Accumulator;
use crate::worker_registry::WorkerId;

pub(super) struct StateMachineDriver {
    inputs: mpsc::UnboundedSender<Input>,
    assignment_epoch: AssignmentEpoch,
    key_sentinel: Arc<KeyOrderSentinel>,
    load: Arc<Load>,
    task: JoinHandle<()>,
}

enum Input {
    Groups {
        assignment_epoch: u64,
        runs: Vec<KeyRun>,
    },
    PartitionsRevoked(Vec<(String, i32)>),
    Shutdown,
}

#[derive(Debug, Default)]
pub(super) struct Load {
    pub pending_messages: AtomicUsize,
    pub in_flight_messages: AtomicUsize,
    pub busy_workers: Mutex<HashSet<WorkerId>>,
}

pub(super) struct RevokeSender(mpsc::UnboundedSender<Input>);

type Response = BoxFuture<'static, (RequestId, Result<u32, SendError>)>;

struct BatcherTask {
    inputs: mpsc::UnboundedReceiver<Input>,
    responses: FuturesUnordered<Response>,
    wakeup: Option<Instant>,
    pool_source: WorkerPoolSource,
    transport: Arc<GrpcTransport>,
    key_sentinel: Arc<KeyOrderSentinel>,
    completions: mpsc::UnboundedSender<GroupCompletion>,
    errors: mpsc::UnboundedSender<String>,
    load: Arc<Load>,
}

enum Event {
    Input(Input),
    Response(RequestId, Result<u32, SendError>),
    Wakeup,
}

impl StateMachineDriver {
    pub(super) fn new(
        state: BatcherStateMachine,
        pool_source: WorkerPoolSource,
        transport: Arc<GrpcTransport>,
    ) -> (Self, BatcherOutputs) {
        let (inputs_tx, inputs_rx) = mpsc::unbounded_channel();
        let (completions_tx, completions_rx) = mpsc::unbounded_channel();
        let (errors_tx, errors_rx) = mpsc::unbounded_channel();
        let load = Arc::new(Load::default());
        let key_sentinel = Arc::new(KeyOrderSentinel::new());
        let assignment_epoch = transport.assignment_epoch();
        let task = BatcherTask {
            inputs: inputs_rx,
            responses: FuturesUnordered::new(),
            wakeup: None,
            pool_source,
            transport,
            key_sentinel: Arc::clone(&key_sentinel),
            completions: completions_tx,
            errors: errors_tx,
            load: Arc::clone(&load),
        };
        let task = tokio::spawn(task.run(state));
        (
            Self {
                inputs: inputs_tx,
                assignment_epoch,
                key_sentinel,
                load,
                task,
            },
            BatcherOutputs {
                completions: completions_rx,
                errors: errors_rx,
            },
        )
    }

    pub(super) fn key_order_sentinel(&self) -> Arc<KeyOrderSentinel> {
        Arc::clone(&self.key_sentinel)
    }

    pub(super) fn load(&self) -> Arc<Load> {
        Arc::clone(&self.load)
    }

    pub(super) fn revoke_sender(&self) -> RevokeSender {
        RevokeSender(self.inputs.clone())
    }

    pub(super) fn submit(&self, accumulator: Accumulator) -> u64 {
        let assignment_epoch = self.assignment_epoch.current();
        let runs = KeyRun::from_groups(accumulator.into_groups());
        let unkeyed = runs
            .iter()
            .filter(|run| run.messages.first().is_some_and(|m| m.key.is_none()))
            .count();
        if unkeyed > 0 {
            counter!("ingestion_consumer_dispatcher_unkeyed_messages_total")
                .increment(unkeyed as u64);
        }
        histogram!("ingestion_consumer_routing_keys_per_batch").record(runs.len() as f64);
        self.send(Input::Groups {
            assignment_epoch,
            runs,
        });
        assignment_epoch
    }

    pub(super) fn begin_shutdown(&self) {
        self.send(Input::Shutdown);
    }

    fn send(&self, input: Input) {
        if self.inputs.send(input).is_err() {
            error!("Batcher task is gone");
        }
    }
}

impl Drop for StateMachineDriver {
    fn drop(&mut self) {
        self.task.abort();
    }
}

impl RevokeSender {
    /// Called from the rebalance callback inside the consumer loop's Kafka
    /// poll, so it queues the revoke rather than waiting for it. The revoke
    /// lands between the polls submitted before and after the rebalance.
    pub(super) fn purge_revoked(&self, partitions: &[(String, i32)]) {
        let _ = self.0.send(Input::PartitionsRevoked(partitions.to_vec()));
    }
}

impl BatcherTask {
    async fn run(mut self, mut state: BatcherStateMachine) {
        loop {
            let wakeup = self.wakeup;
            let event = tokio::select! {
                // Inputs first, so a revoke applies before a response ready at
                // the same time can send a revoked key.
                biased;
                input = self.inputs.recv() => match input {
                    Some(input) => Event::Input(input),
                    None => return,
                },
                Some((request, result)) = self.responses.next(), if !self.responses.is_empty() => {
                    Event::Response(request, result)
                }
                _ = sleep_until(wakeup), if wakeup.is_some() => Event::Wakeup,
            };
            state = self.handle(state, event);
        }
    }

    fn handle(&mut self, state: BatcherStateMachine, event: Event) -> BatcherStateMachine {
        let now = Instant::now();
        let mut assigned = false;
        let mut fence_guard = None;
        let (state, effects) = match event {
            Event::Input(Input::Groups {
                assignment_epoch,
                runs,
            }) => {
                assigned = true;
                state.on_groups(now, &self.pool_source.candidates(), assignment_epoch, runs)
            }
            Event::Input(Input::PartitionsRevoked(partitions)) => {
                // Cleared in order with the sends, so no revoked message is
                // noted as sent after the revoke.
                self.key_sentinel.clear();
                state.on_partitions_revoked(now, &partitions)
            }
            Event::Input(Input::Shutdown) => state.on_shutdown(now, &self.pool_source.candidates()),
            Event::Response(request, Ok(accepted)) => {
                state.on_request_succeeded(now, &self.pool_source.candidates(), request, accepted)
            }
            Event::Response(request, Err(failure)) => {
                // Backpressure is transient, not a worker fault.
                let cause = if failure.error.is_backpressure() {
                    FailureCause::Busy
                } else {
                    FailureCause::Fault
                };
                fence_guard = failure.fence_guard;
                state.on_request_failed(
                    now,
                    &self.pool_source.candidates(),
                    request,
                    cause,
                    failure.messages,
                )
            }
            Event::Wakeup => state.on_wakeup(now, &self.pool_source.candidates()),
        };
        self.perform(&state, effects);
        // The worker stream takes no new send until the failed messages are
        // requeued.
        drop(fence_guard);
        if assigned {
            histogram!("ingestion_consumer_assign_duration_seconds")
                .record(now.elapsed().as_secs_f64());
        }
        state
    }

    fn perform(&mut self, state: &BatcherStateMachine, effects: Effects) {
        let Effects {
            sends,
            completions,
            key_acks,
            evicted_keys,
            worker_outcomes,
            idle_workers,
            busy_workers,
            fatal,
            next_wakeup,
        } = effects;
        let key_sentinel = Arc::clone(&self.key_sentinel);
        let mut sentinel = key_sentinel.batch();
        for ack in &key_acks {
            sentinel.note_acked(&ack.routing_key, ack.max_offset);
        }
        for key in &evicted_keys {
            sentinel.evict(key);
        }
        for send in sends {
            self.begin(send, &mut sentinel);
        }
        drop(sentinel);

        // A worker can go idle and then busy in one action, never the reverse.
        if !idle_workers.is_empty() || !busy_workers.is_empty() {
            let mut busy = self.load.busy_workers.lock().unwrap();
            for worker in &idle_workers {
                busy.remove(worker);
            }
            busy.extend(busy_workers);
        }

        let registry = self.pool_source.registry();
        for outcome in worker_outcomes {
            registry.record_outcome(&outcome.worker, outcome.fault);
        }
        for worker in idle_workers {
            if registry.is_draining(&worker) {
                registry.complete_drain(&worker);
            }
        }
        for completion in completions {
            counter!("ingestion_consumer_group_completions_total").increment(1);
            counter!("ingestion_consumer_group_completion_accepted_messages_total")
                .increment(completion.accepted as u64);
            let _ = self.completions.send(completion);
        }
        if let Some(reason) = fatal {
            error!(error = %reason, "Batcher failure");
            if self.errors.send(reason).is_err() {
                error!("Batcher error channel closed; consumer is gone");
            }
        }
        self.wakeup = next_wakeup;
        self.load
            .pending_messages
            .store(state.pending_messages(), Ordering::Relaxed);
        self.load
            .in_flight_messages
            .store(state.in_flight_messages(), Ordering::Relaxed);
    }

    fn begin(&mut self, send: SendRequest, sentinel: &mut SentinelBatch<'_>) {
        let kind = if send.class.replay {
            SendKind::Resend
        } else {
            SendKind::Fresh
        };
        let mut messages = Vec::new();
        for run in send.runs {
            sentinel.note_sent(&run.routing_key, &run.messages, kind);
            messages.extend(run.messages);
        }
        let pending =
            self.transport
                .begin_send(&send.worker, &make_batch_id(), messages, send.class.replay);
        let request = send.request;
        self.responses
            .push(async move { (request, pending.wait().await) }.boxed());
    }
}

async fn sleep_until(wakeup: Option<Instant>) {
    match wakeup {
        Some(at) => tokio::time::sleep_until(at.into()).await,
        None => std::future::pending().await,
    }
}
