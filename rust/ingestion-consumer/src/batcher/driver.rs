//! Runs the batcher state machine on one task and performs its effects.

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use common_kafka_consumer::{AssignmentEpoch, GroupCompletion};
use futures::future::{BoxFuture, FutureExt};
use futures::stream::{FuturesUnordered, StreamExt};
use metrics::{counter, histogram};
use tokio::sync::{mpsc, oneshot};
use tokio::task::JoinHandle;
use tracing::error;

use super::governor::Adaptation;
use super::in_flight::RequestId;
use super::key_queues::{payload_bytes, KeyRun};
use super::state_machine::{
    BatcherSnapshot, BatcherStateMachine, Effects, FailureCause, SendRequest,
};
use super::worker_pool::WorkerPoolSource;
use super::{make_batch_id, BatcherOutputs};
use crate::debug_recorder::{partition_offsets, record_if, DebugEventKind, DebugRecorder};
use crate::grpc_transport::{GrpcTransport, SendOptions};
use crate::order_sentinel::{KeyOrderSentinel, SendKind, SentinelBatch};
use crate::transport::{SendError, SendOutcome};
use crate::types::{Accumulator, SerializedKafkaMessage};
use crate::worker_registry::WorkerId;

/// A task that does not answer within this is wedged; the debug API then
/// falls back to the totals the task last published.
const SNAPSHOT_TIMEOUT: Duration = Duration::from_secs(1);

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
    /// Answered between two actions, so the snapshot is consistent.
    Snapshot(oneshot::Sender<BatcherSnapshot>),
}

#[derive(Debug, Default)]
pub(super) struct Load {
    pub pending_messages: AtomicUsize,
    pub in_flight_messages: AtomicUsize,
    pub busy_workers: Mutex<HashSet<WorkerId>>,
    /// Fixed at startup, so a snapshot that falls back to the totals still
    /// reports it.
    pub adaptation: Adaptation,
}

pub(super) struct RevokeSender(mpsc::UnboundedSender<Input>);

#[derive(Clone)]
pub(super) struct SnapshotSender(mpsc::UnboundedSender<Input>);

impl SnapshotSender {
    /// `None` when the task is gone or does not answer in time.
    pub(super) async fn snapshot(&self) -> Option<BatcherSnapshot> {
        let (reply, response) = oneshot::channel();
        self.0.send(Input::Snapshot(reply)).ok()?;
        tokio::time::timeout(SNAPSHOT_TIMEOUT, response)
            .await
            .ok()?
            .ok()
    }
}

pub(super) trait RequestSender: Send + Sync + 'static {
    fn assignment_epoch(&self) -> AssignmentEpoch;

    fn send(
        &self,
        worker: &WorkerId,
        messages: Vec<SerializedKafkaMessage>,
        options: SendOptions,
    ) -> BoxFuture<'static, Result<SendOutcome, SendError>>;
}

pub(super) trait Workers: Send + 'static {
    fn candidates(&self) -> Vec<WorkerId>;

    fn record_outcome(&self, worker: &WorkerId, fault: bool);

    /// Completes the worker's drain if it is draining.
    fn idle(&self, worker: &WorkerId);
}

impl RequestSender for GrpcTransport {
    fn assignment_epoch(&self) -> AssignmentEpoch {
        GrpcTransport::assignment_epoch(self)
    }

    fn send(
        &self,
        worker: &WorkerId,
        messages: Vec<SerializedKafkaMessage>,
        options: SendOptions,
    ) -> BoxFuture<'static, Result<SendOutcome, SendError>> {
        self.begin_send_with(worker, &make_batch_id(), messages, options)
            .wait()
            .boxed()
    }
}

impl Workers for WorkerPoolSource {
    fn candidates(&self) -> Vec<WorkerId> {
        WorkerPoolSource::candidates(self)
    }

