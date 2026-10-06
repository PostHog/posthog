//! Decides which key runs go to which worker, and when. The batcher task
//! feeds it polls, worker responses, retry wakeups, revokes and shutdown,
//! and performs the [`Effects`] each action returns. The state machine does
//! no I/O.
//!
//! The caller performs one action's effects in this order: order-sentinel
//! ACKs before evictions, then the sends in the order given, which is each
//! key's send order. `next_wakeup` replaces the previous wakeup; `None` needs
//! no timer. `fatal` means the state machine failed and the process must
//! exit and replay.
//!
//! When work is pending, nothing is in flight, and no message was accepted
//! for `stall_timeout`, the state machine fails, so a wedged batcher restarts
//! instead of growing lag.

use std::cmp::Reverse;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{GroupCompletion, Offset, Partition};
use metrics::{gauge, histogram};

use super::in_flight::{InFlightRequest, InFlightRequests, RequestId, SentRun};
use super::key_queues::{KeyQueues, KeyRun};
use super::packer::Packer;
use super::request::{Request, RequestClass};
use super::retry_policy::{RetryPolicy, RetryReason};
use super::worker_assigner::WorkerAssigner;
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FailureCause {
    Fault,
    Busy,
}

#[derive(Debug)]
pub struct SendRequest {
    pub request: RequestId,
    pub worker: WorkerId,
    pub class: RequestClass,
    pub runs: Vec<KeyRun>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct KeyAck {
    pub routing_key: Arc<str>,
    pub max_offset: i64,
}

#[derive(Debug, PartialEq, Eq)]
pub struct WorkerOutcome {
    pub worker: WorkerId,
    pub fault: bool,
}

#[derive(Debug, Default)]
pub struct Effects {
    pub sends: Vec<SendRequest>,
    pub completions: Vec<GroupCompletion>,
    pub key_acks: Vec<KeyAck>,
    pub evicted_keys: Vec<Arc<str>>,
    pub worker_outcomes: Vec<WorkerOutcome>,
    /// A draining worker listed here has finished its work.
    pub idle_workers: Vec<WorkerId>,
    pub busy_workers: Vec<WorkerId>,
    pub fatal: Option<String>,
    pub next_wakeup: Option<Instant>,
}

pub enum BatcherStateMachine {
    Running(ActiveState),
    Draining(ActiveState),
    Stopped,
    Failed,
}

impl BatcherStateMachine {
    pub fn new(
        packer: Packer,
        assigner: WorkerAssigner,
        retry: RetryPolicy,
        stall_timeout: Duration,
        now: Instant,
    ) -> Result<Self, String> {
        if stall_timeout.is_zero() {
            return Err("stall_timeout must be > 0".to_string());
        }
        // A key's next messages queue behind its held run and count toward
        // a stall, so the hold must leave most of the stall window.
        if packer.latency_budget() * 2 > stall_timeout {
            return Err(
                "the pack latency budget must be at most half the stall timeout".to_string(),
            );
        }
        Ok(BatcherStateMachine::Running(ActiveState {
            keys: KeyQueues::new(),
            packer,
            assigner,
            in_flight: InFlightRequests::new(),
            retry,
            stall_timeout,
            last_progress: now,
        }))
    }

    pub fn on_groups(
        self,
        now: Instant,
        workers: &[WorkerId],
        assignment_epoch: u64,
        runs: Vec<KeyRun>,
    ) -> (Self, Effects) {
        match self {
            BatcherStateMachine::Running(mut active) => {
                let result = active.on_groups(now, workers, assignment_epoch, runs);
                Self::after(active, false, result)
            }
            BatcherStateMachine::Draining(_) | BatcherStateMachine::Stopped => {
                Self::failed("groups submitted after shutdown started".to_string())
            }
            BatcherStateMachine::Failed => (BatcherStateMachine::Failed, Effects::default()),
        }
    }

    pub fn on_request_succeeded(
        self,
        now: Instant,
        workers: &[WorkerId],
        request: RequestId,
        accepted: u32,
    ) -> (Self, Effects) {
        self.act(|active, draining| {
            active.on_request_succeeded(now, workers, draining, request, accepted)
        })
    }

    /// A worker accepts a whole request or none of it. The failed request's
    /// messages go back to the front of their keys' queues and are sent again
    /// as replay after the retry delay.
    pub fn on_request_failed(
        self,
        now: Instant,
        workers: &[WorkerId],
        request: RequestId,
        cause: FailureCause,
        messages: Vec<SerializedKafkaMessage>,
    ) -> (Self, Effects) {
        self.act(|active, draining| {
            active.on_request_failed(now, workers, draining, request, cause, messages)
        })
    }

    pub fn on_wakeup(self, now: Instant, workers: &[WorkerId]) -> (Self, Effects) {
        self.act(|active, draining| {
            let mut effects = Effects::default();
            active.advance(now, workers, draining, &mut effects)?;
            Ok(effects)
        })
    }

    /// The new owner replays the revoked partitions, so their pending
    /// messages drop. Runs already in flight finish; if they fail, their
    /// messages of revoked partitions drop too.
    pub fn on_partitions_revoked(
        self,
        now: Instant,
        partitions: &[(String, i32)],
    ) -> (Self, Effects) {
        self.act(|active, _| active.on_partitions_revoked(now, partitions))
    }

    /// Takes no new groups from now on, seals held batches at once, and stops
    /// once nothing is pending or in flight.
    pub fn on_shutdown(self, now: Instant, workers: &[WorkerId]) -> (Self, Effects) {
        match self {
            BatcherStateMachine::Running(active) | BatcherStateMachine::Draining(active) => {
                BatcherStateMachine::Draining(active).on_wakeup(now, workers)
            }
            other => (other, Effects::default()),
        }
    }

