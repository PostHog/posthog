use std::sync::{Arc, Mutex};
use std::time::Instant;

use common_kafka_consumer::{AssignmentEpoch, GroupCompletion};
use metrics::{counter, histogram};
use tokio::sync::{mpsc, Notify};
use tokio::task::JoinHandle;
use tracing::error;

use super::in_flight::RequestId;
use super::key_queues::KeyRun;
use super::machine::{BatcherState, FailureCause, MachineConfig, Send, Step};
use super::worker_pool::{WorkerPool, WorkerPoolSource};
use super::{make_batch_id, BatcherOutputs};
use crate::grpc_transport::{GrpcTransport, PendingWorkerStreamSend};
use crate::order_sentinel::{KeyOrderSentinel, SendKind};
use crate::routing::Router;
use crate::transport::SendError;
use crate::types::Accumulator;

/// Performs the steps of the batcher state machine: begins its sends,
/// awaits their responses, and fires its wakeups.
pub(super) struct MachineDriver {
    shared: Arc<Shared>,
    timer: JoinHandle<()>,
}

pub(super) struct Shared {
    /// `None` only while an action runs under the lock.
    state: Mutex<Option<BatcherState>>,
    pool_source: WorkerPoolSource,
    transport: Arc<GrpcTransport>,
    key_sentinel: Arc<KeyOrderSentinel>,
    assignment_epoch: AssignmentEpoch,
    completions: mpsc::UnboundedSender<GroupCompletion>,
    errors: mpsc::UnboundedSender<String>,
    wakeup: Mutex<Option<Instant>>,
    wakeup_changed: Notify,
}

impl MachineDriver {
    pub(super) fn new(
        config: MachineConfig,
        pool_source: WorkerPoolSource,
        transport: Arc<GrpcTransport>,
    ) -> Result<(Self, BatcherOutputs), String> {
        let router = Router::new(pool_source.strategy());
        let state = BatcherState::new(config, router, Instant::now())?;
        let (completions_tx, completions_rx) = mpsc::unbounded_channel();
        let (errors_tx, errors_rx) = mpsc::unbounded_channel();
        let shared = Arc::new(Shared {
            state: Mutex::new(Some(state)),
            assignment_epoch: transport.assignment_epoch(),
            pool_source,
            transport,
            key_sentinel: Arc::new(KeyOrderSentinel::new()),
            completions: completions_tx,
            errors: errors_tx,
            wakeup: Mutex::new(None),
            wakeup_changed: Notify::new(),
        });
        let timer = tokio::spawn(run_timer(Arc::clone(&shared)));
        Ok((
            Self { shared, timer },
            BatcherOutputs {
                completions: completions_rx,
                errors: errors_rx,
            },
        ))
    }

    pub(super) fn shared(&self) -> Arc<Shared> {
        Arc::clone(&self.shared)
    }

    pub(super) fn key_order_sentinel(&self) -> Arc<KeyOrderSentinel> {
        Arc::clone(&self.shared.key_sentinel)
    }

    pub(super) fn submit(&self, accumulator: Accumulator) -> u64 {
        let assignment_epoch = self.shared.assignment_epoch.current();
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
        let assign_start = Instant::now();
        self.shared
            .apply(|state, now, pool| state.on_groups(now, pool, assignment_epoch, runs));
        histogram!("ingestion_consumer_assign_duration_seconds")
            .record(assign_start.elapsed().as_secs_f64());
        assignment_epoch
    }

    pub(super) fn begin_shutdown(&self) {
        self.shared
            .apply(|state, now, pool| state.on_shutdown(now, pool));
    }
}

impl Drop for MachineDriver {
    fn drop(&mut self) {
        self.timer.abort();
    }
}

impl Shared {
    /// Reads the current state. The state is absent only inside an action,
    /// which holds the same lock.
    pub(super) fn read<T>(&self, read: impl FnOnce(&BatcherState) -> T) -> T {
        let guard = self.state.lock().unwrap();
        read(
            guard
                .as_ref()
                .expect("every action puts the next state back"),
        )
    }

