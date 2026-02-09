use async_trait::async_trait;
use std::collections::HashSet;
#[cfg(test)]
use std::sync::Arc;
use tokio::sync::Mutex;
#[cfg(test)]
use tokio::sync::Notify;

/// Error returned when lock acquisition fails.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LockError {
    /// Timed out waiting to acquire the lock.
    Timeout,
    /// Lock was held but has been lost (e.g., lease expired).
    LockLost,
    /// Lock is held by another process.
    AlreadyHeld,
}

impl std::fmt::Display for LockError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LockError::Timeout => write!(f, "lock acquisition timed out"),
            LockError::LockLost => write!(f, "lock was lost"),
            LockError::AlreadyHeld => write!(f, "lock is already held by another process"),
        }
    }
}

impl std::error::Error for LockError {}

/// Service for acquiring distributed locks.
#[async_trait]
pub trait LockService: Send + Sync {
    /// Acquire a lock for the given ID.
    /// Returns Ok(()) if the lock was acquired successfully.
    /// Returns Err with the reason if the lock could not be acquired.
    async fn acquire(&self, lock_id: &str) -> Result<(), LockError>;
}

/// In-memory lock service for testing.
/// Always succeeds unless configured otherwise.
pub struct InMemoryLockService {
    held_locks: Mutex<HashSet<String>>,
}

impl InMemoryLockService {
    pub fn new() -> Self {
        Self {
            held_locks: Mutex::new(HashSet::new()),
        }
    }
}

impl Default for InMemoryLockService {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl LockService for InMemoryLockService {
    async fn acquire(&self, lock_id: &str) -> Result<(), LockError> {
        let mut locks = self.held_locks.lock().await;
        locks.insert(lock_id.to_string());
        Ok(())
    }
}

/// Identifies a lock operation for breakpoints.
#[cfg(test)]
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LockOperation {
    pub lock_id: String,
}

#[cfg(test)]
impl LockOperation {
    pub fn new(lock_id: &str) -> Self {
        Self {
            lock_id: lock_id.to_string(),
        }
    }
}

/// A breakpoint that fires before a lock operation.
#[cfg(test)]
pub struct LockBreakpoint {
    pub operation: LockOperation,
    notify: Arc<Notify>,
}

#[cfg(test)]
impl LockBreakpoint {
    pub fn new(operation: LockOperation) -> Self {
        Self {
            operation,
            notify: Arc::new(Notify::new()),
        }
    }

    pub fn before_acquire(lock_id: &str) -> Self {
        Self::new(LockOperation::new(lock_id))
    }

    pub fn complete(&self) {
        self.notify.notify_one();
    }

    fn get_notify(&self) -> Arc<Notify> {
        self.notify.clone()
    }
}

/// An error to be injected for a specific lock operation.
#[cfg(test)]
pub struct InjectedLockError {
    pub operation: LockOperation,
    pub error: LockError,
}

#[cfg(test)]
impl InjectedLockError {
    pub fn new(operation: LockOperation, error: LockError) -> Self {
        Self { operation, error }
    }

    pub fn timeout(lock_id: &str) -> Self {
        Self::new(LockOperation::new(lock_id), LockError::Timeout)
    }

    pub fn lock_lost(lock_id: &str) -> Self {
        Self::new(LockOperation::new(lock_id), LockError::LockLost)
    }

