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
use crate::types::{Accumulator, SerializedKafkaMessage};
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

pub(super) trait RequestSender: Send + Sync + 'static {
    fn assignment_epoch(&self) -> AssignmentEpoch;

    fn send(
        &self,
        worker: &WorkerId,
        messages: Vec<SerializedKafkaMessage>,
        replay: bool,
    ) -> BoxFuture<'static, Result<u32, SendError>>;
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
        replay: bool,
    ) -> BoxFuture<'static, Result<u32, SendError>> {
        self.begin_send(worker, &make_batch_id(), messages, replay)
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

type Response = BoxFuture<'static, (RequestId, Result<u32, SendError>)>;

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
}

enum Event {
    Input(Input),
    Response(RequestId, Result<u32, SendError>),
    Wakeup,
}

impl StateMachineDriver {
    pub(super) fn new<S: RequestSender, W: Workers>(
        state: BatcherStateMachine,
        workers: W,
        sender: Arc<S>,
    ) -> (Self, BatcherOutputs) {
        let (inputs_tx, inputs_rx) = mpsc::unbounded_channel();
        let (completions_tx, completions_rx) = mpsc::unbounded_channel();
        let (errors_tx, errors_rx) = mpsc::unbounded_channel();
        let load = Arc::new(Load::default());
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
            Event::Response(request, Ok(accepted)) => {
                state.on_request_succeeded(now, &self.workers.candidates(), request, accepted)
            }
            Event::Response(request, Err(failure)) => {
                // Backpressure is transient, not a worker fault.
                let cause = if failure.error.is_backpressure() {
                    FailureCause::Busy
                } else {
                    FailureCause::Fault
                };
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
        let mut messages = Vec::new();
        for run in send.runs {
            sentinel.note_sent(&run.routing_key, &run.messages, kind);
            messages.extend(run.messages);
        }
        let response = self.sender.send(&send.worker, messages, send.class.replay);
        let request = send.request;
        self.responses
            .push(async move { (request, response.await) }.boxed());
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
    use std::time::Duration;

    use tokio::sync::oneshot;

    use super::*;
    use crate::batcher::packer::{PackTargets, Packer};
    use crate::batcher::retry_policy::RetryPolicy;
    use crate::batcher::test_support::{message, offsets};
    use crate::batcher::worker_assigner::WorkerAssigner;
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
        fence_released: Option<bool>,
        reply: oneshot::Sender<Result<u32, SendError>>,
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
            replay: bool,
        ) -> BoxFuture<'static, Result<u32, SendError>> {
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
                replay,
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
            let assigner = WorkerAssigner::new(
                Router::new(RoutingStrategy::BinPack),
                max_requests_per_worker,
            )
            .expect("valid request cap");
            let retry = RetryPolicy::new(FAULT_DELAY, BUSY_DELAY, NO_WORKER_DELAY)
                .expect("valid retry policy");
            let packer = Packer::new(PackTargets {
                events: 1,
                bytes: 0,
                latency_budget: Duration::ZERO,
            });
            let state = BatcherStateMachine::new(
                packer,
                assigner,
                retry,
                STALL,
                tokio::time::Instant::now().into_std(),
            )
            .expect("valid stall timeout");
            let fake_workers = FakeWorkers::default();
            fake_workers.set_candidates(workers);
            let sender = Arc::new(FakeSender {
                assignment_epoch: AssignmentEpoch::new(),
                sent: Mutex::new(Vec::new()),
                fence: Mutex::new(None),
            });
            let (driver, outputs) =
                StateMachineDriver::new(state, fake_workers.clone(), Arc::clone(&sender));
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
        h.submit(vec![run("a", &[1, 2])]);
        settle().await;

        let sent = h.take_sent();
        assert_eq!(sent.len(), 1);
        assert_eq!(sent[0].worker, WorkerId::from("w"));
        assert_eq!(sent[0].offsets, vec![1, 2]);
        assert!(!sent[0].replay);

        let send = sent.into_iter().next().unwrap();
        send.reply.send(Ok(2)).unwrap();
        settle().await;
        assert_eq!(h.completed_offsets(), vec![1, 2]);
        assert_eq!(h.workers.outcomes(), vec![(WorkerId::from("w"), false)]);
        assert_eq!(h.workers.idle(), vec![WorkerId::from("w")]);
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

        send.reply.send(Ok(1)).unwrap();
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
        h.submit(vec![run("a", &[1]), run("b", &[2, 3])]);
        settle().await;
        assert_eq!(load.pending_messages.load(Ordering::Relaxed), 3);
        assert!(load.busy_workers.lock().unwrap().is_empty());

        h.workers.set_candidates(&["w"]);
        tokio::time::advance(NO_WORKER_DELAY).await;
        settle().await;
        assert_eq!(load.pending_messages.load(Ordering::Relaxed), 0);
        assert_eq!(load.in_flight_messages.load(Ordering::Relaxed), 3);
        assert_eq!(
            *load.busy_workers.lock().unwrap(),
            HashSet::from([WorkerId::from("w")])
        );

        let mut sent = h.take_sent();
        let accepted = |send: &Sent| send.offsets.len() as u32;
        let first = sent.remove(0);
        let count = accepted(&first);
        first.reply.send(Ok(count)).unwrap();
        settle().await;
        assert!(!load.busy_workers.lock().unwrap().is_empty());

        let last = sent.remove(0);
        let count = accepted(&last);
        last.reply.send(Ok(count)).unwrap();
        settle().await;
        assert!(load.busy_workers.lock().unwrap().is_empty());
        assert_eq!(load.in_flight_messages.load(Ordering::Relaxed), 0);
    }

    #[tokio::test(start_paused = true)]
    async fn a_state_machine_failure_reaches_the_error_channel() {
        let mut h = Harness::new(&["w"], 4);
        h.submit(vec![run("a", &[1, 2])]);
        settle().await;
        let send = h.take_sent().pop().unwrap();
        send.reply.send(Ok(1)).unwrap();
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
}