    /// Runs on the rebalance callback, which is not a runtime task. The
    /// revoke action never sends, so nothing here needs the runtime.
    pub(super) fn purge_revoked(self: &Arc<Self>, partitions: &[(String, i32)]) {
        self.apply(|state, now, _| state.on_partitions_revoked(now, partitions));
    }

    fn apply(
        self: &Arc<Self>,
        action: impl FnOnce(BatcherState, Instant, &WorkerPool) -> (BatcherState, Step),
    ) {
        let pool = self.pool_source.pool();
        let mut guard = self.state.lock().unwrap();
        let state = guard.take().expect("every action puts the next state back");
        let (next, step) = action(state, Instant::now(), &pool);
        *guard = Some(next);
        let Step {
            sends,
            completions,
            key_acks,
            evicted_keys,
            worker_outcomes,
            idle_workers,
            fatal,
            next_wakeup,
        } = step;
        // Sentinel calls and sends begin under the lock, so they follow the
        // machine's per-key order. An ACK advances before its key is evicted.
        for ack in &key_acks {
            self.key_sentinel
                .note_acked(&ack.routing_key, ack.max_offset);
        }
        for key in &evicted_keys {
            self.key_sentinel.evict(key);
        }
        let pending: Vec<(RequestId, PendingWorkerStreamSend)> =
            sends.into_iter().map(|send| self.begin(send)).collect();
        drop(guard);

        let registry = self.pool_source.registry();
        for outcome in worker_outcomes {
            registry.record_outcome(&outcome.worker, outcome.fault);
        }
        for worker in idle_workers {
            // A draining worker with nothing in flight has finished its work,
            // so it can be removed now instead of at the drain timeout.
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
        self.set_wakeup(next_wakeup);
        for (request, pending) in pending {
            drop(tokio::spawn(await_response(
                Arc::clone(self),
                request,
                pending,
            )));
        }
    }

    fn begin(&self, send: Send) -> (RequestId, PendingWorkerStreamSend) {
        let kind = if send.class.replay {
            SendKind::Resend
        } else {
            SendKind::Fresh
        };
        let mut messages = Vec::new();
        for run in send.runs {
            self.key_sentinel
                .note_sent(&run.routing_key, &run.messages, kind);
            messages.extend(run.messages);
        }
        let pending =
            self.transport
                .begin_send(&send.worker, &make_batch_id(), messages, send.class.replay);
        (send.request, pending)
    }

    fn set_wakeup(&self, next: Option<Instant>) {
        let mut wakeup = self.wakeup.lock().unwrap();
        if *wakeup != next {
            *wakeup = next;
            self.wakeup_changed.notify_one();
        }
    }
}

async fn await_response(shared: Arc<Shared>, request: RequestId, pending: PendingWorkerStreamSend) {
    match pending.wait().await {
        Ok(accepted) => shared.apply(|state, now, pool| {
            state.on_request_succeeded(now, pool, request, accepted, Vec::new())
        }),
        Err(SendError {
            error,
            messages,
            fence_guard,
        }) => {
            // Backpressure is transient, so it does not count against the
            // worker's health.
            let cause = if error.is_backpressure() {
                FailureCause::Busy
            } else {
                FailureCause::Fault
            };
            shared.apply(|state, now, pool| {
                state.on_request_failed(now, pool, request, cause, messages)
            });
            // The worker stream fences new sends until the failed messages
            // are back in their queues, so the guard drops only now.
            drop(fence_guard);
        }
    }
}

async fn run_timer(shared: Arc<Shared>) {
    loop {
        let wakeup = *shared.wakeup.lock().unwrap();
        match wakeup {
            Some(at) => {
                tokio::select! {
                    _ = tokio::time::sleep_until(at.into()) => {
                        shared.apply(|state, now, pool| state.on_wakeup(now, pool));
                    }
                    _ = shared.wakeup_changed.notified() => {}
                }
            }
            None => shared.wakeup_changed.notified().await,
        }
    }
}