    pub fn pending_messages(&self) -> usize {
        self.active().map_or(0, ActiveState::pending_messages)
    }

    pub fn in_flight_messages(&self) -> usize {
        self.active()
            .map_or(0, |active| active.assigner.in_flight_messages())
    }

    fn active(&self) -> Option<&ActiveState> {
        match self {
            BatcherStateMachine::Running(active) | BatcherStateMachine::Draining(active) => {
                Some(active)
            }
            BatcherStateMachine::Stopped | BatcherStateMachine::Failed => None,
        }
    }

    fn act(
        self,
        action: impl FnOnce(&mut ActiveState, bool) -> Result<Effects, String>,
    ) -> (Self, Effects) {
        match self {
            BatcherStateMachine::Running(mut active) => {
                let result = action(&mut active, false);
                Self::after(active, false, result)
            }
            BatcherStateMachine::Draining(mut active) => {
                let result = action(&mut active, true);
                Self::after(active, true, result)
            }
            finished => (finished, Effects::default()),
        }
    }

    fn after(
        active: ActiveState,
        draining: bool,
        result: Result<Effects, String>,
    ) -> (Self, Effects) {
        match result {
            Err(reason) => Self::failed(reason),
            Ok(effects) if draining && active.is_drained() => (
                BatcherStateMachine::Stopped,
                Effects {
                    next_wakeup: None,
                    ..effects
                },
            ),
            Ok(effects) if draining => (BatcherStateMachine::Draining(active), effects),
            Ok(effects) => (BatcherStateMachine::Running(active), effects),
        }
    }

    fn failed(reason: String) -> (Self, Effects) {
        (
            BatcherStateMachine::Failed,
            Effects {
                fatal: Some(reason),
                ..Effects::default()
            },
        )
    }
}

pub struct ActiveState {
    keys: KeyQueues,
    packer: Packer,
    assigner: WorkerAssigner,
    in_flight: InFlightRequests,
    retry: RetryPolicy,
    stall_timeout: Duration,
    last_progress: Instant,
}

impl ActiveState {
    fn pending_messages(&self) -> usize {
        self.keys.queued_messages() + self.packer.held_messages()
    }

    /// An open batch waits for its deadline by design, so its messages never
    /// count toward a stall.
    fn stuck_messages(&self) -> usize {
        self.pending_messages() - self.packer.open_messages()
    }

    /// The stall clock starts when work becomes pending, not at the last
    /// action before a quiet period.
    fn restart_stall_clock_if_quiet(&mut self, now: Instant) {
        if self.stuck_messages() == 0 && self.in_flight.is_empty() {
            self.last_progress = now;
        }
    }

    fn is_drained(&self) -> bool {
        self.pending_messages() == 0 && self.in_flight.is_empty()
    }

    fn on_groups(
        &mut self,
        now: Instant,
        workers: &[WorkerId],
        assignment_epoch: u64,
        runs: Vec<KeyRun>,
    ) -> Result<Effects, String> {
        self.restart_stall_clock_if_quiet(now);
        for run in runs {
            self.keys
                .push(run.routing_key, assignment_epoch, run.messages, now);
        }
        let mut effects = Effects::default();
        self.advance(now, workers, false, &mut effects)?;
        Ok(effects)
    }

    fn on_request_succeeded(
        &mut self,
        now: Instant,
        workers: &[WorkerId],
        draining: bool,
        request: RequestId,
        accepted: u32,
    ) -> Result<Effects, String> {
        let mut effects = Effects::default();
        let sent = self.take_request(request, &mut effects)?;
        if accepted as usize != sent.message_count {
            return Err(format!(
                "worker accepted {accepted} of {} messages",
                sent.message_count
            ));
        }
        effects.worker_outcomes.push(WorkerOutcome {
            worker: sent.worker.clone(),
            fault: false,
        });
        if accepted > 0 {
            self.last_progress = now;
        }
        let assignment_epoch = sent.class.assignment_epoch;
        let runs = sent.accepted();
        effects.completions = completions(assignment_epoch, &runs);
        effects.key_acks = key_acks(&runs);
        for run in runs {
            self.settle_key(&run.routing_key, Vec::new(), None, now, &mut effects)?;
        }
        self.advance(now, workers, draining, &mut effects)?;
        Ok(effects)
    }

    fn on_request_failed(
        &mut self,
        now: Instant,
        workers: &[WorkerId],
        draining: bool,
        request: RequestId,
        cause: FailureCause,
        messages: Vec<SerializedKafkaMessage>,
    ) -> Result<Effects, String> {
        let mut effects = Effects::default();
        let sent = self.take_request(request, &mut effects)?;
        effects.worker_outcomes.push(WorkerOutcome {
            worker: sent.worker.clone(),
            fault: cause == FailureCause::Fault,
        });
        let runs = sent.hand_back(messages)?;
        let retry_at = self.retry.retry_at(
            now,
            match cause {
                FailureCause::Fault => RetryReason::Fault,
                FailureCause::Busy => RetryReason::Busy,
            },
        );
        for run in runs {
            self.settle_key(
                &run.routing_key,
                run.messages,
                Some(retry_at),
                now,
                &mut effects,
            )?;
        }
        self.advance(now, workers, draining, &mut effects)?;
        Ok(effects)
    }

    fn on_partitions_revoked(
        &mut self,
        now: Instant,
        partitions: &[(String, i32)],
    ) -> Result<Effects, String> {
        let mut effects = Effects {
            evicted_keys: self.keys.purge(partitions),
            ..Effects::default()
        };

        for key in self.packer.purge(partitions) {
            self.settle_key(&key, Vec::new(), None, now, &mut effects)?;
        }

        self.finish(now, &mut effects)?;
        if self.keys.has_ready() {
            effects.next_wakeup = Some(now);
        }
        Ok(effects)
    }