    fn record_outcome(&self, worker: &WorkerId, fault: bool) {
        self.registry().record_outcome(worker, fault);
    }

    fn idle(&self, worker: &WorkerId) {
        let registry = self.registry();
        if registry.is_draining(worker) {
            registry.complete_drain(worker);
        }
    }
}

type Response = BoxFuture<'static, (RequestId, Result<SendOutcome, SendError>)>;

struct BatcherTask<S, W> {
    inputs: mpsc::UnboundedReceiver<Input>,
    responses: FuturesUnordered<Response>,
    wakeup: Option<Instant>,
    workers: W,
    sender: Arc<S>,
    key_sentinel: Arc<KeyOrderSentinel>,
    completions: mpsc::UnboundedSender<GroupCompletion>,
    errors: mpsc::UnboundedSender<String>,
    load: Arc<Load>,
    recorder: Option<Arc<DebugRecorder>>,
    /// The worker of each request sent while a recorder is present.
    debug_requests: HashMap<RequestId, WorkerId>,
}

enum Event {
    Input(Input),
    Response(RequestId, Result<SendOutcome, SendError>),
    Wakeup,
}

impl StateMachineDriver {
    pub(super) fn new<S: RequestSender, W: Workers>(
        state: BatcherStateMachine,
        workers: W,
        sender: Arc<S>,
        recorder: Option<Arc<DebugRecorder>>,
    ) -> (Self, BatcherOutputs) {
        let (inputs_tx, inputs_rx) = mpsc::unbounded_channel();
        let (completions_tx, completions_rx) = mpsc::unbounded_channel();
        let (errors_tx, errors_rx) = mpsc::unbounded_channel();
        let load = Arc::new(Load {
            adaptation: state.snapshot().governor.adaptation,
            ..Load::default()
        });
        let key_sentinel = Arc::new(KeyOrderSentinel::new());
        let assignment_epoch = sender.assignment_epoch();
        let task = BatcherTask {
            inputs: inputs_rx,
            responses: FuturesUnordered::new(),
            wakeup: None,
            workers,
            sender,
            key_sentinel: Arc::clone(&key_sentinel),
            completions: completions_tx,
            errors: errors_tx,
            load: Arc::clone(&load),
            recorder,
            debug_requests: HashMap::new(),
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

    pub(super) fn snapshot_sender(&self) -> SnapshotSender {
        SnapshotSender(self.inputs.clone())
    }

    pub(super) fn submit(&self, accumulator: Accumulator) -> u64 {
        let assignment_epoch = self.assignment_epoch.current();
        let runs = KeyRun::from_groups(accumulator.into_groups());
        let unkeyed: usize = runs
            .iter()
            .filter(|run| run.messages.first().is_some_and(|m| m.key.is_none()))
            .map(|run| run.messages.len())
            .sum();
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

impl<S: RequestSender, W: Workers> BatcherTask<S, W> {
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
        // A snapshot changes nothing and must not replace the pending wakeup.
        let event = match event {
            Event::Input(Input::Snapshot(reply)) => {
                let _ = reply.send(state.snapshot());
                return state;
            }
            event => event,
        };
        // Read through tokio, so tests on paused time control the clock.
        let now = tokio::time::Instant::now().into_std();
        let mut assigned = false;
        let (state, effects) = match event {
            Event::Input(Input::Groups {
                assignment_epoch,
                runs,
            }) => {
                assigned = true;
                state.on_groups(now, &self.workers.candidates(), assignment_epoch, runs)
            }
            Event::Input(Input::PartitionsRevoked(partitions)) => {
                // Cleared in order with the sends, so no revoked message is
                // noted as sent after the revoke.
                self.key_sentinel.clear();
                state.on_partitions_revoked(now, &partitions)
            }
            Event::Input(Input::Shutdown) => state.on_shutdown(now, &self.workers.candidates()),
            Event::Input(Input::Snapshot(_)) => unreachable!("answered above"),
            Event::Response(request, Ok(SendOutcome::Accepted(accepted))) => {
                self.record_resolved(request, accepted, 0);
                state.on_request_succeeded(now, &self.workers.candidates(), request, accepted)
            }
            Event::Response(
                request,
                Ok(SendOutcome::Partial {
                    accepted,
                    unfinished,
                }),
            ) => {
                self.record_resolved(request, accepted, unfinished.len());
                state.on_request_partial(
                    now,
                    &self.workers.candidates(),
                    request,
                    accepted,
                    unfinished,
                )
            }
            Event::Response(request, Err(failure)) => {
                // Backpressure is transient, not a worker fault.
                let cause = if failure.error.is_backpressure() {
                    FailureCause::Busy
                } else {
                    FailureCause::Fault
                };
                self.record_failed(request, cause, failure.messages.len());
                let requeued = state.on_request_failed(
                    now,
                    &self.workers.candidates(),
                    request,
                    cause,
                    failure.messages,
                );
                // The worker stream takes no new send until the failed
                // messages are requeued. Released before this action's
                // sends, which can go to the same stream.
                drop(failure.fence_guard);
                requeued
            }
            Event::Wakeup => state.on_wakeup(now, &self.workers.candidates()),
        };
        self.perform(&state, effects);
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

        for outcome in worker_outcomes {
            self.workers.record_outcome(&outcome.worker, outcome.fault);
        }
        for worker in idle_workers {
            self.workers.idle(&worker);
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
        let routing_keys = send.runs.len();
        let mut messages = Vec::new();
        for run in send.runs {
            sentinel.note_sent(&run.routing_key, &run.messages, kind);
            messages.extend(run.messages);
        }
        counter!(
            "ingestion_consumer_batcher_requests_sent_total",
            "worker" => send.worker.clone()
        )
        .increment(1);
        counter!(
            "ingestion_consumer_batcher_messages_sent_total",
            "worker" => send.worker.clone()
        )
        .increment(messages.len() as u64);
        if self.recorder.is_some() {
            self.debug_requests
                .insert(send.request, send.worker.clone());
        }
        record_if(&self.recorder, || DebugEventKind::RequestSent {
            request_id: send.request.as_u64(),
            worker: send.worker.to_string(),
            messages: messages.len(),
            routing_keys,
            bytes: payload_bytes(&messages),
            replay: send.class.replay,
            budgeted: send.soft_budget.is_some(),
            assignment_epoch: send.class.assignment_epoch,
            spans: partition_offsets(&messages),
        });
        let options = SendOptions {
            replay: send.class.replay,
            soft_budget: send.soft_budget,
        };
        let response = self.sender.send(&send.worker, messages, options);
        let request = send.request;
        self.responses
            .push(async move { (request, response.await) }.boxed());
    }

    fn record_resolved(&mut self, request: RequestId, accepted: u32, unfinished: usize) {
        if let Some(worker) = self.debug_requests.remove(&request) {
            record_if(&self.recorder, || DebugEventKind::RequestResolved {
                request_id: request.as_u64(),
                worker: worker.to_string(),
                accepted,
                unfinished,
            });
        }
    }

    fn record_failed(&mut self, request: RequestId, cause: FailureCause, messages: usize) {
        if let Some(worker) = self.debug_requests.remove(&request) {
            record_if(&self.recorder, || DebugEventKind::RequestFailed {
                request_id: request.as_u64(),
                worker: worker.to_string(),
                cause: match cause {
                    FailureCause::Busy => "busy",
                    FailureCause::Fault => "fault",
                },
                messages,
            });
        }
    }
}

async fn sleep_until(wakeup: Option<Instant>) {
    match wakeup {
        Some(at) => tokio::time::sleep_until(tokio::time::Instant::from_std(at)).await,
        None => std::future::pending().await,
    }
}

#[cfg(test)]
mod tests {
    use std::num::{NonZeroU32, NonZeroUsize};
    use std::time::Duration;

    use rstest::rstest;

    use super::*;
    use crate::batcher::packer::{PackTargets, Packer};
    use crate::batcher::retry_policy::RetryPolicy;
    use crate::batcher::state_machine::RequestBudget;
    use crate::batcher::test_support::{message, offsets};
    use crate::batcher::worker_assigner::{WorkerAssigner, WorkerInFlight};
    use crate::routing::{Router, RoutingStrategy};
    use crate::transport::{FenceGuard, TransportError};

    const FAULT_DELAY: Duration = Duration::from_millis(200);
    const BUSY_DELAY: Duration = Duration::from_millis(20);
    const NO_WORKER_DELAY: Duration = Duration::from_millis(100);
    const STALL: Duration = Duration::from_secs(60);

    struct Sent {
        worker: WorkerId,
        offsets: Vec<i64>,
        replay: bool,
        soft_budget: Option<Duration>,
        fence_released: Option<bool>,
        reply: oneshot::Sender<Result<SendOutcome, SendError>>,
    }

    struct FakeSender {
        assignment_epoch: AssignmentEpoch,
        sent: Mutex<Vec<Sent>>,
        fence: Mutex<Option<mpsc::UnboundedReceiver<()>>>,
    }

    impl RequestSender for FakeSender {
        fn assignment_epoch(&self) -> AssignmentEpoch {
            self.assignment_epoch.clone()
        }

        fn send(
            &self,
            worker: &WorkerId,
            messages: Vec<SerializedKafkaMessage>,
            options: SendOptions,
        ) -> BoxFuture<'static, Result<SendOutcome, SendError>> {
            let fence_released = self
                .fence
                .lock()
                .unwrap()
                .as_mut()
                .map(|released| released.try_recv().is_ok());
            let (reply, response) = oneshot::channel();
            self.sent.lock().unwrap().push(Sent {
                worker: worker.clone(),
                offsets: offsets(&messages),
                replay: options.replay,
                soft_budget: options.soft_budget,
                fence_released,
                reply,
            });
            async move { response.await.expect("the test replies to every send") }.boxed()
        }
    }

    #[derive(Default)]
    struct WorkersState {
        candidates: Vec<WorkerId>,
        outcomes: Vec<(WorkerId, bool)>,
        idle: Vec<WorkerId>,
    }

    #[derive(Clone, Default)]
    struct FakeWorkers(Arc<Mutex<WorkersState>>);

    impl Workers for FakeWorkers {
        fn candidates(&self) -> Vec<WorkerId> {
            self.0.lock().unwrap().candidates.clone()
        }

        fn record_outcome(&self, worker: &WorkerId, fault: bool) {
            self.0
                .lock()
                .unwrap()
                .outcomes
                .push((worker.clone(), fault));
        }

        fn idle(&self, worker: &WorkerId) {
            self.0.lock().unwrap().idle.push(worker.clone());
        }
    }

    struct Harness {
        driver: StateMachineDriver,
        outputs: BatcherOutputs,
        sender: Arc<FakeSender>,
        workers: FakeWorkers,
    }

    impl Harness {
        fn new(workers: &[&str], max_requests_per_worker: usize) -> Self {
            Self::build(workers, max_requests_per_worker, None, None)
        }

        fn budgeted(
            workers: &[&str],
            max_requests_per_worker: usize,
            budget: Option<RequestBudget>,
        ) -> Self {
            Self::build(workers, max_requests_per_worker, budget, None)
        }

        fn recorded(
            workers: &[&str],
            max_requests_per_worker: usize,
        ) -> (Self, Arc<DebugRecorder>) {
            let recorder = DebugRecorder::new(64, Duration::from_secs(60));
            let harness = Self::build(
                workers,
                max_requests_per_worker,
                None,
                Some(Arc::clone(&recorder)),
            );
            (harness, recorder)
        }

        fn build(
            workers: &[&str],
            max_requests_per_worker: usize,
            budget: Option<RequestBudget>,
            recorder: Option<Arc<DebugRecorder>>,
        ) -> Self {
            let assigner =
                WorkerAssigner::new(Router::new(RoutingStrategy::P2c), max_requests_per_worker)
                    .expect("valid request cap");
            let retry = RetryPolicy::new(FAULT_DELAY, BUSY_DELAY, NO_WORKER_DELAY)
                .expect("valid retry policy");
            let packer = Packer::new(PackTargets {
                events: NonZeroUsize::new(1),
                bytes: None,
                latency_budget: Duration::ZERO,
            });
            let state = BatcherStateMachine::new(
                packer,
                assigner,
                retry,
                STALL,
                tokio::time::Instant::now().into_std(),
            )
            .expect("valid stall timeout")
            .with_request_budget(budget);
            let fake_workers = FakeWorkers::default();
            fake_workers.set_candidates(workers);
            let sender = Arc::new(FakeSender {
                assignment_epoch: AssignmentEpoch::new(),
                sent: Mutex::new(Vec::new()),
                fence: Mutex::new(None),
            });
            let (driver, outputs) =
                StateMachineDriver::new(state, fake_workers.clone(), Arc::clone(&sender), recorder);
            Self {
                driver,
                outputs,
                sender,
                workers: fake_workers,
            }
        }

        fn submit(&self, runs: Vec<KeyRun>) {
            self.driver.send(Input::Groups {
                assignment_epoch: 0,
                runs,
            });
        }

        fn take_sent(&self) -> Vec<Sent> {
            std::mem::take(&mut *self.sender.sent.lock().unwrap())
        }

        fn completed_offsets(&mut self) -> Vec<i64> {
            let mut completed = Vec::new();
            while let Ok(completion) = self.outputs.completions.try_recv() {
                completed.extend(completion.offsets.iter().map(|offset| offset.0));
            }
            completed
        }
    }

    impl FakeWorkers {
        fn set_candidates(&self, workers: &[&str]) {
            self.0.lock().unwrap().candidates =
                workers.iter().map(|w| WorkerId::from(*w)).collect();
        }

        fn outcomes(&self) -> Vec<(WorkerId, bool)> {
            self.0.lock().unwrap().outcomes.clone()
        }

        fn idle(&self) -> Vec<WorkerId> {
            self.0.lock().unwrap().idle.clone()
        }
    }

    /// Lets the batcher task handle everything queued for it.
    async fn settle() {
        for _ in 0..8 {
            tokio::task::yield_now().await;
        }
    }

    fn run(key: &str, offsets: &[i64]) -> KeyRun {
        KeyRun {
            routing_key: key.into(),
            messages: offsets
                .iter()
                .map(|&offset| message(key, 0, offset))
                .collect(),
        }
    }

    fn busy(sent: &Sent, fence_guard: Option<FenceGuard>) -> SendError {
        SendError {
            error: TransportError::WorkerStreamBusy("test"),
            messages: sent
                .offsets
                .iter()
                .map(|&offset| message("a", 0, offset))
                .collect(),
            fence_guard,
        }
    }

    #[tokio::test(start_paused = true)]
    async fn an_accepted_send_completes_its_offsets_and_idles_the_worker() {
        let mut h = Harness::new(&["w"], 4);
        h.submit(vec![run("a", &[1])]);
        settle().await;

        let sent = h.take_sent();
        assert_eq!(sent.len(), 1);
        assert_eq!(sent[0].worker, WorkerId::from("w"));
        assert_eq!(sent[0].offsets, vec![1]);
        assert!(!sent[0].replay);

        let send = sent.into_iter().next().unwrap();
        send.reply.send(Ok(SendOutcome::Accepted(1))).unwrap();
        settle().await;
        assert_eq!(h.completed_offsets(), vec![1]);
        assert_eq!(h.workers.outcomes(), vec![(WorkerId::from("w"), false)]);
        assert_eq!(h.workers.idle(), vec![WorkerId::from("w")]);
    }

    #[tokio::test(start_paused = true)]
    async fn a_partial_response_resends_its_unfinished_messages_at_once_as_replay() {
        let budget = Duration::from_millis(250);
        let mut h = Harness::budgeted(
            &["w"],
            4,
            Some(RequestBudget {
                soft_budget: budget,
                attempts: NonZeroU32::new(3).expect("nonzero attempts"),
            }),
        );
        h.submit(vec![run("a", &[1])]);
        settle().await;
        let send = h.take_sent().pop().unwrap();
        assert_eq!(send.soft_budget, Some(budget));

        send.reply
            .send(Ok(SendOutcome::Partial {
                accepted: 0,
                unfinished: vec![message("a", 0, 1)],
            }))
            .unwrap();
        settle().await;
        assert!(h.completed_offsets().is_empty());
        assert_eq!(h.workers.outcomes(), vec![(WorkerId::from("w"), false)]);
        let resend = h.take_sent();
        assert_eq!(resend.len(), 1, "the resend waits for no retry delay");
        assert!(resend[0].replay);
        assert_eq!(resend[0].offsets, vec![1]);
        assert_eq!(
            resend[0].soft_budget, None,
            "a request that finished nothing resends without a budget"
        );

        let resend = resend.into_iter().next().unwrap();
        resend.reply.send(Ok(SendOutcome::Accepted(1))).unwrap();
        settle().await;
        assert_eq!(h.completed_offsets(), vec![1]);
    }

    #[tokio::test(start_paused = true)]
    async fn a_busy_send_replays_after_the_busy_delay() {
        let h = Harness::new(&["w"], 4);
        h.submit(vec![run("a", &[1])]);
        settle().await;
        let send = h.take_sent().pop().unwrap();
        let failure = busy(&send, None);
        send.reply.send(Err(failure)).unwrap();
        settle().await;
        assert!(h.take_sent().is_empty());
        assert_eq!(h.workers.outcomes(), vec![(WorkerId::from("w"), false)]);

        tokio::time::advance(BUSY_DELAY - Duration::from_millis(1)).await;
        settle().await;
        assert!(h.take_sent().is_empty(), "the retry waits for its delay");

        tokio::time::advance(Duration::from_millis(1)).await;
        settle().await;
        let replay = h.take_sent();
        assert_eq!(replay.len(), 1);
        assert!(replay[0].replay);
        assert_eq!(replay[0].offsets, vec![1]);
    }

    #[tokio::test(start_paused = true)]
    async fn a_failed_send_counts_against_the_worker() {
        let h = Harness::new(&["w"], 4);
        h.submit(vec![run("a", &[1])]);
        settle().await;
        let send = h.take_sent().pop().unwrap();
        send.reply
            .send(Err(SendError {
                error: TransportError::WorkerStreamFailed("test"),
                messages: vec![message("a", 0, 1)],
                fence_guard: None,
            }))
            .unwrap();
        settle().await;
        assert_eq!(h.workers.outcomes(), vec![(WorkerId::from("w"), true)]);
    }

    #[tokio::test(start_paused = true)]
    async fn a_failed_sends_fence_is_released_before_the_next_send_to_its_worker() {
        let h = Harness::new(&["w"], 1);
        h.submit(vec![run("a", &[1]), run("b", &[2])]);
        settle().await;
        let send = h.take_sent().pop().unwrap();
        assert_eq!(send.offsets, vec![1], "b waits for the only slot");

        let (release, released) = mpsc::unbounded_channel();
        *h.sender.fence.lock().unwrap() = Some(released);
        let failure = busy(&send, Some(FenceGuard::new(release)));
        send.reply.send(Err(failure)).unwrap();
        settle().await;

        let next = h.take_sent();
        assert_eq!(next.len(), 1);
        assert_eq!(next[0].offsets, vec![2]);
        assert_eq!(next[0].fence_released, Some(true));
    }

    #[tokio::test(start_paused = true)]
    async fn a_revoke_queued_with_a_ready_response_applies_first() {
        let mut h = Harness::new(&["w"], 4);
        h.submit(vec![run("a", &[1])]);
        settle().await;
        h.submit(vec![run("a", &[2])]);
        settle().await;
        let send = h.take_sent().pop().unwrap();

        send.reply.send(Ok(SendOutcome::Accepted(1))).unwrap();
        h.driver
            .revoke_sender()
            .purge_revoked(&[("events".to_string(), 0)]);
        settle().await;

        assert!(
            h.take_sent().is_empty(),
            "a's queued message was revoked before the response released a"
        );
        assert_eq!(h.completed_offsets(), vec![1]);
    }

    #[tokio::test(start_paused = true)]
    async fn a_revoke_clears_the_order_sentinel() {
        let h = Harness::new(&["w"], 4);
        h.submit(vec![run("a", &[1])]);
        settle().await;
        let sentinel = h.driver.key_order_sentinel();
        assert_eq!(sentinel.key_count(), 1);

        h.driver
            .revoke_sender()
            .purge_revoked(&[("events".to_string(), 9)]);
        settle().await;
        assert_eq!(sentinel.key_count(), 0);
    }

    #[tokio::test(start_paused = true)]
    async fn the_load_tracks_pending_in_flight_and_busy_workers() {
        let h = Harness::new(&[], 2);
        let load = h.driver.load();
        h.submit(vec![run("a", &[1]), run("b", &[2])]);
        settle().await;
        assert_eq!(load.pending_messages.load(Ordering::Relaxed), 2);
        assert!(load.busy_workers.lock().unwrap().is_empty());

        h.workers.set_candidates(&["w"]);
        tokio::time::advance(NO_WORKER_DELAY).await;
        settle().await;
        assert_eq!(load.pending_messages.load(Ordering::Relaxed), 0);
        assert_eq!(load.in_flight_messages.load(Ordering::Relaxed), 2);
        assert_eq!(
            *load.busy_workers.lock().unwrap(),
            HashSet::from([WorkerId::from("w")])
        );

        let mut sent = h.take_sent();
        let accepted = |send: &Sent| send.offsets.len() as u32;
        let first = sent.remove(0);
        let count = accepted(&first);
        first.reply.send(Ok(SendOutcome::Accepted(count))).unwrap();
        settle().await;
        assert!(!load.busy_workers.lock().unwrap().is_empty());

        let last = sent.remove(0);
        let count = accepted(&last);
        last.reply.send(Ok(SendOutcome::Accepted(count))).unwrap();
        settle().await;
        assert!(load.busy_workers.lock().unwrap().is_empty());
        assert_eq!(load.in_flight_messages.load(Ordering::Relaxed), 0);
    }

    #[tokio::test(start_paused = true)]
    async fn a_state_machine_failure_reaches_the_error_channel() {
        let mut h = Harness::new(&["w"], 4);
        h.submit(vec![run("a", &[1])]);
        settle().await;
        let send = h.take_sent().pop().unwrap();
        send.reply.send(Ok(SendOutcome::Accepted(2))).unwrap();
        settle().await;
        assert!(h.outputs.errors.try_recv().is_ok());
    }

    #[tokio::test(start_paused = true)]
    async fn dropping_the_driver_stops_its_task() {
        let h = Harness::new(&["w"], 4);
        let sender = Arc::clone(&h.sender);
        assert_eq!(Arc::strong_count(&sender), 3);
        drop(h);
        settle().await;
        assert_eq!(Arc::strong_count(&sender), 1);
    }

    #[tokio::test(start_paused = true)]
    async fn a_snapshot_answers_through_the_task_with_the_live_load() {
        let h = Harness::new(&["w"], 4);
        let snapshots = h.driver.snapshot_sender();
        h.submit(vec![run("a", &[1]), run("b", &[2])]);
        settle().await;

        let snapshot = snapshots.snapshot().await.expect("the task answers");
        assert_eq!(snapshot.keys, 2);
        assert_eq!(snapshot.claimed_keys, 2);
        assert_eq!(snapshot.in_flight_requests, 2);
        assert_eq!(snapshot.in_flight_messages, 2);
        assert_eq!(snapshot.pending_messages, 0);
        assert_eq!(
            snapshot.per_worker,
            vec![WorkerInFlight {
                worker: WorkerId::from("w"),
                requests: 2,
                messages: 2,
            }]
        );

        drop(h);
        settle().await;
        assert!(
            snapshots.snapshot().await.is_none(),
            "a dropped batcher answers nothing"
        );
    }

    #[rstest]
    #[case::accepted(SendOutcome::Accepted(1))]
    #[case::a_partial_that_finished_nothing(SendOutcome::Partial {
        accepted: 0,
        unfinished: vec![message("a", 0, 1)],
    })]
    #[tokio::test(start_paused = true)]
    async fn the_rtt_sample_is_the_time_between_dispatch_and_settlement(
        #[case] outcome: SendOutcome,
    ) {
        let h = Harness::new(&["w"], 4);
        let snapshots = h.driver.snapshot_sender();
        h.submit(vec![run("a", &[1])]);
        settle().await;
        let send = h.take_sent().pop().unwrap();

        let rtt = Duration::from_millis(750);
        tokio::time::advance(rtt).await;
        send.reply.send(Ok(outcome)).unwrap();
        settle().await;
        let snapshot = snapshots.snapshot().await.expect("the task answers");
        assert_eq!(snapshot.governor.rtt, Some(rtt));
    }

