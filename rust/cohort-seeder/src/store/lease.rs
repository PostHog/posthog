//! The lease-heartbeat handle held alongside a claimed chunk's pure state (PostgreSQL layer).
//!
//! A background ticker renews the lease every `lease / 3`; if a renewal fences out (a competing
//! reclaim bumped the epoch), it cancels the child token and publishes a [`LeaseFailure`]. `Drop`
//! aborts the task, so releasing the handle stops the heartbeats. Depends on `domain` (the lease
//! coordinates) and the sibling store SQL.

use std::sync::{Arc, Mutex};

use metrics::counter;
use tokio::sync::Notify;
use tokio::task::{AbortHandle, JoinError, JoinHandle};
use tokio_util::sync::CancellationToken;

use crate::domain::ChunkLease;
use crate::observability::metrics::{LEASE_HEARTBEATS, LEASE_LOST};

use super::chunks::{ChunkStoreError, PgChunkStore};
use super::{Claimant, LeaseDuration};

pub struct LeaseHandle {
    cancel: CancellationToken,
    signal: LeaseFailureSignal,
    worker_abort: AbortHandle,
    supervisor: JoinHandle<()>,
}

impl LeaseHandle {
    pub(crate) fn start(
        store: PgChunkStore,
        lease: ChunkLease,
        claimant: Claimant,
        lease_duration: LeaseDuration,
    ) -> Self {
        let cancel = CancellationToken::new();
        let worker_cancel = cancel.clone();
        let worker = tokio::spawn(async move {
            let _cancel_on_exit = CancelOnDrop(worker_cancel.clone());
            let mut ticker = tokio::time::interval(lease_duration.heartbeat_interval());
            ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
            ticker.tick().await;
            loop {
                tokio::select! {
                    biased;
                    _ = worker_cancel.cancelled() => return Ok(()),
                    _ = ticker.tick() => {
                        match store.heartbeat(lease, &claimant, lease_duration).await {
                            Ok(()) => counter!(LEASE_HEARTBEATS).increment(1),
                            Err(error) => {
                                counter!(LEASE_LOST).increment(1);
                                return Err(error);
                            }
                        }
                    }
                }
            }
        });
        Self::supervise(cancel, worker)
    }

    fn supervise(
        cancel: CancellationToken,
        worker: JoinHandle<Result<(), ChunkStoreError>>,
    ) -> Self {
        let worker_abort = worker.abort_handle();
        let signal = LeaseFailureSignal::new();
        let failure_state = Arc::clone(&signal.state);
        let supervisor = tokio::spawn(async move {
            match worker.await {
                Ok(Ok(())) => {}
                Ok(Err(error)) => failure_state.publish(LeaseFailure::Heartbeat(error)),
                Err(error) => failure_state.publish(LeaseFailure::Task(error)),
            }
        });
        Self {
            cancel,
            signal,
            worker_abort,
            supervisor,
        }
    }

    /// A child token cancelled when the lease is lost; the scan/produce loops select on it to abort.
    pub fn cancellation_token(&self) -> CancellationToken {
        self.cancel.child_token()
    }

    /// Resolves once the heartbeat task loses the lease or panics.
    pub async fn failure(&self) -> LeaseFailure {
        self.signal.wait().await
    }
}

impl Drop for LeaseHandle {
    fn drop(&mut self) {
        self.cancel.cancel();
        self.worker_abort.abort();
        self.supervisor.abort();
    }
}

#[derive(Debug, thiserror::Error)]
pub enum LeaseFailure {
    #[error("lease heartbeat failed")]
    Heartbeat(#[source] ChunkStoreError),
    #[error("lease heartbeat task failed")]
    Task(#[source] JoinError),
}

struct LeaseFailureState {
    failure: Mutex<Option<LeaseFailure>>,
    notify: Notify,
}

impl LeaseFailureState {
    fn publish(&self, failure: LeaseFailure) {
        *self
            .failure
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(failure);
        self.notify.notify_one();
    }
}

struct LeaseFailureSignal {
    state: Arc<LeaseFailureState>,
}

impl LeaseFailureSignal {
    fn new() -> Self {
        Self {
            state: Arc::new(LeaseFailureState {
                failure: Mutex::new(None),
                notify: Notify::new(),
            }),
        }
    }

    async fn wait(&self) -> LeaseFailure {
        loop {
            let notified = self.state.notify.notified();
            if let Some(failure) = self
                .state
                .failure
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take()
            {
                return failure;
            }
            notified.await;
        }
    }
}

struct CancelOnDrop(CancellationToken);

impl Drop for CancelOnDrop {
    fn drop(&mut self) {
        self.0.cancel();
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    #[tokio::test]
    async fn lease_handle_surfaces_task_panics_and_cancels() {
        let cancel = CancellationToken::new();
        let worker_cancel = cancel.clone();
        let worker: JoinHandle<Result<(), ChunkStoreError>> = tokio::spawn(async move {
            let _cancel_on_exit = CancelOnDrop(worker_cancel);
            panic!("heartbeat panic")
        });
        let handle = LeaseHandle::supervise(cancel.clone(), worker);

        let failure = tokio::time::timeout(Duration::from_secs(1), handle.failure())
            .await
            .unwrap();
        assert!(matches!(failure, LeaseFailure::Task(error) if error.is_panic()));
        assert!(cancel.is_cancelled());
    }
}
