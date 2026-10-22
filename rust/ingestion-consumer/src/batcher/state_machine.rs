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

use std::collections::HashMap;
use std::num::NonZeroU32;
use std::sync::Arc;
use std::time::{Duration, Instant};

use common_kafka_consumer::{GroupCompletion, Offset, Partition};
use metrics::{counter, gauge, histogram};

use super::governor::{Adaptation, Governor, GovernorSettings, GovernorSnapshot};
use super::in_flight::{InFlightRequest, InFlightRequests, RequestId, SentMessage};
use super::key_queues::{KeyQueues, KeyRun, Settlement};
use super::packer::Packer;
use super::request::{Request, RequestClass};
use super::retry_policy::{RetryPolicy, RetryReason};
use super::worker_assigner::{WorkerAssigner, WorkerInFlight};
use crate::order_sentinel::ack_mark;
use crate::types::SerializedKafkaMessage;
use crate::worker_registry::WorkerId;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FailureCause {
    Fault,
    Busy,
}

/// The worker's soft time budget for every request. A key resends without it
/// once `attempts` settles left its messages unfinished since it last finished
/// a run, or at once when its request finished nothing, so a message that
/// never fits the budget still finishes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RequestBudget {
    pub soft_budget: Duration,
    pub attempts: NonZeroU32,
}

