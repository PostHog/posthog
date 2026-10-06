//! A key's messages flow one way: a key queue, then a request on the wire.
//! A request that comes back with returned messages, or fails on the
//! transport, puts them back at the front of the key's queue with a retry
//! time. Retried messages leave the queue like fresh ones.

use std::cmp::Reverse;
use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{GroupCompletion, Offset, Partition};
use metrics::{gauge, histogram};

use super::in_flight::{InFlightRequest, InFlightRequests, KeyOutcome, RequestId};
use super::key_queues::{KeyQueues, KeyRun};
use super::request::{purge_request, Request, RequestClass};
use super::retry_policy::{RetryPolicy, RetryReason};
use super::worker_assigner::WorkerAssigner;
use super::worker_pool::WorkerPool;
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
    /// Sends must begin in this order, which is the per-key send order.
    pub sends: Vec<SendRequest>,
    /// One completion per partition, so each poll is credited per offset.
    pub completions: Vec<GroupCompletion>,
    pub key_acks: Vec<KeyAck>,
    /// Keys that left the state machine; their order-sentinel state can go.
    pub evicted_keys: Vec<Arc<str>>,
    pub worker_outcomes: Vec<WorkerOutcome>,
    /// Workers with nothing left in flight. A draining worker in this list
    /// has finished its work.
    pub idle_workers: Vec<WorkerId>,
    /// Workers that had nothing in flight and now have a request.
    pub busy_workers: Vec<WorkerId>,
    /// Set on the action that fails the state machine. The caller fails the
    /// process.
    pub fatal: Option<String>,
    /// When to call [`BatcherStateMachine::on_wakeup`]. `None` needs no timer.
    pub next_wakeup: Option<Instant>,
}

/// Actions do no I/O: the caller performs the returned [`Effects`].
pub enum BatcherStateMachine {
    Running(ActiveState),
    Draining(ActiveState),
    Stopped,
    Failed,
}

impl BatcherStateMachine {
    /// Stuck work with nothing in flight and no accepted message for
    /// `stall_timeout` fails the state machine, so a wedged batcher restarts
    /// loudly instead of growing lag. A zero timeout would fire on every
    /// action.
    pub fn new(
        assigner: WorkerAssigner,
        retry: RetryPolicy,
        stall_timeout: Duration,
        now: Instant,
    ) -> Result<Self, String> {
        if stall_timeout.is_zero() {
            return Err("stall_timeout must be > 0".to_string());
        }
        Ok(BatcherStateMachine::Running(ActiveState {
            keys: KeyQueues::new(),
            assigner,
            in_flight: InFlightRequests::new(),
            unplaced: VecDeque::new(),
            retry,
            stall_timeout,
            last_progress: now,
        }))
    }

    /// One poll's key runs, in poll order, collected under `assignment_epoch`.
    pub fn on_groups(
        self,
        now: Instant,
        pool: &WorkerPool,
        assignment_epoch: u64,
        runs: Vec<KeyRun>,
    ) -> (Self, Effects) {
        match self {
            BatcherStateMachine::Running(mut active) => {
                let result = active.on_groups(now, pool, assignment_epoch, runs);
                Self::after(active, false, result)
            }
            BatcherStateMachine::Draining(_) | BatcherStateMachine::Stopped => {
                Self::failed("groups submitted after shutdown started".to_string())
            }
            BatcherStateMachine::Failed => (BatcherStateMachine::Failed, Effects::default()),
        }
    }

    /// A request got a response, which may be partial. `returned` holds the
    /// messages the worker did not process; they wait for the timeout delay,
    /// then go out again as replay. `accepted` is the
    /// worker's own count of the rest.
    pub fn on_request_succeeded(
        self,
        now: Instant,
        pool: &WorkerPool,
        request: RequestId,
        accepted: u32,
        returned: Vec<SerializedKafkaMessage>,
    ) -> (Self, Effects) {
        self.act(|active| active.on_request_succeeded(now, pool, request, accepted, returned))
    }

    /// A request failed on the transport. `messages` is every message of the
    /// request, handed back by the transport.
    pub fn on_request_failed(
        self,
        now: Instant,
        pool: &WorkerPool,
        request: RequestId,
        cause: FailureCause,
        messages: Vec<SerializedKafkaMessage>,
    ) -> (Self, Effects) {
        self.act(|active| active.on_request_failed(now, pool, request, cause, messages))
    }

