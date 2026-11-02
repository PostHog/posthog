//! Port of `batch-budget.ts`.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tokio::time::Instant;

/// Uses `tokio::time::Instant`, so a paused test clock controls it, as Jest fake timers
/// control `Date.now()` in Node.
#[derive(Clone, Debug)]
pub struct BatchBudget {
    inner: Arc<BudgetInner>,
}

#[derive(Debug)]
struct BudgetInner {
    soft_at: Option<Instant>,
    expired: AtomicBool,
}

impl BatchBudget {
    pub fn soft_deadline(soft_at: Instant) -> Self {
        Self {
            inner: Arc::new(BudgetInner {
                soft_at: Some(soft_at),
                expired: AtomicBool::new(false),
            }),
        }
    }

    pub fn from_now(allowance: Duration) -> Self {
        Self::soft_deadline(Instant::now() + allowance)
    }

    pub fn unlimited() -> Self {
        Self {
            inner: Arc::new(BudgetInner {
                soft_at: None,
                expired: AtomicBool::new(false),
            }),
        }
    }

    pub fn is_unlimited(&self) -> bool {
        self.inner.soft_at.is_none()
    }

    pub fn soft_at(&self) -> Option<Instant> {
        self.inner.soft_at
    }

    /// Reads the clock rather than a timer flag, so a step that holds the thread past the
    /// deadline still sees the budget as spent. The flag stays set once read as spent.
    pub fn exhausted(&self) -> bool {
        if self.inner.expired.load(Ordering::Relaxed) {
            return true;
        }
        match self.inner.soft_at {
            None => false,
            Some(at) => {
                let expired = Instant::now() >= at;
                if expired {
                    self.inner.expired.store(true, Ordering::Relaxed);
                }
                expired
            }
        }
    }
}

const MAX_TIMER_DELAY_MS: u64 = (1 << 31) - 1;

/// Port of `budgetDeadline`. Zero or an allowance above the Node timer limit means no deadline.
pub fn budget_deadline(armed_at: Instant, budget_ms: u64) -> Option<Instant> {
    if budget_ms == 0 || budget_ms > MAX_TIMER_DELAY_MS {
        None
    } else {
        Some(armed_at + Duration::from_millis(budget_ms))
    }
}