    fn take_request(
        &mut self,
        request: RequestId,
        effects: &mut Effects,
    ) -> Result<InFlightRequest, String> {
        let sent = self
            .in_flight
            .take(request)
            .ok_or_else(|| format!("response for unknown request {request:?}"))?;
        if self.assigner.release(&sent.worker, sent.message_count) {
            effects.idle_workers.push(sent.worker.clone());
        }
        Ok(sent)
    }

    fn settle_key(
        &mut self,
        routing_key: &Arc<str>,
        requeued: Vec<SerializedKafkaMessage>,
        retry_at: Option<Instant>,
        now: Instant,
        effects: &mut Effects,
    ) -> Result<(), String> {
        let evicted = self
            .keys
            .settle(routing_key, requeued, retry_at, now)
            .map_err(|err| err.to_string())?;
        if evicted {
            effects.evicted_keys.push(Arc::clone(routing_key));
        }
        Ok(())
    }

    fn advance(
        &mut self,
        now: Instant,
        workers: &[WorkerId],
        draining: bool,
        effects: &mut Effects,
    ) -> Result<(), String> {
        self.restart_stall_clock_if_quiet(now);
        for ready in self.keys.take_ready(now, usize::MAX) {
            self.packer.push(ready, now);
        }
        if draining {
            self.packer.flush();
        } else {
            self.packer.seal_expired(now);
        }
        // Past the stall deadline no new request starts, so overlapping
        // failures drain to nothing in flight and the watchdog can fire.
        let stalled = self.stuck_messages() > 0 && now >= self.last_progress + self.stall_timeout;
        if !stalled {
            self.place(now, workers, effects)?;
        }
        self.finish(now, effects)
    }

    fn place(
        &mut self,
        now: Instant,
        workers: &[WorkerId],
        effects: &mut Effects,
    ) -> Result<(), String> {
        let free_slots = self.assigner.free_slots(workers);
        let mut batch = self.packer.take_ready(now, free_slots);
        if self.assigner.prefers_largest_first() {
            // Bin-packing places the heavy requests first, so they drive
            // the load distribution.
            batch.sort_by_key(|request| Reverse(request.message_count));
        }
        for request in batch {
            let worker = self
                .assigner
                .assign(workers, request.message_count)
                .ok_or("no worker took a request within the free slots")?;
            if self.assigner.requests_on(&worker) == 1 {
                effects.busy_workers.push(worker.clone());
            }
            self.send(now, worker, request, effects);
        }
        Ok(())
    }

    fn send(&mut self, now: Instant, worker: WorkerId, request: Request, effects: &mut Effects) {
        let kind = if request.class.replay {
            "replay"
        } else {
            "fresh"
        };
        histogram!("ingestion_consumer_request_events").record(request.message_count as f64);
        histogram!("ingestion_consumer_request_bytes").record(request.bytes as f64);
        histogram!("ingestion_consumer_request_queue_wait_seconds", "kind" => kind).record(
            now.saturating_duration_since(request.oldest_arrival)
                .as_secs_f64(),
        );
        let id = self
            .in_flight
            .register(worker.clone(), request.class, &request.runs);
        effects.sends.push(SendRequest {
            request: id,
            worker,
            class: request.class,
            runs: request.runs,
        });
    }

    fn finish(&mut self, now: Instant, effects: &mut Effects) -> Result<(), String> {
        // A stalled action and a revoke skip `take_ready`, so without this a due
        // retry would set the next wakeup at or before `now`.
        self.keys.promote_due(now);
        let stuck = self.stuck_messages();
        let in_flight = self.in_flight.len();
        if stuck == 0 && in_flight == 0 {
            self.last_progress = now;
        }
        self.record_gauges();
        let stall_deadline = self.last_progress + self.stall_timeout;
        if stuck > 0 && in_flight == 0 && now >= stall_deadline {
            return Err("pending work made no progress within the stall timeout".to_string());
        }
        effects.next_wakeup = [
            self.keys.next_retry_at(),
            self.packer.next_deadline(),
            (self.packer.sealed_requests() > 0)
                .then(|| self.retry.retry_at(now, RetryReason::NoWorker)),
            (stuck > 0 && in_flight == 0).then_some(stall_deadline),
        ]
        .into_iter()
        .flatten()
        .min();
        Ok(())
    }