    #[tokio::test(start_paused = true)]
    async fn request_events_follow_a_failed_send_and_its_replay() {
        let (h, recorder) = Harness::recorded(&["w"], 4);
        h.submit(vec![run("a", &[1])]);
        settle().await;
        let send = h.take_sent().pop().unwrap();
        let failure = busy(&send, None);
        send.reply.send(Err(failure)).unwrap();
        settle().await;
        tokio::time::advance(BUSY_DELAY).await;
        settle().await;
        let replay = h.take_sent().pop().unwrap();
        replay.reply.send(Ok(SendOutcome::Accepted(1))).unwrap();
        settle().await;

        let events: Vec<String> = recorder
            .backlog()
            .into_iter()
            .map(|event| match event.kind {
                DebugEventKind::RequestSent {
                    request_id,
                    worker,
                    messages,
                    routing_keys,
                    replay,
                    spans,
                    ..
                } => format!(
                    "sent #{request_id} {worker} {messages} msgs {routing_keys} keys replay={replay} spans={:?}",
                    spans
                        .iter()
                        .map(|span| (span.partition, span.ranges.clone()))
                        .collect::<Vec<_>>()
                ),
                DebugEventKind::RequestFailed {
                    request_id,
                    worker,
                    cause,
                    messages,
                } => format!("failed #{request_id} {worker} {cause} {messages} msgs"),
                DebugEventKind::RequestResolved {
                    request_id,
                    worker,
                    accepted,
                    unfinished,
                } => format!("resolved #{request_id} {worker} {accepted}/{unfinished}"),
                _ => "other".to_string(),
            })
            .collect();
        assert_eq!(
            events,
            vec![
                "sent #0 w 1 msgs 1 keys replay=false spans=[(0, [(1, 1)])]",
                "failed #0 w busy 1 msgs",
                "sent #1 w 1 msgs 1 keys replay=true spans=[(0, [(1, 1)])]",
                "resolved #1 w 1/0",
            ]
        );
    }
}