#[derive(Debug)]
pub struct SendRequest {
    pub request: RequestId,
    pub worker: WorkerId,
    pub class: RequestClass,
    pub soft_budget: Option<Duration>,
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

/// A point-in-time view of the batcher's load, for the debug API.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BatcherSnapshot {
    pub keys: usize,
    pub pending_messages: usize,
    pub queued_bytes: usize,
    pub waiting_keys: usize,
    pub claimed_keys: usize,
    pub in_flight_requests: usize,
    pub in_flight_messages: usize,
    pub per_worker: Vec<WorkerInFlight>,
    pub governor: GovernorSnapshot,
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
        // Messages waiting for the pack deadline count toward a stall, so the
        // budget must leave most of the stall window.
        if packer.latency_budget() * 2 > stall_timeout {
            return Err(
                "the pack latency budget must be at most half the stall timeout".to_string(),
            );
        }
        // Without a target, one request takes every ready run of a class,
        // and one failure replays all of it.
        let targets = packer.targets();
        if targets.events.is_none() && targets.bytes.is_none() {
            return Err("set a pack target in events or bytes".to_string());
        }
        let governor = Governor::new(
            GovernorSettings::observing(),
            assigner.max_requests_per_worker(),
        )?;
        Ok(BatcherStateMachine::Running(ActiveState {
            keys: KeyQueues::new(packer.run_cap()),
            packer,
            assigner,
            in_flight: InFlightRequests::new(),
            retry,
            stall_timeout,
            last_progress: now,
            soft_budget: None,
            governor,
            reconnecting: HashMap::new(),
        }))
    }

    /// `None` sends no budget.
    pub fn with_request_budget(self, budget: Option<RequestBudget>) -> Self {
        match self {
            BatcherStateMachine::Running(active) => BatcherStateMachine::Running(ActiveState {
                soft_budget: budget.map(|budget| budget.soft_budget),
                keys: active
                    .keys
                    .with_budget_attempts(budget.map(|budget| budget.attempts)),
                ..active
            }),
            other => other,
        }
    }

    pub fn with_governor(self, settings: GovernorSettings) -> Result<Self, String> {
        match self {
            BatcherStateMachine::Running(active) => {
                let governor = Governor::new(settings, active.assigner.max_requests_per_worker())?;
                Ok(BatcherStateMachine::Running(ActiveState {
                    governor,
                    ..active
                }))
            }
            other => Ok(other),
        }
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

    /// The worker finished every message except `unfinished`. Those go back to
    /// the front of their keys' queues and are sent again at once as replay,
    /// without a budget when the worker finished nothing.
    pub fn on_request_partial(
        self,
        now: Instant,
        workers: &[WorkerId],
        request: RequestId,
        accepted: u32,
        unfinished: Vec<SerializedKafkaMessage>,
    ) -> (Self, Effects) {
        self.act(|active, draining| {
            active.on_request_partial(now, workers, draining, request, accepted, unfinished)
        })
    }

    /// The failed request's messages go back to the front of their keys'
    /// queues and are sent again as replay after the retry delay.
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

    /// Takes no new groups from now on, and stops once nothing is pending or
    /// in flight.
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

    pub fn snapshot(&self) -> BatcherSnapshot {
        self.active()
            .map_or_else(BatcherSnapshot::default, ActiveState::snapshot)
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
    soft_budget: Option<Duration>,
    governor: Governor,
    /// Workers whose stream a failure fenced, with the time of that failure.
    /// The stream reconnects after a backoff, so a request sent since then
    /// may wait it out and is no RTT sample. The first such request to settle
    /// clears the mark.
    reconnecting: HashMap<WorkerId, Instant>,
}

impl ActiveState {
    fn pending_messages(&self) -> usize {
        self.keys.queued_messages()
    }

    fn snapshot(&self) -> BatcherSnapshot {
        BatcherSnapshot {
            keys: self.keys.key_count(),
            pending_messages: self.keys.queued_messages(),
            queued_bytes: self.keys.queued_bytes(),
            waiting_keys: self.keys.waiting_keys(),
            claimed_keys: self.keys.claimed_keys(),
            in_flight_requests: self.in_flight.len(),
            in_flight_messages: self.assigner.in_flight_messages(),
            per_worker: self.assigner.in_flight_per_worker(),
            governor: self.governor.snapshot(),
        }
    }

    /// The stall clock starts when work becomes pending, not at the last
    /// action before a quiet period.
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
        self.observe_rtt(&sent, now);
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
        effects.completions =
            completions(assignment_epoch, runs.iter().flat_map(|run| &run.messages));
        effects.key_acks = key_acks(runs.iter().map(|run| {
            (
                &run.routing_key,
                run.first_keyed_partition(),
                run.messages.as_slice(),
                &[][..],
            )
        }));
        for run in runs {
            self.settle_key(&run.routing_key, Settlement::Done, now, &mut effects)?;
        }
        self.advance(now, workers, draining, &mut effects)?;
        Ok(effects)
    }

    fn on_request_partial(
        &mut self,
        now: Instant,
        workers: &[WorkerId],
        draining: bool,
        request: RequestId,
        accepted: u32,
        unfinished: Vec<SerializedKafkaMessage>,
    ) -> Result<Effects, String> {
        let mut effects = Effects::default();
        let sent = self.take_request(request, &mut effects)?;
        self.observe_rtt(&sent, now);
        effects.worker_outcomes.push(WorkerOutcome {
            worker: sent.worker.clone(),
            fault: false,
        });
        if accepted > 0 {
            self.last_progress = now;
        }
        let assignment_epoch = sent.class.assignment_epoch;
        let unfinished_count = unfinished.len();
        let partial_runs = sent.partially_accepted(accepted, unfinished)?;
        counter!("ingestion_consumer_request_budget_partials_total").increment(1);
        counter!("ingestion_consumer_request_budget_unfinished_messages_total")
            .increment(unfinished_count as u64);
        effects.completions = completions(
            assignment_epoch,
            partial_runs.iter().flat_map(|run| &run.accepted),
        );
        effects.key_acks = key_acks(partial_runs.iter().map(|run| {
            (
                &run.routing_key,
                run.first_keyed_partition,
                run.accepted.as_slice(),
                run.unfinished.as_slice(),
            )
        }));
        for run in partial_runs {
            let settlement = if run.unfinished.is_empty() {
                Settlement::Done
            } else if accepted == 0 {
                Settlement::Bounced(run.unfinished)
            } else {
                Settlement::Unfinished(run.unfinished)
            };
            self.settle_key(&run.routing_key, settlement, now, &mut effects)?;
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
        self.reconnecting.entry(sent.worker.clone()).or_insert(now);
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
            let settlement = Settlement::Failed {
                messages: run.messages,
                retry_at,
            };
            self.settle_key(&run.routing_key, settlement, now, &mut effects)?;
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

    /// Only an accepted or partial settlement is a sample, because a fault or
    /// a busy answer measures the failure, not the worker. Saturation still
    /// reaches the average, because the workers send no busy answer: a
    /// request that finds no free slot waits for one, and at its soft budget
    /// it comes back as a partial with nothing finished. Faults and ack
    /// timeouts go to health routing instead, and a busy answer waits out the
    /// busy retry delay.
    fn observe_rtt(&mut self, sent: &InFlightRequest, now: Instant) {
        let sent_while_reconnecting = self
            .reconnecting
            .get(&sent.worker)
            .is_some_and(|failed_at| sent.sent_at >= *failed_at);
        if sent_while_reconnecting {
            self.reconnecting.remove(&sent.worker);
            return;
        }
        let rtt = now.saturating_duration_since(sent.sent_at);
        if let Some(decision) = self.governor.observe(rtt, now) {
            counter!(
                "ingestion_consumer_governor_adjustments_total",
                "direction" => decision.direction.as_str(),
                "applied" => if decision.applied { "true" } else { "false" }
            )
            .increment(1);
        }
    }

    /// A request on a worker that left the pool holds none of the pool's
    /// permits, so the governor counts only the requests on `workers`.
    fn sync_governor(&mut self, workers: &[WorkerId]) {
        let in_flight = workers
            .iter()
            .map(|worker| self.assigner.requests_on(worker))
            .sum();
        self.governor.set_pool(workers.len(), in_flight);
        self.reconnecting
            .retain(|worker, _| workers.contains(worker));
    }

    fn settle_key(
        &mut self,
        routing_key: &Arc<str>,
        settlement: Settlement,
        now: Instant,
        effects: &mut Effects,
    ) -> Result<(), String> {
        let settled = self
            .keys
            .settle(routing_key, settlement, now)
            .map_err(|err| err.to_string())?;
        if settled.escalated {
            counter!("ingestion_consumer_request_budget_escalations_total").increment(1);
        }
        if settled.evicted {
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
        self.sync_governor(workers);
        // Past the stall deadline no new request starts, so overlapping
        // failures drain to nothing in flight and the watchdog can fire.
        let stalled = self.pending_messages() > 0 && now >= self.last_progress + self.stall_timeout;
        if !stalled {
            self.place(now, workers, draining, effects)?;
        }
        self.finish(now, effects)
    }

    fn place(
        &mut self,
        now: Instant,
        workers: &[WorkerId],
        draining: bool,
        effects: &mut Effects,
    ) -> Result<(), String> {
        let free_slots = self.assigner.free_slots(workers);
        let free_permits = self.governor.free();
        let free = match self.governor.adaptation() {
            Adaptation::On => free_slots.min(free_permits),
            Adaptation::Off => free_slots,
        };
        let batch = self.packer.pack(&mut self.keys, now, free, draining);
        // With adaptation off free slots size the pass, so the requests past
        // the free permits are the ones the governor would have held back.
        let mut starved_messages: usize = batch
            .iter()
            .skip(free_permits)
            .map(|request| request.message_count)
            .sum();
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
        self.sync_governor(workers);
        if self.governor.free() == 0 {
            starved_messages += self
                .keys
                .ready_sizes()
                .iter()
                .map(|(_, size)| size.messages)
                .sum::<usize>();
        }
        self.governor.set_starved_messages(starved_messages);
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
            .register(worker.clone(), request.class, now, &request.runs);
        effects.sends.push(SendRequest {
            request: id,
            worker,
            class: request.class,
            soft_budget: self.soft_budget.filter(|_| !request.class.unbudgeted),
            runs: request.runs,
        });
    }

    fn finish(&mut self, now: Instant, effects: &mut Effects) -> Result<(), String> {
        // A stalled action and a revoke skip `pack`, so without this a due
        // retry would set the next wakeup at or before `now`.
        self.keys.promote_due(now);
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
        // A passed deadline waits for a free slot like any other ready work.
        let pack_deadline = self.packer.deadline().filter(|deadline| *deadline > now);
        effects.next_wakeup = [
            self.keys.next_retry_at(),
            pack_deadline,
            (pack_deadline.is_none() && self.keys.has_ready())
                .then(|| self.retry.retry_at(now, RetryReason::NoWorker)),
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
        gauge!("ingestion_consumer_batcher_in_flight_requests").set(self.in_flight.len() as f64);
        let governor = self.governor.snapshot();
        gauge!("ingestion_consumer_governor_permits").set(governor.permits as f64);
        gauge!("ingestion_consumer_governor_ceiling").set(governor.ceiling as f64);
        gauge!("ingestion_consumer_governor_free_permits").set(governor.free_permits as f64);
        gauge!("ingestion_consumer_governor_starved_messages")
            .set(governor.starved_messages as f64);
        if let Some(rtt) = governor.rtt {
            gauge!("ingestion_consumer_request_rtt_seconds").set(rtt.as_secs_f64());
        }
    }
}

fn completions<'a>(
    assignment_epoch: u64,
    messages: impl IntoIterator<Item = &'a SentMessage>,
) -> Vec<GroupCompletion> {
    let mut by_partition: HashMap<i32, Vec<Offset>> = HashMap::new();
    for message in messages {
        by_partition
            .entry(message.partition)
            .or_default()
            .push(Offset(message.offset));
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

fn key_acks<'a>(
    runs: impl IntoIterator<
        Item = (
            &'a Arc<str>,
            Option<i32>,
            &'a [SentMessage],
            &'a [SerializedKafkaMessage],
        ),
    >,
) -> Vec<KeyAck> {
    runs.into_iter()
        .filter_map(
            |(routing_key, first_keyed_partition, accepted, unfinished)| {
                let max_offset = ack_mark(
                    first_keyed_partition?,
                    accepted
                        .iter()
                        .map(|message| (message.partition, message.offset, message.keyed)),
                    unfinished
                        .iter()
                        .map(|message| (message.partition, message.offset)),
                )?;
                Some(KeyAck {
                    routing_key: Arc::clone(routing_key),
                    max_offset,
                })
            },
        )
        .collect()
}

#[cfg(test)]
mod tests {
    use std::collections::VecDeque;
    use std::num::NonZeroUsize;

    use rstest::rstest;

    use super::*;
    use crate::batcher::key_queues::RunCap;
    use crate::batcher::packer::PackTargets;
    use crate::batcher::test_support::{message, offsets};
    use crate::order_sentinel::{KeyOrderSentinel, KeyOrderViolation, SendKind};
    use crate::routing::{Router, RoutingStrategy};

    const FAULT_DELAY: Duration = Duration::from_millis(200);
    const BUSY_DELAY: Duration = Duration::from_millis(20);
    const NO_WORKER_DELAY: Duration = Duration::from_millis(100);
    const STALL: Duration = Duration::from_secs(60);
    const BUDGET: Duration = Duration::from_millis(250);
    const LATENCY_BUDGET: Duration = Duration::from_secs(1);
    const SLOW_RTT: Duration = Duration::from_secs(2);

    /// Distinct delays, so a wakeup time shows which retry reason applied.
    fn retry_policy() -> RetryPolicy {
        RetryPolicy::new(FAULT_DELAY, BUSY_DELAY, NO_WORKER_DELAY).expect("valid retry policy")
    }

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
            events: NonZeroUsize::new(events),
            bytes: None,
            latency_budget: budget,
        });
        batcher_with(packer, max_requests_per_worker, now)
    }

    fn batcher_with(
        packer: Packer,
        max_requests_per_worker: usize,
        now: Instant,
    ) -> BatcherStateMachine {
        let assigner = WorkerAssigner::new(
            Router::with_seed(RoutingStrategy::P2c, 0),
            max_requests_per_worker,
        )
        .expect("valid request cap");
        BatcherStateMachine::new(packer, assigner, retry_policy(), STALL, now)
            .expect("valid stall timeout")
    }

    fn budgeted_batcher(events: usize, attempts: u32, now: Instant) -> BatcherStateMachine {
        packing_batcher(events, Duration::ZERO, 4, now).with_request_budget(Some(RequestBudget {
            soft_budget: BUDGET,
            attempts: NonZeroU32::new(attempts).expect("nonzero attempts"),
        }))
    }

    /// One worker with four slots, and a latency budget the slow settlements
    /// of these tests exceed.
    fn governed_batcher(adaptation: Adaptation, now: Instant) -> BatcherStateMachine {
        batcher(4, now)
            .with_governor(GovernorSettings {
                adaptation,
                latency_budget: Some(LATENCY_BUDGET),
                ..GovernorSettings::observing()
            })
            .expect("valid governor settings")
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

    /// Applies the effects in the order the driver does, so the sentinel judges
    /// the sends against the ACK marks of the same action.
    fn apply_to_sentinel(sentinel: &KeyOrderSentinel, effects: &Effects) -> Vec<KeyOrderViolation> {
        let mut batch = sentinel.batch();
        for ack in &effects.key_acks {
            batch.note_acked(&ack.routing_key, ack.max_offset);
        }
        for key in &effects.evicted_keys {
            batch.evict(key);
        }
        let mut violations = Vec::new();
        for send in &effects.sends {
            let kind = if send.class.replay {
                SendKind::Resend
            } else {
                SendKind::Fresh
            };
            for run in &send.runs {
                violations.extend(batch.note_sent(&run.routing_key, &run.messages, kind));
            }
        }
        violations
    }

    fn sent_messages(send: &SendRequest) -> Vec<SerializedKafkaMessage> {
        send.runs
            .iter()
            .flat_map(|run| run.messages.iter().cloned())
            .collect()
    }

    fn saturate_then_settle_slowly(
        batcher: BatcherStateMachine,
        now: Instant,
    ) -> (BatcherStateMachine, Vec<String>) {
        let workers = pool(&["w"]);
        let runs = vec![
            run("a", &[1]),
            run("b", &[2]),
            run("c", &[3]),
            run("d", &[4]),
        ];
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, runs);
        let first = effects.sends[0].request;
        let mut log = vec![format!("{effects:?}")];
        let settled_at = now + SLOW_RTT;
        let (batcher, effects) = batcher.on_request_succeeded(settled_at, &workers, first, 1);
        log.push(format!("{effects:?}"));
        let (batcher, effects) = batcher.on_groups(settled_at, &workers, 0, vec![run("e", &[5])]);
        log.push(format!("{effects:?}"));
        (batcher, log)
    }

    #[test]
    fn with_adaptation_off_the_governor_changes_no_effect_while_its_shadow_pool_moves() {
        let now = Instant::now();
        let (baseline, baseline_log) = saturate_then_settle_slowly(batcher(4, now), now);
        let (shadow, shadow_log) =
            saturate_then_settle_slowly(governed_batcher(Adaptation::Off, now), now);
        assert_eq!(baseline_log, shadow_log);

        assert_eq!(baseline.snapshot().governor.permits, 4);
        let governor = shadow.snapshot().governor;
        assert_eq!(governor.rtt, Some(SLOW_RTT));
        assert_eq!(
            (governor.permits, governor.ceiling),
            (3, 4),
            "the shadow pool shrank below the ceiling"
        );
        assert_eq!(
            governor.starved_messages, 1,
            "e went out on a free slot past the shadow pool's free permits"
        );
    }

    #[test]
    fn with_adaptation_on_free_permits_cap_the_pass_until_a_permit_returns() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let runs = vec![
            run("a", &[1]),
            run("b", &[2]),
            run("c", &[3]),
            run("d", &[4]),
        ];
        let (batcher, effects) =
            governed_batcher(Adaptation::On, now).on_groups(now, &workers, 0, runs);
        assert_eq!(effects.sends.len(), 4);
        let (a, b) = (effects.sends[0].request, effects.sends[1].request);

        let settled_at = now + SLOW_RTT;
        let (batcher, _) = batcher.on_request_succeeded(settled_at, &workers, a, 1);
        let (batcher, effects) = batcher.on_groups(settled_at, &workers, 0, vec![run("e", &[5])]);
        assert!(
            effects.sends.is_empty(),
            "a's slot is free but the pool shrank to three"
        );
        let governor = batcher.snapshot().governor;
        assert_eq!(
            (
                governor.permits,
                governor.free_permits,
                governor.starved_messages
            ),
            (3, 0, 1)
        );

        let (batcher, effects) = batcher.on_request_succeeded(settled_at, &workers, b, 1);
        assert_eq!(shape(&effects.sends[0]), vec![("e", vec![5])]);
        assert_eq!(
            batcher.snapshot().governor.starved_messages,
            0,
            "the pass that sent e left nothing waiting"
        );
    }

    #[test]
    fn a_failure_and_the_requests_sent_until_its_worker_answers_again_give_no_rtt_sample() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let (batcher, effects) = batcher(4, now).on_groups(now, &workers, 0, vec![run("a", &[1])]);
        let request = effects.sends[0].request;
        assert_eq!(batcher.snapshot().governor.free_permits, 3);

        let failed_at = now + SLOW_RTT;
        let (batcher, _) = batcher.on_request_failed(
            failed_at,
            &workers,
            request,
            FailureCause::Busy,
            vec![message("a", 0, 1)],
        );
        let governor = batcher.snapshot().governor;
        assert_eq!(governor.free_permits, 4);
        assert_eq!(governor.rtt, None, "a busy answer is no round-trip sample");

        let (batcher, effects) = batcher.on_wakeup(failed_at + BUSY_DELAY, &workers);
        let retry = effects.sends[0].request;
        let answered_at = failed_at + BUSY_DELAY + SLOW_RTT;
        let (batcher, _) = batcher.on_request_succeeded(answered_at, &workers, retry, 1);
        assert_eq!(
            batcher.snapshot().governor.rtt,
            None,
            "the retry can wait out the stream's reconnect backoff"
        );

        let rtt = Duration::from_millis(100);
        let (batcher, effects) = batcher.on_groups(answered_at, &workers, 0, vec![run("b", &[2])]);
        let next = effects.sends[0].request;
        let (batcher, _) = batcher.on_request_succeeded(answered_at + rtt, &workers, next, 1);
        assert_eq!(batcher.snapshot().governor.rtt, Some(rtt));
    }

    #[test]
    fn a_draining_workers_requests_hold_none_of_the_routable_workers_permits() {
        let now = Instant::now();
        let both = pool(&["a", "b"]);
        let runs = (1..=8).map(|n| run(&format!("k{n}"), &[n])).collect();
        let (mut batcher, effects) =
            governed_batcher(Adaptation::On, now).on_groups(now, &both, 0, runs);
        assert_eq!(effects.sends.len(), 8);
        let on_a: Vec<_> = effects
            .sends
            .iter()
            .filter(|send| send.worker == WorkerId::from("a"))
            .map(|send| send.request)
            .collect();
        assert_eq!(on_a.len(), 4);

        let only_a = pool(&["a"]);
        for request in on_a {
            let effects;
            (batcher, effects) = batcher.on_request_succeeded(now, &only_a, request, 1);
            assert!(effects.sends.is_empty());
        }
        let governor = batcher.snapshot().governor;
        assert_eq!(
            (governor.ceiling, governor.free_permits),
            (4, 4),
            "b's four requests in flight hold none of a's permits"
        );

        let (_, effects) = batcher.on_groups(now, &only_a, 0, vec![run("k9", &[9])]);
        assert_eq!(shape(&effects.sends[0]), vec![("k9", vec![9])]);
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
            WorkerAssigner::new(Router::new(RoutingStrategy::P2c), 1).expect("valid cap");
        let packer = Packer::new(PackTargets {
            events: NonZeroUsize::new(1),
            bytes: None,
            latency_budget: STALL / 2 + Duration::from_millis(1),
        });
        let created =
            BatcherStateMachine::new(packer, assigner, retry_policy(), STALL, Instant::now());
        assert!(created.is_err());
    }

    #[test]
    fn a_packer_without_a_target_is_rejected() {
        let assigner =
            WorkerAssigner::new(Router::new(RoutingStrategy::P2c), 1).expect("valid cap");
        let created = BatcherStateMachine::new(
            Packer::new(PackTargets::default()),
            assigner,
            retry_policy(),
            STALL,
            Instant::now(),
        );
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
            WorkerAssigner::new(Router::new(RoutingStrategy::P2c), 1).expect("valid cap");
        let created = BatcherStateMachine::new(
            Packer::new(PackTargets {
                events: NonZeroUsize::new(1),
                ..PackTargets::default()
            }),
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
    fn a_key_with_runs_under_two_epochs_sends_them_one_at_a_time() {
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
    fn messages_below_the_target_leave_together_at_the_pack_deadline() {
        let now = Instant::now();
        let budget = Duration::from_millis(30);
        let workers = pool(&["w"]);
        let batcher = packing_batcher(100, budget, 4, now);

        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1])]);
        assert!(effects.sends.is_empty());
        assert_eq!(effects.next_wakeup, Some(now + budget));
        let (batcher, effects) =
            batcher.on_groups(now + budget / 2, &workers, 0, vec![run("b", &[2])]);
        assert!(effects.sends.is_empty());
        assert_eq!(effects.next_wakeup, Some(now + budget));

        let (_, effects) = batcher.on_wakeup(now + budget, &workers);
        assert_eq!(
            shape(&effects.sends[0]),
            vec![("a", vec![1]), ("b", vec![2])]
        );
    }

    #[test]
    fn a_saturated_pool_keeps_requests_full_instead_of_claiming_keys_early() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = packing_batcher(4, Duration::ZERO, 1, now);
        let first: Vec<_> = (0..4).map(|n| run(&format!("k{n}"), &[n])).collect();
        let (mut batcher, effects) = batcher.on_groups(now, &workers, 0, first);
        let request = effects.sends[0].request;

        for n in 4..10 {
            let effects;
            (batcher, effects) =
                batcher.on_groups(now, &workers, 0, vec![run(&format!("k{n}"), &[n])]);
            assert!(effects.sends.is_empty(), "the only slot is busy");
        }
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("k4", &[10])]);
        assert!(effects.sends.is_empty());

        let (_, effects) = batcher.on_request_succeeded(now, &workers, request, 4);
        assert_eq!(effects.sends.len(), 1);
        assert_eq!(
            shape(&effects.sends[0]),
            vec![("k4", vec![4, 10]), ("k5", vec![5]), ("k6", vec![6]),],
            "the freed slot gets a full request, and k4's later message joins its run"
        );
    }

    #[test]
    fn a_hot_keys_backlog_leaves_in_capped_runs_while_other_keys_keep_moving() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = packing_batcher(2, Duration::ZERO, 2, now);
        let (batcher, effects) = batcher.on_groups(
            now,
            &workers,
            0,
            vec![run("hot", &[1, 2, 3, 4, 5, 6]), run("other", &[10])],
        );
        assert_eq!(
            effects.sends.iter().map(shape).collect::<Vec<_>>(),
            vec![vec![("hot", vec![1, 2])], vec![("other", vec![10])]]
        );

        let (failed, messages) = (effects.sends[0].request, sent_messages(&effects.sends[0]));
        let (batcher, _) =
            batcher.on_request_failed(now, &workers, failed, FailureCause::Fault, messages);
        let retry_at = now + FAULT_DELAY;
        let (mut batcher, effects) = batcher.on_wakeup(retry_at, &workers);
        assert!(effects.sends[0].class.replay);
        assert_eq!(shape(&effects.sends[0]), vec![("hot", vec![1, 2])]);

        let mut request = effects.sends[0].request;
        for expected in [vec![3, 4], vec![5, 6]] {
            let effects;
            (batcher, effects) = batcher.on_request_succeeded(retry_at, &workers, request, 2);
            assert_eq!(shape(&effects.sends[0]), vec![("hot", expected)]);
            request = effects.sends[0].request;
        }
    }

    #[test]
    fn a_run_cap_above_the_target_sends_a_hot_keys_backlog_in_one_round_trip() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let packer = Packer::new(PackTargets {
            events: NonZeroUsize::new(2),
            bytes: None,
            latency_budget: Duration::ZERO,
        })
        .with_run_cap(RunCap {
            messages: NonZeroUsize::new(6),
            bytes: None,
        });
        let batcher = batcher_with(packer, 2, now);
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("hot", &[1])]);
        let request = effects.sends[0].request;

        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("hot", &[2, 3, 4])]);
        assert!(effects.sends.is_empty());
        let (batcher, _) = batcher.on_groups(now, &workers, 0, vec![run("hot", &[5, 6, 7, 8])]);

        let (_, effects) = batcher.on_request_succeeded(now, &workers, request, 1);
        assert_eq!(
            effects.sends.iter().map(shape).collect::<Vec<_>>(),
            vec![vec![("hot", vec![2, 3, 4, 5, 6, 7])]]
        );
    }

    #[test]
    fn the_pack_budget_starts_when_a_slot_frees_not_when_messages_arrive() {
        let now = Instant::now();
        let budget = Duration::from_millis(30);
        let workers = pool(&["w"]);
        let batcher = packing_batcher(2, budget, 1, now);

        let (batcher, effects) =
            batcher.on_groups(now, &workers, 0, vec![run("a", &[1]), run("b", &[2])]);
        let request = effects.sends[0].request;
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("c", &[3])]);
        assert!(effects.sends.is_empty());

        let freed = now + budget * 2;
        let (batcher, effects) = batcher.on_request_succeeded(freed, &workers, request, 2);
        assert!(effects.sends.is_empty());
        assert_eq!(effects.next_wakeup, Some(freed + budget));

        let (_, effects) = batcher.on_wakeup(freed + budget, &workers);
        assert_eq!(shape(&effects.sends[0]), vec![("c", vec![3])]);
    }

    #[test]
    fn shutdown_sends_messages_waiting_for_the_pack_deadline_at_once() {
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
    fn messages_waiting_out_the_pack_budget_do_not_trip_the_stall_check() {
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

        // A failure does not move the stall clock, so a replay that waited
        // the budget again would be due after the stall deadline.
        let failed_at = arrival + budget + Duration::from_secs(1);
        let (batcher, _) = batcher.on_request_failed(
            failed_at,
            &workers,
            effects.sends[0].request,
            FailureCause::Fault,
            vec![message("a", 0, 1)],
        );
        let (batcher, effects) = batcher.on_wakeup(failed_at + FAULT_DELAY, &workers);
        assert!(matches!(batcher, BatcherStateMachine::Running(_)));
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![1])]);
        assert!(effects.sends[0].class.replay);
    }

    #[test]
    fn a_revoke_of_every_message_waiting_for_the_pack_deadline_releases_the_slot() {
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
        assert_eq!(effects.next_wakeup, None);
    }

    #[test]
    fn every_offset_completes_exactly_once_across_failures_partials_retries_and_packing() {
        let now = Instant::now();
        let retry_at = now + FAULT_DELAY;
        let workers = pool(&["w1", "w2"]);
        let mut completed = Vec::new();
        let mut record = |effects: &Effects| {
            for completion in &effects.completions {
                completed.extend(completion.offsets.iter().map(|offset| offset.0));
            }
        };

        let (batcher, effects) = packing_batcher(3, Duration::ZERO, 2, now).on_groups(
            now,
            &workers,
            0,
            vec![
                run("a", &[1, 2]),
                run("b", &[3]),
                run("c", &[4]),
                run("d", &[5, 6]),
            ],
        );
        assert_eq!(
            effects.sends.iter().map(shape).collect::<Vec<_>>(),
            vec![
                vec![("a", vec![1, 2]), ("b", vec![3])],
                vec![("c", vec![4]), ("d", vec![5, 6])],
            ]
        );
        let (failed, failed_messages) =
            (effects.sends[0].request, sent_messages(&effects.sends[0]));
        let succeeded = effects.sends[1].request;

        let (batcher, _) =
            batcher.on_request_failed(now, &workers, failed, FailureCause::Fault, failed_messages);
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[7])]);
        assert!(effects.sends.is_empty(), "a is claimed by its replay");
        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, succeeded, 3);
        record(&effects);

        let (batcher, effects) = batcher.on_wakeup(retry_at, &workers);
        assert!(effects.sends[0].class.replay);
        assert_eq!(
            shape(&effects.sends[0]),
            vec![("a", vec![1, 2]), ("b", vec![3])]
        );
        let replay = effects.sends[0].request;
        let (batcher, effects) =
            batcher.on_request_partial(retry_at, &workers, replay, 2, vec![message("a", 0, 1)]);
        record(&effects);
        assert!(effects.sends[0].class.replay);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![1])]);
        let resend = effects.sends[0].request;
        let (batcher, effects) = batcher.on_request_succeeded(retry_at, &workers, resend, 1);
        record(&effects);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![7])]);
        let last = effects.sends[0].request;
        let (batcher, effects) = batcher.on_request_succeeded(retry_at, &workers, last, 1);
        record(&effects);

        completed.sort_unstable();
        assert_eq!(completed, vec![1, 2, 3, 4, 5, 6, 7]);
        assert_eq!(batcher.pending_messages(), 0);
        assert_eq!(batcher.in_flight_messages(), 0);
    }

    #[test]
    fn a_worker_accepting_fewer_messages_than_sent_fails_the_state_machine() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = packing_batcher(4, Duration::ZERO, 4, now);
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[1, 2])]);
        let request = effects.sends[0].request;

        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, request, 1);
        assert!(matches!(batcher, BatcherStateMachine::Failed));
        assert!(effects.fatal.is_some());
    }

    #[test]
    fn an_accepted_request_completes_each_partition_and_acks_keyed_messages_on_the_first_partition()
    {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let batcher = packing_batcher(2, Duration::ZERO, 4, now);
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
                max_offset: 1
            }]
        );

        let (_, effects) = batcher.on_request_succeeded(now, &workers, unkeyed_request, 1);
        assert_eq!(effects.completions[0].offsets, vec![Offset(5)]);
        assert!(effects.key_acks.is_empty());
    }

    #[test]
    fn a_partial_leaving_a_keys_first_partition_unfinished_resends_it_without_a_violation() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let sentinel = KeyOrderSentinel::new();
        let run = KeyRun {
            routing_key: "a".into(),
            messages: vec![message("a", 0, 10), message("a", 1, 100)],
        };
        let (batcher, effects) =
            packing_batcher(2, Duration::ZERO, 4, now).on_groups(now, &workers, 0, vec![run]);
        assert!(apply_to_sentinel(&sentinel, &effects).is_empty());
        let request = effects.sends[0].request;

        let (_, effects) =
            batcher.on_request_partial(now, &workers, request, 1, vec![message("a", 0, 10)]);
        assert_eq!(effects.completions[0].offsets, vec![Offset(100)]);
        assert!(
            effects.key_acks.is_empty(),
            "partition 1's offset is no mark for partition 0"
        );
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![10])]);
        assert!(apply_to_sentinel(&sentinel, &effects).is_empty());
    }

    #[test]
    fn a_failed_run_spanning_a_revoked_partition_replays_only_the_kept_partition_in_order() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let spanning = KeyRun {
            routing_key: "a".into(),
            messages: vec![message("a", 0, 1), message("a", 1, 7)],
        };
        let (batcher, effects) =
            packing_batcher(4, Duration::ZERO, 4, now).on_groups(now, &workers, 0, vec![spanning]);
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
        let (batcher, effects) = packing_batcher(4, Duration::ZERO, 4, now).on_groups(
            now,
            &workers,
            1,
            vec![run("a", &[1, 2])],
        );
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

    /// Key `a` holds offsets 1 to 3 and key `b` offset 4. The ack for `a`
    /// stops below its lowest unfinished offset, and a key with nothing
    /// finished gets no ack.
    #[rstest]
    #[case::a_middle_message_of_a_shared_key(&[2], &[1, 3, 4], Some(1))]
    #[case::the_tail_of_a_key(&[2, 3], &[1, 4], Some(1))]
    #[case::a_whole_key(&[1, 2, 3], &[4], None)]
    fn a_partial_completes_the_accepted_offsets_and_requeues_the_unfinished_ones_at_the_front(
        #[case] unfinished: &[i64],
        #[case] completed: &[i64],
        #[case] ack_for_a: Option<i64>,
    ) {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let sentinel = KeyOrderSentinel::new();
        let (batcher, effects) = packing_batcher(4, Duration::ZERO, 4, now).on_groups(
            now,
            &workers,
            0,
            vec![run("a", &[1, 2, 3]), run("b", &[4])],
        );
        assert_eq!(
            shape(&effects.sends[0]),
            vec![("a", vec![1, 2, 3]), ("b", vec![4])]
        );
        assert!(apply_to_sentinel(&sentinel, &effects).is_empty());
        let request = effects.sends[0].request;
        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("a", &[5])]);
        assert!(effects.sends.is_empty(), "a's run is in flight");

        let accepted = 4 - unfinished.len() as u32;
        let unfinished_messages = unfinished
            .iter()
            .map(|&offset| message("a", 0, offset))
            .collect();
        let (batcher, effects) =
            batcher.on_request_partial(now, &workers, request, accepted, unfinished_messages);
        assert_eq!(
            effects.completions[0].offsets,
            completed
                .iter()
                .map(|&offset| Offset(offset))
                .collect::<Vec<_>>()
        );
        let mut expected_acks = Vec::new();
        if let Some(max_offset) = ack_for_a {
            expected_acks.push(KeyAck {
                routing_key: "a".into(),
                max_offset,
            });
        }
        expected_acks.push(KeyAck {
            routing_key: "b".into(),
            max_offset: 4,
        });
        assert_eq!(effects.key_acks, expected_acks);
        assert_eq!(effects.evicted_keys, vec![Arc::<str>::from("b")]);
        assert_eq!(
            effects.sends.len(),
            1,
            "a's fresh message waits for the replay"
        );
        assert!(effects.sends[0].class.replay);
        assert_eq!(shape(&effects.sends[0]), vec![("a", unfinished.to_vec())]);
        let violations = apply_to_sentinel(&sentinel, &effects);
        assert!(
            violations.is_empty(),
            "the ACK mark stops before the unfinished message, so its resend is legal: \
             {violations:?}"
        );
        let replay = effects.sends[0].request;

        let (_, effects) =
            batcher.on_request_succeeded(now, &workers, replay, unfinished.len() as u32);
        assert_eq!(
            effects.completions[0].offsets,
            unfinished
                .iter()
                .map(|&offset| Offset(offset))
                .collect::<Vec<_>>()
        );
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![5])]);
        let violations = apply_to_sentinel(&sentinel, &effects);
        assert!(
            violations.is_empty(),
            "the fresh send after the resend is legal: {violations:?}"
        );
    }

    #[test]
    fn a_partial_that_does_not_match_the_request_fails_the_state_machine() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let (batcher, effects) = batcher(4, now).on_groups(now, &workers, 0, vec![run("a", &[1])]);
        let request = effects.sends[0].request;

        let (batcher, effects) =
            batcher.on_request_partial(now, &workers, request, 0, vec![message("a", 0, 2)]);
        assert!(matches!(batcher, BatcherStateMachine::Failed));
        assert!(effects.fatal.is_some());
    }

    #[test]
    fn partials_that_accept_nothing_do_not_hold_off_the_watchdog() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let (batcher, effects) = batcher(4, now).on_groups(now, &workers, 0, vec![run("a", &[1])]);
        let request = effects.sends[0].request;

        let (batcher, effects) = batcher.on_request_partial(
            now + STALL / 2,
            &workers,
            request,
            0,
            vec![message("a", 0, 1)],
        );
        assert!(effects.fatal.is_none());
        let resend = effects.sends[0].request;
        let (batcher, effects) =
            batcher.on_request_partial(now + STALL, &workers, resend, 0, vec![message("a", 0, 1)]);
        assert!(matches!(batcher, BatcherStateMachine::Failed));
        assert!(effects.fatal.is_some());
    }

    #[test]
    fn a_key_that_keeps_running_out_of_budget_resends_alone_without_one() {
        let now = Instant::now();
        let retry_at = now + FAULT_DELAY;
        let workers = pool(&["w"]);
        let (batcher, effects) =
            budgeted_batcher(4, 2, now).on_groups(now, &workers, 0, vec![run("a", &[1, 2, 3])]);
        let first = effects.sends[0].request;
        let (batcher, effects) = batcher.on_request_partial(
            now,
            &workers,
            first,
            1,
            vec![message("a", 0, 2), message("a", 0, 3)],
        );
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![2, 3])]);
        assert_eq!(effects.sends[0].soft_budget, Some(BUDGET));
        let second = effects.sends[0].request;
        let (batcher, effects) =
            batcher.on_request_partial(now, &workers, second, 1, vec![message("a", 0, 3)]);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![3])]);
        assert_eq!(effects.sends[0].soft_budget, None);
        assert!(effects.sends[0].class.unbudgeted);
        let escalated = effects.sends[0].request;

        let (batcher, effects) = batcher.on_groups(now, &workers, 0, vec![run("b", &[4])]);
        let budgeted = effects.sends[0].request;
        let (batcher, _) = batcher.on_request_failed(
            now,
            &workers,
            escalated,
            FailureCause::Fault,
            vec![message("a", 0, 3)],
        );
        let (batcher, _) = batcher.on_request_failed(
            now,
            &workers,
            budgeted,
            FailureCause::Fault,
            vec![message("b", 0, 4)],
        );

        let (_, effects) = batcher.on_wakeup(retry_at, &workers);
        let sends: Vec<_> = effects
            .sends
            .iter()
            .map(|send| (shape(send), send.soft_budget))
            .collect();
        assert_eq!(
            sends,
            vec![
                (vec![("a", vec![3])], None),
                (vec![("b", vec![4])], Some(BUDGET)),
            ],
            "a failure keeps the escalation, the escalated replay goes first, and a budgeted \
             replay never rides along"
        );
    }

    #[test]
    fn a_partial_that_finished_nothing_resends_without_a_budget_at_once() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let (batcher, effects) =
            budgeted_batcher(4, 3, now).on_groups(now, &workers, 0, vec![run("a", &[1, 2])]);
        let request = effects.sends[0].request;

        let (_, effects) = batcher.on_request_partial(
            now,
            &workers,
            request,
            0,
            vec![message("a", 0, 1), message("a", 0, 2)],
        );
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![1, 2])]);
        assert_eq!(effects.sends[0].soft_budget, None);
        assert!(effects.sends[0].class.unbudgeted);
    }

    #[test]
    fn a_finished_run_resets_the_escalation_count() {
        let now = Instant::now();
        let workers = pool(&["w"]);
        let (batcher, effects) =
            budgeted_batcher(4, 2, now).on_groups(now, &workers, 0, vec![run("a", &[1, 2])]);
        let first = effects.sends[0].request;
        let (batcher, _) = batcher.on_groups(now, &workers, 0, vec![run("a", &[3, 4])]);
        let (batcher, effects) =
            batcher.on_request_partial(now, &workers, first, 1, vec![message("a", 0, 2)]);
        let resend = effects.sends[0].request;
        let (batcher, effects) = batcher.on_request_succeeded(now, &workers, resend, 1);
        assert_eq!(shape(&effects.sends[0]), vec![("a", vec![3, 4])]);
        let next = effects.sends[0].request;

        let (_, effects) =
            batcher.on_request_partial(now, &workers, next, 1, vec![message("a", 0, 4)]);
        assert_eq!(
            effects.sends[0].soft_budget,
            Some(BUDGET),
            "the earlier unfinished attempt no longer counts"
        );
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