    fn record_gauges(&self) {
        gauge!("ingestion_consumer_batcher_keys").set(self.keys.key_count() as f64);
        gauge!("ingestion_consumer_batcher_queued_messages")
            .set(self.keys.queued_messages() as f64);
        gauge!("ingestion_consumer_batcher_queued_bytes").set(self.keys.queued_bytes() as f64);
        gauge!("ingestion_consumer_batcher_claimed_keys").set(self.keys.claimed_keys() as f64);
        gauge!("ingestion_consumer_batcher_waiting_keys").set(self.keys.waiting_keys() as f64);
        gauge!("ingestion_consumer_batcher_packer_held_messages")
            .set(self.packer.held_messages() as f64);
        gauge!("ingestion_consumer_batcher_packer_held_keys").set(self.packer.held_keys() as f64);
        gauge!("ingestion_consumer_batcher_in_flight_requests").set(self.in_flight.len() as f64);
    }
}

fn completions(assignment_epoch: u64, runs: &[SentRun]) -> Vec<GroupCompletion> {
    let mut by_partition: HashMap<i32, Vec<Offset>> = HashMap::new();
    for run in runs {
        for message in &run.messages {
            by_partition
                .entry(message.partition)
                .or_default()
                .push(Offset(message.offset));
        }
    }
    let mut completions: Vec<GroupCompletion> = by_partition
        .into_iter()
        .map(|(partition, offsets)| GroupCompletion {
            partition: Partition(partition),
            assignment_epoch,
            accepted: offsets.len() as u32,
            offsets,
        })
        .collect();
    completions.sort_by_key(|completion| completion.partition.0);
    completions
}

fn key_acks(runs: &[SentRun]) -> Vec<KeyAck> {
    runs.iter()
        .filter_map(|run| {
            let max_offset = run
                .messages
                .iter()
                // An unkeyed message lives on an arbitrary partition under a
                // synthetic key, so it does not advance an ACK high-water mark.
                .filter(|message| message.keyed)
                .map(|message| message.offset)
                .max()?;
            Some(KeyAck {
                routing_key: Arc::clone(&run.routing_key),
                max_offset,
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use std::collections::VecDeque;

    use super::*;
    use crate::batcher::packer::PackTargets;
    use crate::batcher::test_support::{message, offsets};
    use crate::routing::{Router, RoutingStrategy};

    const FAULT_DELAY: Duration = Duration::from_millis(200);
    const BUSY_DELAY: Duration = Duration::from_millis(20);
    const NO_WORKER_DELAY: Duration = Duration::from_millis(100);
    const STALL: Duration = Duration::from_secs(60);

    /// Distinct delays, so a wakeup time shows which retry reason applied.
    fn retry_policy() -> RetryPolicy {
        RetryPolicy::new(FAULT_DELAY, BUSY_DELAY, NO_WORKER_DELAY).expect("valid retry policy")
    }

    /// Seals each key run as its own request.
    fn batcher(max_requests_per_worker: usize, now: Instant) -> BatcherStateMachine {
        packing_batcher(1, Duration::ZERO, max_requests_per_worker, now)
    }

    fn packing_batcher(
        events: usize,
        budget: Duration,
        max_requests_per_worker: usize,
        now: Instant,
    ) -> BatcherStateMachine {
        let packer = Packer::new(PackTargets {
            events,
            bytes: 0,
            latency_budget: budget,
        });
        let assigner = WorkerAssigner::new(
            Router::new(RoutingStrategy::BinPack),
            max_requests_per_worker,
        )
        .expect("valid request cap");
        BatcherStateMachine::new(packer, assigner, retry_policy(), STALL, now)
            .expect("valid stall timeout")
    }

    fn pool(workers: &[&str]) -> Vec<WorkerId> {
        workers.iter().map(|w| WorkerId::from(*w)).collect()
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

    fn shape(send: &SendRequest) -> Vec<(&str, Vec<i64>)> {
        send.runs
            .iter()
            .map(|run| (&*run.routing_key, offsets(&run.messages)))
            .collect()
    }

    fn sent_messages(send: &SendRequest) -> Vec<SerializedKafkaMessage> {
        send.runs
            .iter()
            .flat_map(|run| run.messages.iter().cloned())
            .collect()
    }

    #[test]
    fn each_key_run_is_its_own_request_and_its_next_run_waits_for_the_response() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(4, now);

        let (batcher, effects) =
            batcher.on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        assert_eq!(
            effects.sends.iter().map(shape).collect::<Vec<_>>(),
            vec![vec![("a", vec![1])], vec![("b", vec![2])]]
        );
        let request = effects.sends[0].request;

        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[3])]);
        assert!(effects.sends.is_empty(), "a's first run is still in flight");

        let (_, effects) = batcher.on_request_succeeded(now, &workers, request, 1);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![3])]);
        assert_eq!(effects.completions.len(), 1);
        assert_eq!(effects.completions[0].offsets, vec![Offset(1)]);
        assert_eq!(
            effects.key_acks,
            vec![KeyAck {
                routing_key: "a".into(),
                max_offset: 1
            }]
        );
    }

    #[test]
    fn a_key_arriving_under_a_new_epoch_stays_one_run_out() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(4, now);

        let (batcher, effects) = batcher.on_groups(now, &workers, 1, vec![run("k", &[1])]);
        assert_eq!(effects.sends[0].class.assignment_epoch, 1);
        let request = effects.sends[0].request;
        let (batcher, effects) = batcher.on_groups(now, &workers, 2, vec![run("k", &[2])]);
        assert!(
            effects.sends.is_empty(),
            "the epoch-2 message waits for k's run"
        );

        let (_, effects) = batcher.on_request_succeeded(now, &workers, request, 1);
        assert_eq!(effects.sends[0].class.assignment_epoch, 2);
        assert_eq!(shape(&effects.sends[0]), vec![("k", vec![2])]);
    }

    #[test]
    fn a_transport_failure_retries_as_replay_after_the_fault_delay() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(4, now);
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1])]);
        let request = effects.sends[0].request;

        let messages = vec![message("a", 0, 1)];
        let (batcher, effects) =
            batcher.on_request_failed(now, &workers, request, FailureCause::Fault, messages);
        assert_eq!(
            effects.worker_outcomes,
            vec![WorkerOutcome {
                worker: WorkerId::from("w"),
                fault: true
            }]
        );
        assert!(effects.completions.is_empty());
        assert!(effects.sends.is_empty());
        assert_eq!(effects.next_wakeup, Some(now + FAULT_DELAY));

        let (_, effects) = batcher.on_wakeup(now + FAULT_DELAY, &workers);
        assert!(effects.sends[0].class.replay);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![1])]);
    }

    #[test]
    fn a_revoke_after_a_retry_time_passed_asks_for_a_wakeup_now() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(4, now);
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1])]);
        let request = effects.sends[0].request;
        let (batcher, _) = batcher.on_request_failed(
            now,
            &workers,
            request,
            FailureCause::Busy,
            vec![message("a", 0, 1)],
        );

        let late = now + BUSY_DELAY * 3;
        let (_, effects) = batcher.on_partitions_revoked(late, &[("events".to_string(), 9)]);
        assert_eq!(effects.next_wakeup, Some(late));
    }

    #[test]
    fn bin_packing_places_the_largest_request_first() {
        let now = Instant::now();
        let workers = pool(&["w1", "w2"]);
        let batcher = batcher(4, now);

        let (_, effects) = batcher.on_groups(
            now,
            &workers,
            0,
            vec![run("small", &[1]), run("large", &[2, 3, 4])],
        );
        let placed: Vec<_> = effects
            .sends
            .iter()
            .map(|send| (&*send.runs[0].routing_key, send.worker.as_ref()))
            .collect();
        assert_eq!(placed, vec![("large", "w1"), ("small", "w2")]);
    }

    #[test]
    fn a_request_without_a_worker_waits_and_is_sent_when_one_appears() {
        let now = Instant::now();
        let batcher = batcher(4, now);

        let (batcher, effects) = batcher.on_groups(now, &pool(&[]), 0, vec![run("a", &[1])]);
        assert!(effects.sends.is_empty());
        assert_eq!(batcher.pending_messages(), 1);
        assert_eq!(effects.next_wakeup, Some(now + NO_WORKER_DELAY));

        let (_, effects) = batcher.on_wakeup(now + NO_WORKER_DELAY, &pool(&["w"]));
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![1])]);
    }

    #[test]
    fn the_request_cap_holds_sends_until_a_slot_frees() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(1, now);

        let (batcher, effects) =
            batcher.on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        assert_eq!(effects.sends.len(), 1);
        let request = effects.sends[0].request;

        let (_, effects) = batcher.on_request_succeeded(now, &workers, request, 1);
        assert_eq!(shape(&effects.sends[0]), vec![("b", vec![2])]);
        // The freed slot is refilled in the same action, so the worker is
        // reported idle and then busy again.
        assert_eq!(effects.idle_workers, vec![WorkerId::from("w")]);
        assert_eq!(effects.busy_workers, vec![WorkerId::from("w")]);
    }

    #[test]
    fn a_worker_is_busy_from_its_first_request_until_its_last_settles() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(2, now);

        let (batcher, effects) =
            batcher.on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        assert_eq!(effects.sends.len(), 2);
        assert_eq!(effects.busy_workers, vec![WorkerId::from("w")]);
        let (first, second) = (effects.sends[0].request, effects.sends[1].request);

        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, first, 1);
        assert!(effects.idle_workers.is_empty());

        let (_, effects) = batcher.on_request_succeeded(now, &workers, second, 1);
        assert_eq!(effects.idle_workers, vec![WorkerId::from("w")]);
    }

    #[test]
    fn a_revoke_drops_pending_messages_and_never_sends_them() {
        let now = Instant::now();
        let batcher = batcher(4, now);
        let (batcher, effects) = batcher.on_groups(now, &pool(&[]), 0, vec![run("a", &[1])]);
        assert!(effects.sends.is_empty());

        let (batcher, effects) = batcher.on_partitions_revoked(now, &[("events".to_string(), 0)]);
        assert!(effects.sends.is_empty());
        assert_eq!(effects.evicted_keys, vec![Arc::<str>::from("a")]);
        assert_eq!(batcher.pending_messages(), 0);

        let (_, effects) = batcher.on_wakeup(now + STALL / 2, &pool(&["w"]));
        assert!(effects.sends.is_empty());
    }

    #[test]
    fn shutdown_stops_once_drained() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(4, now);
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1])]);
        let request = effects.sends[0].request;

        let (batcher, _) = batcher.on_shutdown(now, &workers);
        assert!(matches!(batcher, BatcherStateMachine::Draining(_)));

        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, request, 1);
        assert!(matches!(batcher, BatcherStateMachine::Stopped));
        assert_eq!(effects.next_wakeup, None);
    }

    #[test]
    fn a_pack_budget_over_half_the_stall_timeout_is_rejected() {
        let assigner =
            WorkerAssigner::new(Router::new(RoutingStrategy::BinPack), 1).expect("valid cap");
        let packer = Packer::new(PackTargets {
            latency_budget: STALL / 2 + Duration::from_millis(1),
            ..PackTargets::default()
        });
        let created =
            BatcherStateMachine::new(packer, assigner, retry_policy(), STALL, Instant::now());
        assert!(created.is_err());
    }

    #[test]
    fn a_second_shutdown_keeps_a_waiting_retrys_wakeup() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(4, now);
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1])]);
        let request = effects.sends[0].request;
        let (batcher, _) = batcher.on_request_failed(
            now,
            &workers,
            request,
            FailureCause::Busy,
            vec![message("a", 0, 1)],
        );
        let (batcher, _) = batcher.on_shutdown(now, &workers);

        let (batcher, effects) = batcher.on_shutdown(now, &workers);
        assert!(matches!(batcher, BatcherStateMachine::Draining(_)));
        assert_eq!(effects.next_wakeup, Some(now + BUSY_DELAY));
    }

    #[test]
    fn a_zero_stall_timeout_is_rejected() {
        let assigner =
            WorkerAssigner::new(Router::new(RoutingStrategy::BinPack), 1).expect("valid cap");
        let created = BatcherStateMachine::new(
            Packer::new(PackTargets::default()),
            assigner,
            retry_policy(),
            Duration::ZERO,
            Instant::now(),
        );
        assert!(created.is_err());
    }

    #[test]
    fn work_stuck_without_progress_fails_the_state_machine() {
        let now = Instant::now();
        let batcher = batcher(4, now);
        let (batcher, _) = batcher.on_groups(now, &pool(&[]), 0, vec![run("a", &[1])]);

        let (batcher, effects) = batcher.on_wakeup(now + STALL, &pool(&[]));
        assert!(matches!(batcher, BatcherStateMachine::Failed));
        assert!(effects.fatal.is_some());
        assert_eq!(effects.next_wakeup, None);
    }

    #[test]
    fn a_passed_stall_deadline_with_a_request_in_flight_never_asks_for_a_past_wakeup() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(1, now);
        let (batcher, _) =
            batcher.on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);

        let late = now + STALL * 2;
        let (batcher, effects) = batcher.on_wakeup(late, &workers);
        assert!(matches!(batcher, BatcherStateMachine::Running(_)));
        assert!(effects.next_wakeup.is_some_and(|at| at > late));
    }

    #[test]
    fn a_retry_due_past_the_stall_deadline_waits_the_no_worker_delay() {
        let now = Instant::now();
        let workers = pool(&["w1", "w2"]);
        let (batcher, effects) =
            batcher(1, now).on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        let a = effects
            .sends
            .iter()
            .find(|send| &*send.runs[0].routing_key == "a")
            .expect("a was sent")
            .request;
        let (batcher, _) = batcher.on_request_failed(
            now + STALL - BUSY_DELAY / 2,
            &workers,
            a,
            FailureCause::Busy,
            vec![message("a", 0, 1)],
        );

        let late = now + STALL + BUSY_DELAY;
        let (batcher, effects) = batcher.on_wakeup(late, &workers);
        assert!(matches!(batcher, BatcherStateMachine::Running(_)));
        assert_eq!(effects.next_wakeup, Some(late + NO_WORKER_DELAY));
    }

    #[test]
    fn past_the_stall_deadline_no_new_request_starts_until_the_in_flight_one_settles() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(1, now);
        let (batcher, effects) =
            batcher.on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        let request = effects.sends[0].request;

        let late = now + STALL;
        let (batcher, effects) = batcher.on_request_failed(
            late,
            &workers,
            request,
            FailureCause::Busy,
            vec![message("a", 0, 1)],
        );
        assert!(effects.sends.is_empty(), "b stays unsent past the deadline");
        assert!(matches!(batcher, BatcherStateMachine::Failed));
    }

    #[test]
    fn an_idle_period_does_not_count_toward_a_stall() {
        let start = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(4, start);

        let arrival = start + STALL * 3;
        let (batcher, effects) = batcher.on_groups(arrival, &workers, 0, vec![run("a", &[1])]);
        assert!(matches!(batcher, BatcherStateMachine::Running(_)));
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![1])]);
    }

    #[test]
    fn keys_pack_into_one_request_and_their_next_runs_wait_for_the_response() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = packing_batcher(100, Duration::ZERO, 4, now);

        let (batcher, effects) =
            batcher.on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        assert_eq!(effects.sends.len(), 1);
        assert_eq!(
            shape(&effects.sends[0]),
            vec![("a", vec![1]), ("b", vec![2])]
        );
        let request = effects.sends[0].request;

        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[3])]);
        assert!(effects.sends.is_empty(), "a's first run is still in flight");

        let (_, effects) = batcher.on_request_succeeded(now, &workers, request, 2);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![3])]);
        assert_eq!(effects.completions.len(), 1);
        assert_eq!(effects.completions[0].offsets, vec![Offset(1), Offset(2)]);
        assert_eq!(effects.evicted_keys, vec![Arc::<str>::from("b")]);
        assert_eq!(
            effects.key_acks,
            vec![
                KeyAck {
                    routing_key: "a".into(),
                    max_offset: 1
                },
                KeyAck {
                    routing_key: "b".into(),
                    max_offset: 2
                },
            ]
        );
    }

    #[test]
    fn a_key_arriving_under_a_new_epoch_while_held_stays_one_run_out() {
        let now = Instant::now();
        let budget = Duration::from_millis(30);
        let workers = pool(&["w"]);
        let batcher = packing_batcher(100, budget, 4, now);

        let (batcher, _) = batcher.on_groups(now, &workers, 1, vec![run("k", &[1])]);
        let (batcher, effects) = batcher.on_groups(now, &workers, 2, vec![run("k", &[2])]);
        assert!(effects.sends.is_empty());

        let (batcher, effects) = batcher.on_wakeup(now + budget, &workers);
        assert_eq!(
            effects.sends.len(),
            1,
            "the epoch-2 message waits for k's run"
        );
        assert_eq!(effects.sends[0].class.assignment_epoch, 1);
        assert_eq!(shape(&effects.sends[0]), vec![("k", vec![1])]);

        let request = effects.sends[0].request;
        let later = now + budget * 2;
        let (batcher, _) = batcher.on_request_succeeded(later, &workers, request, 1);
        let (_, effects) = batcher.on_wakeup(later + budget, &workers);
        assert_eq!(effects.sends[0].class.assignment_epoch, 2);
        assert_eq!(shape(&effects.sends[0]), vec![("k", vec![2])]);
    }

    #[test]
    fn a_transport_failure_retries_on_its_own_delay_whatever_the_pack_budget() {
        let now = Instant::now();
        let budget = Duration::from_millis(10);
        let workers = pool(&["w"]);
        let batcher = packing_batcher(2, budget, 4, now);
        let (batcher, effects) =
            batcher.on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        let request = effects.sends[0].request;

        let messages = vec![message("a", 0, 1), message("b", 0, 2)];
        let (batcher, effects) =
            batcher.on_request_failed(now, &workers, request, FailureCause::Fault, messages);
        assert_eq!(
            effects.worker_outcomes,
            vec![WorkerOutcome {
                worker: WorkerId::from("w"),
                fault: true
            }]
        );
        assert!(effects.completions.is_empty());
        assert_eq!(effects.next_wakeup, Some(now + FAULT_DELAY));

        let (batcher, effects) = batcher.on_wakeup(now + budget, &workers);
        assert!(
            effects.sends.is_empty(),
            "the pack budget does not pace retries"
        );

        let (_, effects) = batcher.on_wakeup(now + FAULT_DELAY, &workers);
        assert_eq!(effects.sends.len(), 1, "the retries pack into one request");
        assert!(effects.sends[0].class.replay);
    }

    #[test]
    fn a_held_batch_leaves_at_its_deadline() {
        let now = Instant::now();
        let budget = Duration::from_millis(30);
        let workers = pool(&["w"]);
        let batcher = packing_batcher(100, budget, 4, now);

        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1])]);
        assert!(effects.sends.is_empty());
        assert_eq!(effects.next_wakeup, Some(now + budget));

        let (_, effects) = batcher.on_wakeup(now + budget, &workers);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![1])]);
    }

    #[test]
    fn shutdown_seals_held_batches_and_stops_once_drained() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = packing_batcher(100, Duration::from_secs(10), 4, now);
        let (batcher, _) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1])]);

        let (batcher, effects) = batcher.on_shutdown(now, &workers);
        assert!(matches!(batcher, BatcherStateMachine::Draining(_)));
        let request = effects.sends[0].request;

        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, request, 1);
        assert!(matches!(batcher, BatcherStateMachine::Stopped));
        assert_eq!(effects.next_wakeup, None);
    }

    #[test]
    fn neither_an_idle_period_nor_a_held_batch_counts_toward_a_stall() {
        let start = Instant::now();
        let budget = STALL / 2;
        let workers = pool(&["w"]);
        let batcher = packing_batcher(100, budget, 4, start);

        let arrival = start + STALL * 3;
        let (batcher, effects) = batcher.on_groups(arrival, &workers, 0, vec![run("a", &[1])]);
        assert!(matches!(batcher, BatcherStateMachine::Running(_)));
        assert_eq!(effects.next_wakeup, Some(arrival + budget));

        let (batcher, effects) = batcher.on_wakeup(arrival + budget, &workers);
        assert!(matches!(batcher, BatcherStateMachine::Running(_)));
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![1])]);
    }

    #[test]
    fn a_revoke_drops_a_message_held_in_an_open_batch() {
        let now = Instant::now();
        let budget = Duration::from_secs(10);
        let workers = pool(&["w"]);
        let batcher = packing_batcher(100, budget, 4, now);
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1])]);
        assert!(effects.sends.is_empty());

        let (batcher, effects) = batcher.on_partitions_revoked(now, &[("events".to_string(), 0)]);
        assert_eq!(effects.evicted_keys, vec![Arc::<str>::from("a")]);
        assert_eq!(batcher.pending_messages(), 0);

        let (_, effects) = batcher.on_wakeup(now + budget, &workers);
        assert!(effects.sends.is_empty());
    }

    #[test]
    fn a_worker_accepting_fewer_messages_than_sent_fails_the_state_machine() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(4, now);
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1, 2])]);
        let request = effects.sends[0].request;

        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, request, 1);
        assert!(matches!(batcher, BatcherStateMachine::Failed));
        assert!(effects.fatal.is_some());
    }

    #[test]
    fn an_accepted_request_completes_each_partition_and_acks_only_keyed_messages() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(4, now);
        let keyed = KeyRun {
            routing_key: "a".into(),
            messages: vec![message("a", 0, 1), message("a", 1, 2)],
        };
        let unkeyed = KeyRun {
            routing_key: ":2:5".into(),
            messages: vec![SerializedKafkaMessage {
                key: None,
                ..message("unkeyed", 2, 5)
            }],
        };
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![keyed, unkeyed]);
        let (keyed_request, unkeyed_request) = (effects.sends[0].request, effects.sends[1].request);

        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, keyed_request, 2);
        let completed: Vec<_> = effects
            .completions
            .iter()
            .map(|completion| (completion.partition.0, completion.offsets.clone()))
            .collect();
        assert_eq!(completed, vec![(0, vec![Offset(1)]), (1, vec![Offset(2)])]);
        assert_eq!(
            effects.key_acks,
            vec![KeyAck {
                routing_key: "a".into(),
                max_offset: 2
            }]
        );

        let (_, effects) = batcher.on_request_succeeded(now, &workers, unkeyed_request, 1);
        assert_eq!(effects.completions[0].offsets, vec![Offset(5)]);
        assert!(effects.key_acks.is_empty());
    }

    #[test]
    fn a_failed_run_spanning_a_revoked_partition_replays_only_the_kept_partition_in_order() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let spanning = KeyRun {
            routing_key: "a".into(),
            messages: vec![message("a", 0, 1), message("a", 1, 7)],
        };
        let (batcher, effects) = batcher(4, now).on_groups(now, &workers, 0, vec![spanning]);
        let (request, messages) = (effects.sends[0].request, sent_messages(&effects.sends[0]));
        let later = KeyRun {
            routing_key: "a".into(),
            messages: vec![message("a", 1, 8)],
        };
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![later]);
        assert!(effects.sends.is_empty());

        let (batcher, effects) = batcher.on_partitions_revoked(now, &[("events".to_string(), 0)]);
        assert!(effects.evicted_keys.is_empty(), "a's run is in flight");
        let (batcher, _) =
            batcher.on_request_failed(now, &workers, request, FailureCause::Fault, messages);

        let retry_at = now + FAULT_DELAY;
        let (batcher, effects) = batcher.on_wakeup(retry_at, &workers);
        assert!(effects.sends[0].class.replay);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![7])]);
        let replay = effects.sends[0].request;

        let (_, effects) = batcher.on_request_succeeded(retry_at, &workers, replay, 1);
        assert_eq!(effects.completions[0].offsets, vec![Offset(7)]);
        assert!(!effects.sends[0].class.replay);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![8])]);
    }

    #[test]
    fn a_revoke_then_reassign_drops_the_old_requeue_and_sends_the_new_epoch_run_once() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let (batcher, effects) =
            batcher(4, now).on_groups(now, &workers, 1, vec![run("a", &[1, 2])]);
        let (request, messages) = (effects.sends[0].request, sent_messages(&effects.sends[0]));
        let (batcher, _) = batcher.on_partitions_revoked(now, &[("events".to_string(), 0)]);
        // The new owner of the partition replays the uncommitted offsets.
        let (batcher, effects) = batcher.on_groups(now, &workers, 2, vec![run("a", &[1, 2, 3])]);
        assert!(effects.sends.is_empty(), "a's epoch-1 run is still out");

        let (batcher, effects) =
            batcher.on_request_failed(now, &workers, request, FailureCause::Fault, messages);
        assert_eq!(effects.sends.len(), 1, "the epoch-2 run goes at once");
        assert_eq!(effects.sends[0].class.assignment_epoch, 2);
        assert!(!effects.sends[0].class.replay);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![1, 2, 3])]);
        let request = effects.sends[0].request;

        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, request, 3);
        assert_eq!(effects.completions.len(), 1);
        assert_eq!(effects.completions[0].assignment_epoch, 2);
        assert_eq!(
            effects.completions[0].offsets,
            vec![Offset(1), Offset(2), Offset(3)]
        );
        assert_eq!(batcher.pending_messages(), 0);
        assert_eq!(batcher.in_flight_messages(), 0);
    }

    #[test]
    fn a_second_response_for_the_same_request_fails_the_state_machine() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let (batcher, effects) = batcher(4, now).on_groups(now, &workers, 0, vec![run("a", &[1])]);
        let request = effects.sends[0].request;
        let (batcher, _) = batcher.on_request_succeeded(now, &workers, request, 1);

        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, request, 1);
        assert!(matches!(batcher, BatcherStateMachine::Failed));
        assert!(effects.fatal.is_some());
        assert!(effects.completions.is_empty());
    }

    #[test]
    fn a_failure_handing_back_extra_messages_fails_the_state_machine() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let (batcher, effects) = batcher(4, now).on_groups(now, &workers, 0, vec![run("a", &[1])]);
        let request = effects.sends[0].request;

        let (batcher, effects) = batcher.on_request_failed(
            now,
            &workers,
            request,
            FailureCause::Fault,
            vec![message("a", 0, 1), message("a", 0, 2)],
        );
        assert!(matches!(batcher, BatcherStateMachine::Failed));
        assert!(effects.fatal.is_some());
    }

    #[test]
    fn a_revoke_during_a_replay_wait_leaves_no_wait_behind_for_a_fresh_sibling_partition() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let (batcher, effects) = batcher(4, now).on_groups(now, &workers, 0, vec![run("a", &[1])]);
        let (request, messages) = (effects.sends[0].request, sent_messages(&effects.sends[0]));
        let sibling = KeyRun {
            routing_key: "a".into(),
            messages: vec![message("a", 1, 7)],
        };
        let (batcher, _) = batcher.on_groups(now, &workers, 0, vec![sibling]);
        let (batcher, _) =
            batcher.on_request_failed(now, &workers, request, FailureCause::Fault, messages);

        let (batcher, effects) = batcher.on_partitions_revoked(now, &[("events".to_string(), 0)]);
        assert_eq!(effects.next_wakeup, Some(now), "a is ready again at once");
        let (_, effects) = batcher.on_wakeup(now, &workers);
        assert!(!effects.sends[0].class.replay);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![7])]);
    }

    #[test]
    fn the_watchdog_fires_once_overlapping_failures_drain_even_with_waiting_retries() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let (mut batcher, effects) =
            batcher(2, now).on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        let mut outstanding: VecDeque<_> = effects
            .sends
            .iter()
            .map(|send| (send.request, sent_messages(send)))
            .collect();

        let mut at = now;
        let (failed, fired_at) = loop {
            at += BUSY_DELAY;
            assert!(at < now + STALL * 2, "the watchdog never fired");
            let (request, messages) = outstanding.pop_front().expect("a request in flight");
            let (next, effects) =
                batcher.on_request_failed(at, &workers, request, FailureCause::Busy, messages);
            if effects.fatal.is_some() {
                break (next, at);
            }
            let (next, effects) = next.on_wakeup(at + BUSY_DELAY, &workers);
            outstanding.extend(
                effects
                    .sends
                    .iter()
                    .map(|send| (send.request, sent_messages(send))),
            );
            batcher = next;
        };
        assert!(matches!(failed, BatcherStateMachine::Failed));
        assert!(fired_at <= now + STALL + BUSY_DELAY * 3);
    }

    #[test]
    fn draining_stops_when_an_in_flight_run_of_a_revoked_partition_fails() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let (batcher, effects) = batcher(4, now).on_groups(now, &workers, 0, vec![run("a", &[1])]);
        let (request, messages) = (effects.sends[0].request, sent_messages(&effects.sends[0]));
        let (batcher, _) = batcher.on_shutdown(now, &workers);
        let (batcher, _) = batcher.on_partitions_revoked(now, &[("events".to_string(), 0)]);
        assert!(
            matches!(batcher, BatcherStateMachine::Draining(_)),
            "a is in flight"
        );

        let (batcher, effects) =
            batcher.on_request_failed(now, &workers, request, FailureCause::Fault, messages);
        assert!(matches!(batcher, BatcherStateMachine::Stopped));
        assert!(effects.sends.is_empty());
        assert!(effects.completions.is_empty());
        assert_eq!(effects.next_wakeup, None);
    }
}