    pub fn on_wakeup(self, now: Instant, pool: &WorkerPool) -> (Self, Effects) {
        self.act(|active| {
            let mut effects = Effects::default();
            active.advance(now, pool, &mut effects)?;
            Ok(effects)
        })
    }

    /// Partitions were revoked, as `(topic, partition)`. Their pending
    /// messages drop, because the new partition owner replays them. A revoke
    /// never sends: it runs on the rebalance callback, outside the runtime
    /// that begins sends. It asks for an immediate wakeup instead when keys
    /// became ready.
    pub fn on_partitions_revoked(
        self,
        now: Instant,
        partitions: &[(String, i32)],
    ) -> (Self, Effects) {
        self.act(|active| active.on_partitions_revoked(now, partitions))
    }

    pub fn on_shutdown(self, now: Instant, pool: &WorkerPool) -> (Self, Effects) {
        match self {
            BatcherStateMachine::Running(active) => {
                BatcherStateMachine::Draining(active).on_wakeup(now, pool)
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
        action: impl FnOnce(&mut ActiveState) -> Result<Effects, String>,
    ) -> (Self, Effects) {
        match self {
            BatcherStateMachine::Running(mut active) => {
                let result = action(&mut active);
                Self::after(active, false, result)
            }
            BatcherStateMachine::Draining(mut active) => {
                let result = action(&mut active);
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
    assigner: WorkerAssigner,
    in_flight: InFlightRequests,
    /// Requests that found no worker or no free send slot, oldest first.
    /// Their keys stay claimed.
    unplaced: VecDeque<Request>,
    retry: RetryPolicy,
    stall_timeout: Duration,
    last_progress: Instant,
}

impl ActiveState {
    fn pending_messages(&self) -> usize {
        self.keys.queued_messages()
            + self
                .unplaced
                .iter()
                .map(|request| request.message_count)
                .sum::<usize>()
    }

    /// No timer runs while nothing can stall, so the stall clock starts when
    /// work becomes stuck, not at the last action before the quiet period.
    fn restart_stall_clock_if_quiet(&mut self, now: Instant) {
        if self.pending_messages() == 0 && self.in_flight.is_empty() {
            self.last_progress = now;
        }
    }

    fn is_drained(&self) -> bool {
        self.pending_messages() == 0 && self.in_flight.is_empty()
    }

    fn on_groups(
        &mut self,
        now: Instant,
        pool: &WorkerPool,
        assignment_epoch: u64,
        runs: Vec<KeyRun>,
    ) -> Result<Effects, String> {
        self.restart_stall_clock_if_quiet(now);
        for run in runs {
            self.keys
                .push(run.routing_key, assignment_epoch, run.messages, now);
        }
        let mut effects = Effects::default();
        self.advance(now, pool, &mut effects)?;
        Ok(effects)
    }

    fn on_request_succeeded(
        &mut self,
        now: Instant,
        pool: &WorkerPool,
        request: RequestId,
        accepted: u32,
        returned: Vec<SerializedKafkaMessage>,
    ) -> Result<Effects, String> {
        let mut effects = Effects::default();
        let sent = self.take_request(request, &mut effects)?;
        let returned_count = returned.len();
        let message_count = sent.message_count;
        let assignment_epoch = sent.class.assignment_epoch;
        effects.worker_outcomes.push(WorkerOutcome {
            worker: sent.worker.clone(),
            fault: false,
        });
        let outcomes = sent
            .resolve(returned)
            .map_err(|err| format!("invalid response: {err}"))?;
        if accepted as usize != message_count - returned_count {
            return Err(format!(
                "worker accepted {accepted} of {message_count} messages but returned {returned_count}"
            ));
        }
        if accepted > 0 {
            self.last_progress = now;
        }
        effects.completions = completions(assignment_epoch, &outcomes);
        effects.key_acks = key_acks(&outcomes);
        let retry_at = self.retry.retry_at(now, RetryReason::Returned);
        for outcome in outcomes {
            let retry_at = (!outcome.returned.is_empty()).then_some(retry_at);
            self.settle_key(
                &outcome.routing_key,
                outcome.returned,
                retry_at,
                now,
                &mut effects,
            )?;
        }
        self.advance(now, pool, &mut effects)?;
        Ok(effects)
    }

    fn on_request_failed(
        &mut self,
        now: Instant,
        pool: &WorkerPool,
        request: RequestId,
        cause: FailureCause,
        messages: Vec<SerializedKafkaMessage>,
    ) -> Result<Effects, String> {
        let mut effects = Effects::default();
        let sent = self.take_request(request, &mut effects)?;
        if messages.len() != sent.message_count {
            return Err(format!(
                "transport handed back {} of {} messages of a failed request",
                messages.len(),
                sent.message_count
            ));
        }
        effects.worker_outcomes.push(WorkerOutcome {
            worker: sent.worker.clone(),
            fault: cause == FailureCause::Fault,
        });
        let outcomes = sent
            .resolve(messages)
            .map_err(|err| format!("invalid failed request: {err}"))?;
        let retry_at = self.retry.retry_at(
            now,
            match cause {
                FailureCause::Fault => RetryReason::Fault,
                FailureCause::Busy => RetryReason::Busy,
            },
        );
        for outcome in outcomes {
            self.settle_key(
                &outcome.routing_key,
                outcome.returned,
                Some(retry_at),
                now,
                &mut effects,
            )?;
        }
        self.advance(now, pool, &mut effects)?;
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

        let mut emptied_keys = Vec::new();
        let revoked: HashSet<(&str, i32)> = partitions
            .iter()
            .map(|(topic, partition)| (topic.as_str(), *partition))
            .collect();
        for request in self.unplaced.iter_mut() {
            purge_request(request, &revoked, &mut emptied_keys);
        }
        self.unplaced.retain(|request| !request.runs.is_empty());
        for key in emptied_keys {
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
        returned: Vec<SerializedKafkaMessage>,
        retry_at: Option<Instant>,
        now: Instant,
        effects: &mut Effects,
    ) -> Result<(), String> {
        let evicted = self
            .keys
            .settle(routing_key, returned, retry_at, now)
            .map_err(|err| err.to_string())?;
        if evicted {
            effects.evicted_keys.push(Arc::clone(routing_key));
        }
        Ok(())
    }

    fn advance(
        &mut self,
        now: Instant,
        pool: &WorkerPool,
        effects: &mut Effects,
    ) -> Result<(), String> {
        self.restart_stall_clock_if_quiet(now);
        // Past the stall deadline, no new request starts, so overlapping
        // failures drain to nothing in flight and the watchdog can fire. A
        // request still in flight may yet be accepted, which resets it.
        let stalled = self.pending_messages() > 0 && now >= self.last_progress + self.stall_timeout;
        if !stalled {
            self.place(now, pool, effects);
        }
        self.finish(now, effects)
    }

    /// Each claimed key run goes out as a request of its own.
    fn place(&mut self, now: Instant, pool: &WorkerPool, effects: &mut Effects) {
        let mut batch: Vec<Request> = self.unplaced.drain(..).collect();
        batch.extend(self.keys.take_ready(now).into_iter().map(Request::from_run));
        if self.assigner.prefers_largest_first() {
            // Bin-packing places the heavy requests first, so they drive
            // the load distribution.
            batch.sort_by_key(|request| Reverse(request.message_count));
        }
        for request in batch {
            // A replay escapes the aperture slice and routes over the whole
            // healthy pool: the slice may be exactly what it failed in.
            let candidates = if request.class.replay {
                &pool.healthy
            } else {
                &pool.candidates
            };
            let Some(worker) = self.assigner.assign(candidates, request.message_count) else {
                // Requests carry disjoint keys, so their send order does
                // not matter for per-key order. A request that no
                // candidate can take must not hold back the others.
                self.unplaced.push_back(request);
                continue;
            };
            if self.assigner.requests_on(&worker) == 1 {
                effects.busy_workers.push(worker.clone());
            }
            self.send(now, worker, request, effects);
        }
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
        let pending = self.pending_messages();
        let in_flight = self.in_flight.len();
        if pending == 0 && in_flight == 0 {
            self.last_progress = now;
        }
        self.record_gauges();
        let stall_deadline = self.last_progress + self.stall_timeout;
        if pending > 0 && in_flight == 0 && now >= stall_deadline {
            return Err("pending work made no progress within the stall timeout".to_string());
        }
        effects.next_wakeup = [
            self.keys.next_retry_at(),
            (!self.unplaced.is_empty()).then(|| self.retry.retry_at(now, RetryReason::NoWorker)),
            // The watchdog fires only with nothing in flight. While a request
            // is out, its response re-checks the stall.
            (pending > 0 && in_flight == 0).then_some(stall_deadline),
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
        gauge!("ingestion_consumer_batcher_unplaced_requests").set(self.unplaced.len() as f64);
        gauge!("ingestion_consumer_batcher_unplaced_messages").set(
            self.unplaced
                .iter()
                .map(|request| request.message_count)
                .sum::<usize>() as f64,
        );
        gauge!("ingestion_consumer_batcher_in_flight_requests").set(self.in_flight.len() as f64);
    }
}

fn completions(assignment_epoch: u64, outcomes: &[KeyOutcome]) -> Vec<GroupCompletion> {
    let mut by_partition: HashMap<i32, Vec<Offset>> = HashMap::new();
    for outcome in outcomes {
        for message in &outcome.accepted {
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

fn key_acks(outcomes: &[KeyOutcome]) -> Vec<KeyAck> {
    outcomes
        .iter()
        .filter_map(|outcome| {
            let max_offset = outcome
                .accepted
                .iter()
                // An unkeyed message lives on an arbitrary partition under a
                // synthetic key, so it does not advance an ACK high-water mark.
                .filter(|message| message.keyed)
                .map(|message| message.offset)
                .max()?;
            Some(KeyAck {
                routing_key: Arc::clone(&outcome.routing_key),
                max_offset,
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use rstest::rstest;

    use super::*;
    use crate::batcher::test_support::{message, offsets};
    use crate::routing::{Router, RoutingStrategy};

    const FAULT_DELAY: Duration = Duration::from_millis(200);
    const BUSY_DELAY: Duration = Duration::from_millis(20);
    const RETURNED_DELAY: Duration = Duration::from_millis(50);
    const NO_WORKER_DELAY: Duration = Duration::from_millis(100);
    const STALL: Duration = Duration::from_secs(60);

    /// Distinct delays, so a wakeup time shows which retry reason applied.
    fn retry_policy() -> RetryPolicy {
        RetryPolicy::new(FAULT_DELAY, BUSY_DELAY, RETURNED_DELAY, NO_WORKER_DELAY)
            .expect("valid retry policy")
    }

    fn batcher(max_requests_per_worker: usize, now: Instant) -> BatcherStateMachine {
        let assigner = WorkerAssigner::new(
            Router::new(RoutingStrategy::BinPack),
            max_requests_per_worker,
        )
        .expect("valid request cap");
        BatcherStateMachine::new(assigner, retry_policy(), STALL, now).expect("valid stall timeout")
    }

    fn pool(workers: &[&str]) -> WorkerPool {
        let workers: Vec<WorkerId> = workers.iter().map(|w| WorkerId::from(*w)).collect();
        WorkerPool {
            healthy: workers.clone(),
            candidates: workers,
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

    fn shape(send: &SendRequest) -> Vec<(&str, Vec<i64>)> {
        send.runs
            .iter()
            .map(|run| (&*run.routing_key, offsets(&run.messages)))
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

        let (_, effects) = batcher.on_request_succeeded(now, &workers, request, 1, Vec::new());
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

        let (_, effects) = batcher.on_request_succeeded(now, &workers, request, 1, Vec::new());
        assert_eq!(effects.sends[0].class.assignment_epoch, 2);
        assert_eq!(shape(&effects.sends[0]), vec![("k", vec![2])]);
    }

    #[test]
    fn a_partial_response_replays_the_returned_suffix_after_the_timeout_delay() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(4, now);
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1, 2, 3])]);
        let request = effects.sends[0].request;
        let (batcher, _) = batcher.on_groups(now, &workers, 0, vec![run("a", &[4])]);

        let returned = vec![message("a", 0, 2), message("a", 0, 3)];
        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, request, 1, returned);
        assert!(effects.sends.is_empty());
        assert_eq!(effects.completions[0].offsets, vec![Offset(1)]);
        assert_eq!(effects.next_wakeup, Some(now + RETURNED_DELAY));

        let retry = now + RETURNED_DELAY;
        let (batcher, effects) = batcher.on_wakeup(retry, &workers);
        assert!(effects.sends[0].class.replay);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![2, 3])]);

        // The fresh message behind the replay waits for it, so order holds.
        let replay = effects.sends[0].request;
        let (_, effects) = batcher.on_request_succeeded(retry, &workers, replay, 2, Vec::new());
        assert!(!effects.sends[0].class.replay);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![4])]);
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
    fn a_replay_is_sent_past_a_fresh_request_that_no_candidate_can_take() {
        let now = Instant::now();
        let batcher = batcher(4, now);
        let (batcher, effects) = batcher.on_groups(now, &pool(&["w"]), 0, vec![run("b", &[2])]);
        let request = effects.sends[0].request;
        let (batcher, _) = batcher.on_request_failed(
            now,
            &pool(&["w"]),
            request,
            FailureCause::Busy,
            vec![message("b", 0, 2)],
        );

        let outside_the_slice = WorkerPool {
            healthy: pool(&["w"]).healthy,
            candidates: Vec::new(),
        };
        let (batcher, effects) =
            batcher.on_groups(now, &outside_the_slice, 0, vec![run("a", &[1])]);
        assert!(
            effects.sends.is_empty(),
            "a fresh request routes only within the slice"
        );

        let retry = now + BUSY_DELAY;
        let (_, effects) = batcher.on_wakeup(retry, &outside_the_slice);
        assert_eq!(effects.sends.len(), 1);
        assert!(effects.sends[0].class.replay);
        assert_eq!(shape(&effects.sends[0]), vec![("b", vec![2])]);
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
        assert!(effects.next_wakeup.is_some());

        let later = now + Duration::from_millis(100);
        let (_, effects) = batcher.on_wakeup(later, &pool(&["w"]));
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

        let (_, effects) = batcher.on_request_succeeded(now, &workers, request, 1, Vec::new());
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

        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, first, 1, Vec::new());
        assert!(effects.idle_workers.is_empty());

        let (_, effects) = batcher.on_request_succeeded(now, &workers, second, 1, Vec::new());
        assert_eq!(effects.idle_workers, vec![WorkerId::from("w")]);
    }

    /// Where the revoked message waits: with no healthy worker, or with no
    /// candidate in the aperture slice.
    #[rstest]
    #[case::no_worker(&[], &[])]
    #[case::outside_the_slice(&["w"], &[])]
    fn a_revoke_drops_pending_messages_and_never_sends_them(
        #[case] healthy: &[&str],
        #[case] candidates: &[&str],
    ) {
        let now = Instant::now();
        let batcher = batcher(4, now);
        let at_arrival = WorkerPool {
            healthy: pool(healthy).healthy,
            candidates: pool(candidates).candidates,
        };
        let (batcher, effects) = batcher.on_groups(now, &at_arrival, 0, vec![run("a", &[1])]);
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

        let (batcher, effects) =
            batcher.on_request_succeeded(now, &workers, request, 1, Vec::new());
        assert!(matches!(batcher, BatcherStateMachine::Stopped));
        assert_eq!(effects.next_wakeup, None);
    }

    #[test]
    fn a_zero_stall_timeout_is_rejected() {
        let assigner =
            WorkerAssigner::new(Router::new(RoutingStrategy::BinPack), 1).expect("valid cap");
        let created =
            BatcherStateMachine::new(assigner, retry_policy(), Duration::ZERO, Instant::now());
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
    fn a_response_that_breaks_the_suffix_contract_fails_the_state_machine() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = batcher(4, now);
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1, 2])]);
        let request = effects.sends[0].request;

        let (batcher, effects) =
            batcher.on_request_succeeded(now, &workers, request, 1, vec![message("a", 0, 1)]);
        assert!(matches!(batcher, BatcherStateMachine::Failed));
        assert!(effects.fatal.is_some());
    }
}
