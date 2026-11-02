//! Synchronization helpers: `ResettableSignal` (port of `resettable-signal.ts`) and
//! `FifoLimiter` (the `p-limit` semantics the Node stages rely on).

use std::collections::VecDeque;
use std::future::Future;
use std::sync::{Arc, Mutex};

use tokio::sync::{oneshot, watch};

/// A one-shot wake-up that can be re-armed. A `resolve()` that arrives after `reset()` and
/// before `wait()` is not lost.
pub struct ResettableSignal {
    tx: watch::Sender<u64>,
    baseline: Mutex<u64>,
}

impl Default for ResettableSignal {
    fn default() -> Self {
        let (tx, _) = watch::channel(0);
        Self {
            tx,
            baseline: Mutex::new(0),
        }
    }
}

impl ResettableSignal {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn resolve(&self) {
        self.tx.send_modify(|generation| *generation += 1);
    }

    pub fn reset(&self) {
        *self.baseline.lock().unwrap() = *self.tx.borrow();
    }

    pub fn wait(&self) -> impl Future<Output = ()> + Send + 'static {
        let baseline = *self.baseline.lock().unwrap();
        let mut rx = self.tx.subscribe();
        async move {
            let _ = rx.wait_for(|generation| *generation != baseline).await;
        }
    }
}

/// A concurrency cap with FIFO admission, like `p-limit`. A caller takes its place in the
/// queue when it calls `acquire()`, not when it first polls the returned future, so the
/// admission order is the call order.
pub struct FifoLimiter {
    max: usize,
    state: Mutex<LimiterState>,
}

struct LimiterState {
    running: usize,
    waiters: VecDeque<oneshot::Sender<LimiterPermit>>,
}

/// A held slot. The slot is a value from the moment `acquire()` reserves it, so a dropped
/// `acquire()` future, or a dropped permit in transit to a waiter, releases it.
pub struct LimiterPermit {
    limiter: Option<Arc<FifoLimiter>>,
}

impl FifoLimiter {
    /// # Panics
    ///
    /// Panics when `max` is 0, as `pLimit(0)` throws when the Node pipeline is built.
    pub fn new(max: usize) -> Arc<Self> {
        assert!(
            max > 0,
            "Expected `concurrency` to be a number from 1 and up"
        );
        Arc::new(Self {
            max,
            state: Mutex::new(LimiterState {
                running: 0,
                waiters: VecDeque::new(),
            }),
        })
    }

    pub fn acquire(self: &Arc<Self>) -> impl Future<Output = LimiterPermit> + Send + 'static {
        enum Reserved {
            Now(LimiterPermit),
            Queued(oneshot::Receiver<LimiterPermit>),
        }
        let reserved = {
            let mut state = self.state.lock().unwrap();
            if state.running < self.max && state.waiters.is_empty() {
                state.running += 1;
                Reserved::Now(LimiterPermit {
                    limiter: Some(self.clone()),
                })
            } else {
                let (tx, rx) = oneshot::channel();
                state.waiters.push_back(tx);
                Reserved::Queued(rx)
            }
        };
        async move {
            match reserved {
                Reserved::Now(permit) => permit,
                // Every queued sender gets a send, so this receive does not fail.
                Reserved::Queued(rx) => rx.await.unwrap_or(LimiterPermit { limiter: None }),
            }
        }
    }

    fn release(self: &Arc<Self>) {
        loop {
            let waiter = {
                let mut state = self.state.lock().unwrap();
                match state.waiters.pop_front() {
                    Some(waiter) => waiter,
                    None => {
                        state.running -= 1;
                        return;
                    }
                }
            };
            // The slot moves to the next waiter. A waiter that is gone hands it back.
            match waiter.send(LimiterPermit {
                limiter: Some(self.clone()),
            }) {
                Ok(()) => return,
                Err(mut permit) => {
                    permit.limiter = None;
                }
            }
        }
    }
}

impl Drop for LimiterPermit {
    fn drop(&mut self) {
        if let Some(limiter) = self.limiter.take() {
            limiter.release();
        }
    }
}