    pub fn already_held(lock_id: &str) -> Self {
        Self::new(LockOperation::new(lock_id), LockError::AlreadyHeld)
    }
}

/// A lock service wrapper that pauses at breakpoints and can inject errors.
#[cfg(test)]
pub struct BreakpointedLockService<L: LockService> {
    inner: L,
    breakpoints: Arc<Mutex<Vec<LockBreakpoint>>>,
    injected_errors: Arc<Mutex<Vec<InjectedLockError>>>,
}

#[cfg(test)]
impl<L: LockService> BreakpointedLockService<L> {
    pub fn new(inner: L) -> Self {
        Self {
            inner,
            breakpoints: Arc::new(Mutex::new(Vec::new())),
            injected_errors: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub async fn add_breakpoint(&self, breakpoint: LockBreakpoint) {
        self.breakpoints.lock().await.push(breakpoint);
    }

    pub async fn inject_error(&self, error: InjectedLockError) {
        self.injected_errors.lock().await.push(error);
    }

    pub async fn complete_breakpoint(&self, operation: &LockOperation) {
        let breakpoints = self.breakpoints.lock().await;
        if let Some(bp) = breakpoints.iter().find(|bp| &bp.operation == operation) {
            bp.complete();
        }
    }

    pub async fn complete_all_breakpoints(&self) {
        let breakpoints = self.breakpoints.lock().await;
        for bp in breakpoints.iter() {
            bp.complete();
        }
    }

    async fn wait_for_breakpoint(&self, operation: &LockOperation) {
        let notify = {
            let breakpoints = self.breakpoints.lock().await;
            breakpoints
                .iter()
                .find(|bp| &bp.operation == operation)
                .map(|bp| bp.get_notify())
        };

        if let Some(notify) = notify {
            notify.notified().await;
        }
    }

    async fn check_injected_error(&self, operation: &LockOperation) -> Option<LockError> {
        let mut errors = self.injected_errors.lock().await;
        if let Some(pos) = errors.iter().position(|e| &e.operation == operation) {
            let error = errors.remove(pos);
            Some(error.error)
        } else {
            None
        }
    }
}

#[cfg(test)]
#[async_trait]
impl<L: LockService> LockService for BreakpointedLockService<L> {
    async fn acquire(&self, lock_id: &str) -> Result<(), LockError> {
        let operation = LockOperation::new(lock_id);
        self.wait_for_breakpoint(&operation).await;
        if let Some(error) = self.check_injected_error(&operation).await {
            return Err(error);
        }
        self.inner.acquire(lock_id).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::{timeout, Duration};

    #[tokio::test]
    async fn test_in_memory_lock_service_acquires_lock() {
        let service = InMemoryLockService::new();
        let result = service.acquire("test-lock").await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_breakpointed_lock_service_pauses_on_acquire() {
        let inner = InMemoryLockService::new();
        let service = Arc::new(BreakpointedLockService::new(inner));

        service
            .add_breakpoint(LockBreakpoint::before_acquire("merge-1"))
            .await;

        let service_clone = service.clone();
        let handle = tokio::spawn(async move { service_clone.acquire("merge-1").await });

        // Give the task time to reach the breakpoint
        tokio::time::sleep(Duration::from_millis(10)).await;

        // Task should still be running (blocked at breakpoint)
        assert!(!handle.is_finished());

        // Complete the breakpoint
        service
            .complete_breakpoint(&LockOperation::new("merge-1"))
            .await;

        // Task should complete
        let result = timeout(Duration::from_millis(100), handle)
            .await
            .expect("Task should complete")
            .unwrap();

        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_breakpointed_lock_service_injects_timeout_error() {
        let inner = InMemoryLockService::new();
        let service = BreakpointedLockService::new(inner);

        service
            .inject_error(InjectedLockError::timeout("merge-1"))
            .await;

        let result = service.acquire("merge-1").await;
        assert_eq!(result, Err(LockError::Timeout));
    }

    #[tokio::test]
    async fn test_breakpointed_lock_service_injects_lock_lost_error() {
        let inner = InMemoryLockService::new();
        let service = BreakpointedLockService::new(inner);

        service
            .inject_error(InjectedLockError::lock_lost("merge-1"))
            .await;

        let result = service.acquire("merge-1").await;
        assert_eq!(result, Err(LockError::LockLost));
    }

    #[tokio::test]
    async fn test_injected_error_is_one_shot() {
        let inner = InMemoryLockService::new();
        let service = BreakpointedLockService::new(inner);

        service
            .inject_error(InjectedLockError::timeout("merge-1"))
            .await;

        // First call fails
        let result = service.acquire("merge-1").await;
        assert!(result.is_err());

        // Second call succeeds (error was consumed)
        let result = service.acquire("merge-1").await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_breakpointed_lock_service_without_breakpoint_proceeds() {
        let inner = InMemoryLockService::new();
        let service = BreakpointedLockService::new(inner);

        // No breakpoints - should proceed immediately
        let result = service.acquire("merge-1").await;
        assert!(result.is_ok());
    }
}
