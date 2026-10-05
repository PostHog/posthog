//! The batcher state machine: the key queues, the packer, the worker
//! assigner, and the in-flight requests, coordinated behind one sans-IO
//! machine.
//!
//! A key's messages flow one way: a key queue, then the packer, then a
//! request on the wire. A request that comes back with returned messages, or
//! fails on the transport, puts them back at the front of the key's queue
//! with a retry time. Retried messages go through the packer like fresh ones.
//!
//! Every action consumes the state and returns the next state with one
//! [`Step`], so a caller cannot act on a state the machine has left. An
//! action does no I/O. After every action that can make work ready, the
//! machine claims the ready keys into the packer and pulls packed requests
//! while workers have free send slots.
//!
//! A partially processed request is a success: its returned messages are a
//! per-key suffix that waits for the timeout retry delay, then goes through
//! the packer again as replay. A transport failure returns every message of
//! the request.

use std::collections::{HashMap, HashSet, VecDeque};
use std::time::{Duration, Instant};

use common_kafka_consumer::{GroupCompletion, Offset, Partition};
use metrics::gauge;

use super::in_flight::{InFlightRequest, InFlightRequests, KeyOutcome, RequestId};
use super::key_queues::{KeyQueues, KeyRun, Settled};
use super::packer::{purge_request, PackTargets, PackedRequest, Packer};
use super::request_class::RequestClass;
use super::worker_assigner::{WorkerAssigner, WorkerPool};
use crate::routing::Router;
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RetryPolicy {
    /// The worker or its stream failed. The pause gives a failing pool time
    /// to recover before the redelivery.
    pub fault: Duration,
    pub busy: Duration,
    /// The worker returned messages it did not process within the request's
    /// budget.
    pub timeout: Duration,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MachineConfig {
    pub pack_targets: PackTargets,
    pub max_requests_per_worker: usize,
    pub retry: RetryPolicy,
    pub unplaced_retry_interval: Duration,
    /// Stuck work with nothing in flight and no accepted message for this
    /// long fails the machine, so a wedged batcher restarts loudly instead of
    /// growing lag.
    pub stall_timeout: Duration,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FailureCause {
    Fault,
    Busy,
}

/// Sends must begin in step order, which is the per-key send order.
#[derive(Debug)]
pub struct Send {
    pub request: RequestId,
    pub worker: WorkerId,
    pub class: RequestClass,
    pub runs: Vec<KeyRun>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct KeyAck {
    pub routing_key: String,
    pub max_offset: i64,
}

#[derive(Debug, PartialEq, Eq)]
pub struct WorkerOutcome {
    pub worker: WorkerId,
    pub fault: bool,
}

#[derive(Debug, Default)]
pub struct Step {
    pub sends: Vec<Send>,
    /// One completion per partition, so each poll is credited per offset.
    pub completions: Vec<GroupCompletion>,
    pub key_acks: Vec<KeyAck>,
    /// Keys that left the machine; their order-sentinel state can go.
    pub evicted_keys: Vec<String>,
    pub worker_outcomes: Vec<WorkerOutcome>,
    /// Workers with nothing left in flight. A draining worker in this list
    /// has finished its work.
    pub idle_workers: Vec<WorkerId>,
    /// Set on the action that fails the machine. The caller fails the
    /// process.
    pub fatal: Option<String>,
    /// When to call [`BatcherState::on_wakeup`]. `None` needs no timer.
    pub next_wakeup: Option<Instant>,
}

pub enum BatcherState {
    Running(Work),
    /// Shutdown started: no new groups, every open batch seals at once, and
    /// retries continue until nothing is pending or in flight.
    Draining(Work),
    Stopped,
    Failed,
}

impl BatcherState {
    pub fn new(config: MachineConfig, router: Router, now: Instant) -> Self {
        BatcherState::Running(Work::new(config, router, now))
    }

    /// One poll's key runs, in poll order, collected under `assignment_epoch`.
    pub fn on_groups(
        self,
        now: Instant,
        pool: &WorkerPool,
        assignment_epoch: u64,
        runs: Vec<KeyRun>,
    ) -> (Self, Step) {
        match self {
            BatcherState::Running(mut work) => {
                let result = work.on_groups(now, pool, assignment_epoch, runs);
                Self::after(work, false, result)
            }
            BatcherState::Draining(_) | BatcherState::Stopped => {
                Self::failed("groups submitted after shutdown started".to_string())
            }
            BatcherState::Failed => (BatcherState::Failed, Step::default()),
        }
    }

    /// A request got a response. `returned` holds the messages the worker did
    /// not process; `accepted` is the worker's own count of the rest.
    pub fn on_request_succeeded(
        self,
        now: Instant,
        pool: &WorkerPool,
        request: RequestId,
        accepted: u32,
        returned: Vec<SerializedKafkaMessage>,
    ) -> (Self, Step) {
        self.act(|work, draining| {
            work.on_request_succeeded(now, pool, draining, request, accepted, returned)
        })
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
    ) -> (Self, Step) {
        self.act(|work, draining| {
            work.on_request_failed(now, pool, draining, request, cause, messages)
        })
    }

    pub fn on_wakeup(self, now: Instant, pool: &WorkerPool) -> (Self, Step) {
        self.act(|work, draining| {
            let mut step = Step::default();
            work.advance(now, pool, draining, &mut step)?;
            Ok(step)
        })
    }

    /// Partitions were revoked, as `(topic, partition)`. Their pending
    /// messages drop, because the new partition owner replays them. A revoke
    /// never sends: it runs on the rebalance callback, outside the runtime
    /// that begins sends. It asks for an immediate wakeup instead when keys
    /// became ready.
    pub fn on_partitions_revoked(self, now: Instant, partitions: &[(String, i32)]) -> (Self, Step) {
        self.act(|work, _| work.on_partitions_revoked(now, partitions))
    }

    pub fn on_shutdown(self, now: Instant, pool: &WorkerPool) -> (Self, Step) {
        match self {
            BatcherState::Running(work) => BatcherState::Draining(work).on_wakeup(now, pool),
            other => (other, Step::default()),
        }
    }

    pub fn pending_messages(&self) -> usize {
        match self {
            BatcherState::Running(work) | BatcherState::Draining(work) => work.pending_messages(),
            BatcherState::Stopped | BatcherState::Failed => 0,
        }
    }

    fn act(self, action: impl FnOnce(&mut Work, bool) -> Result<Step, String>) -> (Self, Step) {
        match self {
            BatcherState::Running(mut work) => {
                let result = action(&mut work, false);
                Self::after(work, false, result)
            }
            BatcherState::Draining(mut work) => {
                let result = action(&mut work, true);
                Self::after(work, true, result)
            }
            finished => (finished, Step::default()),
        }
    }

    fn after(work: Work, draining: bool, result: Result<Step, String>) -> (Self, Step) {
        match result {
            Err(reason) => Self::failed(reason),
            Ok(step) if draining && work.is_drained() => (
                BatcherState::Stopped,
                Step {
                    next_wakeup: None,
                    ..step
                },
            ),
            Ok(step) if draining => (BatcherState::Draining(work), step),
            Ok(step) => (BatcherState::Running(work), step),
        }
    }

    fn failed(reason: String) -> (Self, Step) {
        (
            BatcherState::Failed,
            Step {
                fatal: Some(reason),
                ..Step::default()
            },
        )
    }
}

pub struct Work {
    config: MachineConfig,
    keys: KeyQueues,
    packer: Packer,
    assigner: WorkerAssigner,
    in_flight: InFlightRequests,
    /// Packed requests that found no worker, oldest first. Their keys stay
    /// claimed.
    unplaced: VecDeque<PackedRequest>,
    last_progress: Instant,
}

impl Work {
    fn new(config: MachineConfig, router: Router, now: Instant) -> Self {
        Self {
            keys: KeyQueues::new(),
            packer: Packer::new(config.pack_targets),
            assigner: WorkerAssigner::new(router, config.max_requests_per_worker),
            in_flight: InFlightRequests::new(),
            unplaced: VecDeque::new(),
            last_progress: now,
            config,
        }
    }

    fn pending_messages(&self) -> usize {
        self.keys.queued_messages()
            + self.packer.held_messages()
            + self
                .unplaced
                .iter()
                .map(|request| request.message_count)
                .sum::<usize>()
    }

    /// An open batch waits for its deadline by design, so its messages do
    /// not count toward a stall however long the latency budget is.
    fn stuck_messages(&self) -> usize {
        self.pending_messages() - self.packer.open_messages()
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
    ) -> Result<Step, String> {
        // No timer runs while nothing can stall, so the stall clock starts
        // when work arrives, not at the last action before the quiet period.
        if self.stuck_messages() == 0 && self.in_flight.is_empty() {
            self.last_progress = now;
        }
        for run in runs {
            self.keys
                .push(&run.routing_key, assignment_epoch, run.messages, now);
        }
        let mut step = Step::default();
        self.advance(now, pool, false, &mut step)?;
        Ok(step)
    }

    fn on_request_succeeded(
        &mut self,
        now: Instant,
        pool: &WorkerPool,
        draining: bool,
        request: RequestId,
        accepted: u32,
        returned: Vec<SerializedKafkaMessage>,
    ) -> Result<Step, String> {
        let mut step = Step::default();
        let sent = self.take_request(request, &mut step)?;
        let returned_count = returned.len();
        let outcomes = sent
            .resolve(returned)
            .map_err(|err| format!("invalid response: {err}"))?;
        if accepted as usize != sent.message_count - returned_count {
            return Err(format!(
                "worker accepted {accepted} of {} messages but returned {returned_count}",
                sent.message_count
            ));
        }
        step.worker_outcomes.push(WorkerOutcome {
            worker: sent.worker.clone(),
            fault: false,
        });
        if accepted > 0 {
            self.last_progress = now;
        }
        step.completions = completions(sent.class.assignment_epoch, &outcomes);
        step.key_acks = key_acks(&outcomes);
        let retry_at = now + self.config.retry.timeout;
        for outcome in outcomes {
            let retry_at = (!outcome.returned.is_empty()).then_some(retry_at);
            self.settle_key(
                &outcome.routing_key,
                outcome.returned,
                retry_at,
                now,
                &mut step,
            );
        }
        self.advance(now, pool, draining, &mut step)?;
        Ok(step)
    }

    fn on_request_failed(
        &mut self,
        now: Instant,
        pool: &WorkerPool,
        draining: bool,
        request: RequestId,
        cause: FailureCause,
        messages: Vec<SerializedKafkaMessage>,
    ) -> Result<Step, String> {
        let mut step = Step::default();
        let sent = self.take_request(request, &mut step)?;
        if messages.len() != sent.message_count {
            return Err(format!(
                "transport handed back {} of {} messages of a failed request",
                messages.len(),
                sent.message_count
            ));
        }
        let outcomes = sent
            .resolve(messages)
            .map_err(|err| format!("invalid failed request: {err}"))?;
        step.worker_outcomes.push(WorkerOutcome {
            worker: sent.worker.clone(),
            fault: cause == FailureCause::Fault,
        });
        let delay = match cause {
            FailureCause::Fault => self.config.retry.fault,
            FailureCause::Busy => self.config.retry.busy,
        };
        for outcome in outcomes {
            self.settle_key(
                &outcome.routing_key,
                outcome.returned,
                Some(now + delay),
                now,
                &mut step,
            );
        }
        self.advance(now, pool, draining, &mut step)?;
        Ok(step)
    }

    fn on_partitions_revoked(
        &mut self,
        now: Instant,
        partitions: &[(String, i32)],
    ) -> Result<Step, String> {
        let mut step = Step::default();
        let purged = self.keys.purge(partitions);
        step.evicted_keys = purged.evicted_keys;

        let (_, mut emptied_keys) = self.packer.purge(partitions);
        let revoked: HashSet<(&str, i32)> = partitions
            .iter()
            .map(|(topic, partition)| (topic.as_str(), *partition))
            .collect();
        for request in self.unplaced.iter_mut() {
            purge_request(request, &revoked, &mut emptied_keys);
        }
        self.unplaced.retain(|request| !request.runs.is_empty());
        for key in emptied_keys {
            self.settle_key(&key, Vec::new(), None, now, &mut step);
        }

        self.finish(now, &mut step)?;
        if self.keys.has_ready() {
            step.next_wakeup = Some(now);
        }
        Ok(step)
    }

    fn take_request(
        &mut self,
        request: RequestId,
        step: &mut Step,
    ) -> Result<InFlightRequest, String> {
        let sent = self
            .in_flight
            .take(request)
            .ok_or_else(|| format!("response for unknown request {request:?}"))?;
        if self.assigner.release(&sent.worker, sent.message_count) {
            step.idle_workers.push(sent.worker.clone());
        }
        Ok(sent)
    }

    fn settle_key(
        &mut self,
        routing_key: &str,
        returned: Vec<SerializedKafkaMessage>,
        retry_at: Option<Instant>,
        now: Instant,
        step: &mut Step,
    ) {
        if self.keys.settle(routing_key, returned, retry_at, now) == Settled::Evicted {
            step.evicted_keys.push(routing_key.to_string());
        }
    }

    fn advance(
        &mut self,
        now: Instant,
        pool: &WorkerPool,
        draining: bool,
        step: &mut Step,
    ) -> Result<(), String> {
        for ready in self.keys.take_ready(now) {
            self.packer.push(ready, now);
        }
        if draining {
            self.packer.flush();
        } else {
            self.packer.seal_expired(now);
        }
        self.place(now, pool, step);
        self.finish(now, step)
    }

    fn place(&mut self, now: Instant, pool: &WorkerPool, step: &mut Step) {
        // Requests carry disjoint keys, so their send order does not matter
        // for per-key order. A request that no candidate can take must not
        // hold back the requests behind it.
        let mut retry = std::mem::take(&mut self.unplaced);
        let mut still_unplaced = VecDeque::new();
        loop {
            let request = match retry.pop_front() {
                Some(request) => request,
                None => {
                    if self.assigner.free_slots(&pool.healthy) == 0 {
                        break;
                    }
                    match self.packer.take_ready(now, 1).pop() {
                        Some(request) => request,
                        None => break,
                    }
                }
            };
            // A replay escapes the aperture slice and routes over the whole
            // healthy pool: the slice may be exactly what it failed in.
            let candidates = if request.class.replay {
                &pool.healthy
            } else {
                &pool.candidates
            };
            let Some(worker) = self.assigner.assign(candidates, request.message_count) else {
                still_unplaced.push_back(request);
                continue;
            };
            let id = self
                .in_flight
                .register(worker.clone(), request.class, &request.runs);
            step.sends.push(Send {
                request: id,
                worker,
                class: request.class,
                runs: request.runs,
            });
        }
        self.unplaced = still_unplaced;
    }

    fn finish(&mut self, now: Instant, step: &mut Step) -> Result<(), String> {
        let stuck = self.stuck_messages();
        let in_flight = self.in_flight.len();
        if stuck == 0 && in_flight == 0 {
            self.last_progress = now;
        }
        self.record_gauges();
        let stall_deadline = self.last_progress + self.config.stall_timeout;
        if stuck > 0 && in_flight == 0 && now >= stall_deadline {
            return Err("pending work made no progress within the stall timeout".to_string());
        }
        step.next_wakeup = [
            self.keys.next_retry_at(),
            self.packer.next_deadline(),
            // Nothing signals a worker joining the pool, so requests waiting
            // for a worker poll for one.
            (!self.unplaced.is_empty() || self.packer.sealed_requests() > 0)
                .then(|| now + self.config.unplaced_retry_interval),
            (stuck > 0).then_some(stall_deadline),
        ]
        .into_iter()
        .flatten()
        .min();
        Ok(())
    }

    fn record_gauges(&self) {
        gauge!("ingestion_consumer_machine_keys").set(self.keys.key_count() as f64);
        gauge!("ingestion_consumer_machine_queued_messages")
            .set(self.keys.queued_messages() as f64);
        gauge!("ingestion_consumer_machine_queued_bytes").set(self.keys.queued_bytes() as f64);
        gauge!("ingestion_consumer_machine_claimed_keys").set(self.keys.claimed_keys() as f64);
        gauge!("ingestion_consumer_machine_waiting_keys").set(self.keys.waiting_keys() as f64);
        gauge!("ingestion_consumer_machine_packer_held_messages")
            .set(self.packer.held_messages() as f64);
        gauge!("ingestion_consumer_machine_unplaced_requests").set(self.unplaced.len() as f64);
        gauge!("ingestion_consumer_machine_in_flight_requests").set(self.in_flight.len() as f64);
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

/// Only keyed messages advance a key's ACK high-water mark: an unkeyed
/// message lives on an arbitrary partition under a synthetic key.
fn key_acks(outcomes: &[KeyOutcome]) -> Vec<KeyAck> {
    outcomes
        .iter()
        .filter_map(|outcome| {
            let max_offset = outcome
                .accepted
                .iter()
                .filter(|message| message.keyed)
                .map(|message| message.offset)
                .max()?;
            Some(KeyAck {
                routing_key: outcome.routing_key.clone(),
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
    use crate::routing::RoutingStrategy;

    const FAULT_DELAY: Duration = Duration::from_millis(200);
    const TIMEOUT_DELAY: Duration = Duration::from_millis(50);
    const STALL: Duration = Duration::from_secs(60);

    fn config(events: usize, budget: Duration, max_requests_per_worker: usize) -> MachineConfig {
        MachineConfig {
            pack_targets: PackTargets {
                events,
                bytes: 0,
                latency_budget: budget,
            },
            max_requests_per_worker,
            retry: RetryPolicy {
                fault: FAULT_DELAY,
                busy: Duration::from_millis(20),
                timeout: TIMEOUT_DELAY,
            },
            unplaced_retry_interval: Duration::from_millis(100),
            stall_timeout: STALL,
        }
    }

    fn machine(config: MachineConfig, now: Instant) -> BatcherState {
        BatcherState::new(config, Router::new(RoutingStrategy::BinPack), now)
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
            routing_key: key.to_string(),
            messages: offsets
                .iter()
                .map(|&offset| message(key, 0, offset))
                .collect(),
        }
    }

    fn shape(send: &Send) -> Vec<(&str, Vec<i64>)> {
        send.runs
            .iter()
            .map(|run| (run.routing_key.as_str(), offsets(&run.messages)))
            .collect()
    }

    #[test]
    fn keys_pack_into_one_request_and_their_next_runs_wait_for_the_response() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let machine = machine(config(100, Duration::ZERO, 4), now);

        let (machine, step) =
            machine.on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        assert_eq!(step.sends.len(), 1);
        assert_eq!(shape(&step.sends[0]), vec![("a", vec![1]), ("b", vec![2])]);
        let request = step.sends[0].request;

        let (machine, step) = machine.on_groups(now, &workers, 0, vec![run("a", &[3])]);
        assert!(step.sends.is_empty(), "a's first run is still in flight");

        let (_, step) = machine.on_request_succeeded(now, &workers, request, 2, Vec::new());
        assert_eq!(shape(&step.sends[0]), vec![("a", vec![3])]);
        assert_eq!(step.completions.len(), 1);
        assert_eq!(step.completions[0].offsets, vec![Offset(1), Offset(2)]);
        assert_eq!(step.evicted_keys, vec!["b".to_string()]);
        assert_eq!(
            step.key_acks,
            vec![
                KeyAck {
                    routing_key: "a".to_string(),
                    max_offset: 1
                },
                KeyAck {
                    routing_key: "b".to_string(),
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
        let machine = machine(config(100, budget, 4), now);

        let (machine, _) = machine.on_groups(now, &workers, 1, vec![run("k", &[1])]);
        let (machine, step) = machine.on_groups(now, &workers, 2, vec![run("k", &[2])]);
        assert!(step.sends.is_empty());

        let (machine, step) = machine.on_wakeup(now + budget, &workers);
        assert_eq!(step.sends.len(), 1, "the epoch-2 message waits for k's run");
        assert_eq!(step.sends[0].class.assignment_epoch, 1);
        assert_eq!(shape(&step.sends[0]), vec![("k", vec![1])]);

        let request = step.sends[0].request;
        let later = now + budget * 2;
        let (machine, _) = machine.on_request_succeeded(later, &workers, request, 1, Vec::new());
        let (_, step) = machine.on_wakeup(later + budget, &workers);
        assert_eq!(step.sends[0].class.assignment_epoch, 2);
        assert_eq!(shape(&step.sends[0]), vec![("k", vec![2])]);
    }

    #[test]
    fn a_partial_response_replays_the_returned_suffix_after_the_timeout_delay() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let machine = machine(config(100, Duration::ZERO, 4), now);
        let (machine, step) = machine.on_groups(now, &workers, 0, vec![run("a", &[1, 2, 3])]);
        let request = step.sends[0].request;
        let (machine, _) = machine.on_groups(now, &workers, 0, vec![run("a", &[4])]);

        let returned = vec![message("a", 0, 2), message("a", 0, 3)];
        let (machine, step) = machine.on_request_succeeded(now, &workers, request, 1, returned);
        assert!(step.sends.is_empty());
        assert_eq!(step.completions[0].offsets, vec![Offset(1)]);
        assert_eq!(step.next_wakeup, Some(now + TIMEOUT_DELAY));

        let retry = now + TIMEOUT_DELAY;
        let (machine, step) = machine.on_wakeup(retry, &workers);
        assert!(step.sends[0].class.replay);
        assert_eq!(shape(&step.sends[0]), vec![("a", vec![2, 3])]);

        // The fresh message behind the replay waits for it, so order holds.
        let replay = step.sends[0].request;
        let (_, step) = machine.on_request_succeeded(retry, &workers, replay, 2, Vec::new());
        assert!(!step.sends[0].class.replay);
        assert_eq!(shape(&step.sends[0]), vec![("a", vec![4])]);
    }

    #[test]
    fn a_transport_failure_retries_on_its_own_delay_whatever_the_pack_budget() {
        let now = Instant::now();
        let budget = Duration::from_millis(10);
        let workers = pool(&["w"]);
        let machine = machine(config(2, budget, 4), now);
        let (machine, step) =
            machine.on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        let request = step.sends[0].request;

        let messages = vec![message("a", 0, 1), message("b", 0, 2)];
        let (machine, step) =
            machine.on_request_failed(now, &workers, request, FailureCause::Fault, messages);
        assert_eq!(
            step.worker_outcomes,
            vec![WorkerOutcome {
                worker: WorkerId::from("w"),
                fault: true
            }]
        );
        assert!(step.completions.is_empty());
        assert_eq!(step.next_wakeup, Some(now + FAULT_DELAY));

        let (machine, step) = machine.on_wakeup(now + budget, &workers);
        assert!(
            step.sends.is_empty(),
            "the pack budget does not pace retries"
        );

        let (_, step) = machine.on_wakeup(now + FAULT_DELAY, &workers);
        assert_eq!(step.sends.len(), 1, "the retries pack into one request");
        assert!(step.sends[0].class.replay);
    }

    #[test]
    fn a_replay_is_sent_past_a_fresh_request_that_no_candidate_can_take() {
        let now = Instant::now();
        let machine = machine(config(100, Duration::ZERO, 4), now);
        let (machine, step) = machine.on_groups(now, &pool(&["w"]), 0, vec![run("b", &[2])]);
        let request = step.sends[0].request;
        let (machine, _) = machine.on_request_failed(
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
        let (machine, step) = machine.on_groups(now, &outside_the_slice, 0, vec![run("a", &[1])]);
        assert!(
            step.sends.is_empty(),
            "a fresh request routes only within the slice"
        );

        let retry = now + Duration::from_millis(20);
        let (_, step) = machine.on_wakeup(retry, &outside_the_slice);
        assert_eq!(step.sends.len(), 1);
        assert!(step.sends[0].class.replay);
        assert_eq!(shape(&step.sends[0]), vec![("b", vec![2])]);
    }

    #[test]
    fn a_held_batch_leaves_at_its_deadline() {
        let now = Instant::now();
        let budget = Duration::from_millis(30);
        let workers = pool(&["w"]);
        let machine = machine(config(100, budget, 4), now);

        let (machine, step) = machine.on_groups(now, &workers, 0, vec![run("a", &[1])]);
        assert!(step.sends.is_empty());
        assert_eq!(step.next_wakeup, Some(now + budget));

        let (_, step) = machine.on_wakeup(now + budget, &workers);
        assert_eq!(shape(&step.sends[0]), vec![("a", vec![1])]);
    }

    #[test]
    fn a_request_without_a_worker_waits_and_is_sent_when_one_appears() {
        let now = Instant::now();
        let machine = machine(config(100, Duration::ZERO, 4), now);

        let (machine, step) = machine.on_groups(now, &pool(&[]), 0, vec![run("a", &[1])]);
        assert!(step.sends.is_empty());
        assert_eq!(machine.pending_messages(), 1);
        assert!(step.next_wakeup.is_some());

        let later = now + Duration::from_millis(100);
        let (_, step) = machine.on_wakeup(later, &pool(&["w"]));
        assert_eq!(shape(&step.sends[0]), vec![("a", vec![1])]);
    }

    #[test]
    fn the_request_cap_holds_sends_until_a_slot_frees() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let machine = machine(config(1, Duration::ZERO, 1), now);

        let (machine, step) =
            machine.on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        assert_eq!(step.sends.len(), 1);
        let request = step.sends[0].request;

        let (_, step) = machine.on_request_succeeded(now, &workers, request, 1, Vec::new());
        assert_eq!(shape(&step.sends[0]), vec![("b", vec![2])]);
    }

    /// Where the revoked message waits: in an open pack batch, sealed with no
    /// free send slot, or packed with no candidate worker.
    #[rstest]
    #[case::open_batch(Duration::from_secs(10), &["w"], &["w"])]
    #[case::sealed_without_a_slot(Duration::ZERO, &[], &[])]
    #[case::unplaced(Duration::ZERO, &["w"], &[])]
    fn a_revoke_drops_pending_messages_and_never_sends_them(
        #[case] budget: Duration,
        #[case] healthy: &[&str],
        #[case] candidates: &[&str],
    ) {
        let now = Instant::now();
        let machine = machine(config(100, budget, 4), now);
        let at_arrival = WorkerPool {
            healthy: pool(healthy).healthy,
            candidates: pool(candidates).candidates,
        };
        let (machine, step) = machine.on_groups(now, &at_arrival, 0, vec![run("a", &[1])]);
        assert!(step.sends.is_empty());

        let (machine, step) = machine.on_partitions_revoked(now, &[("events".to_string(), 0)]);
        assert!(step.sends.is_empty());
        assert_eq!(step.evicted_keys, vec!["a".to_string()]);
        assert_eq!(machine.pending_messages(), 0);

        let (_, step) = machine.on_wakeup(now + budget + STALL / 2, &pool(&["w"]));
        assert!(step.sends.is_empty());
    }

    #[test]
    fn shutdown_seals_held_batches_and_stops_once_drained() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let machine = machine(config(100, Duration::from_secs(10), 4), now);
        let (machine, _) = machine.on_groups(now, &workers, 0, vec![run("a", &[1])]);

        let (machine, step) = machine.on_shutdown(now, &workers);
        assert!(matches!(machine, BatcherState::Draining(_)));
        let request = step.sends[0].request;

        let (machine, step) = machine.on_request_succeeded(now, &workers, request, 1, Vec::new());
        assert!(matches!(machine, BatcherState::Stopped));
        assert_eq!(step.next_wakeup, None);
    }

    #[test]
    fn work_stuck_without_progress_fails_the_machine() {
        let now = Instant::now();
        let machine = machine(config(100, Duration::ZERO, 4), now);
        let (machine, _) = machine.on_groups(now, &pool(&[]), 0, vec![run("a", &[1])]);

        let (machine, step) = machine.on_wakeup(now + STALL, &pool(&[]));
        assert!(matches!(machine, BatcherState::Failed));
        assert!(step.fatal.is_some());
        assert_eq!(step.next_wakeup, None);
    }

    #[test]
    fn neither_an_idle_period_nor_a_long_pack_budget_counts_toward_a_stall() {
        let start = Instant::now();
        let budget = STALL * 2;
        let workers = pool(&["w"]);
        let machine = machine(config(100, budget, 4), start);

        let arrival = start + STALL * 3;
        let (machine, step) = machine.on_groups(arrival, &workers, 0, vec![run("a", &[1])]);
        assert!(matches!(machine, BatcherState::Running(_)));
        assert_eq!(step.next_wakeup, Some(arrival + budget));

        let (machine, step) = machine.on_wakeup(arrival + budget, &workers);
        assert!(matches!(machine, BatcherState::Running(_)));
        assert_eq!(shape(&step.sends[0]), vec![("a", vec![1])]);
    }

    #[test]
    fn a_response_that_breaks_the_suffix_contract_fails_the_machine() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let machine = machine(config(100, Duration::ZERO, 4), now);
        let (machine, step) = machine.on_groups(now, &workers, 0, vec![run("a", &[1, 2])]);
        let request = step.sends[0].request;

        let (machine, step) =
            machine.on_request_succeeded(now, &workers, request, 1, vec![message("a", 0, 1)]);
        assert!(matches!(machine, BatcherState::Failed));
        assert!(step.fatal.is_some());
    }
}
