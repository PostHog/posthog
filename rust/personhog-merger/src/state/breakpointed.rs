use async_trait::async_trait;
use std::sync::Arc;
use tokio::sync::{Mutex, Notify};

use crate::state::{MergeState, MergeStateRepository, MergeStep};
use crate::types::ApiResult;

/// Identifies a specific operation on the repository.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RepositoryOperation {
    Get { merge_id: String },
    Set { merge_id: String, step: MergeStep },
    Delete { merge_id: String },
}

/// A breakpoint that fires before a repository operation.
/// Uses Notify which can be cloned and awaited without holding the lock.
pub struct OperationBreakpoint {
    pub operation: RepositoryOperation,
    notify: Arc<Notify>,
}

impl OperationBreakpoint {
    pub fn new(operation: RepositoryOperation) -> Self {
        Self {
            operation,
            notify: Arc::new(Notify::new()),
        }
    }

    pub fn before_get(merge_id: &str) -> Self {
        Self::new(RepositoryOperation::Get {
            merge_id: merge_id.to_string(),
        })
    }

    pub fn before_set(merge_id: &str, step: MergeStep) -> Self {
        Self::new(RepositoryOperation::Set {
            merge_id: merge_id.to_string(),
            step,
        })
    }

    pub fn before_delete(merge_id: &str) -> Self {
        Self::new(RepositoryOperation::Delete {
            merge_id: merge_id.to_string(),
        })
    }

    /// Complete this breakpoint, allowing waiters to proceed.
    pub fn complete(&self) {
        self.notify.notify_one();
    }

    /// Get a clone of the notify handle for waiting.
    fn get_notify(&self) -> Arc<Notify> {
        self.notify.clone()
    }
}

/// An error to be injected for a specific operation.
pub struct InjectedError {
    pub operation: RepositoryOperation,
    pub error_message: String,
}

impl InjectedError {
    pub fn new(operation: RepositoryOperation, error_message: impl Into<String>) -> Self {
        Self {
            operation,
            error_message: error_message.into(),
        }
    }

    pub fn on_get(merge_id: &str, error_message: impl Into<String>) -> Self {
        Self::new(
            RepositoryOperation::Get {
                merge_id: merge_id.to_string(),
            },
            error_message,
        )
    }

    pub fn on_set(merge_id: &str, step: MergeStep, error_message: impl Into<String>) -> Self {
        Self::new(
            RepositoryOperation::Set {
                merge_id: merge_id.to_string(),
                step,
            },
            error_message,
        )
    }

    pub fn on_delete(merge_id: &str, error_message: impl Into<String>) -> Self {
        Self::new(
            RepositoryOperation::Delete {
                merge_id: merge_id.to_string(),
            },
            error_message,
        )
    }
}

/// A repository wrapper that pauses at breakpoints and can inject errors.
/// Useful for testing race conditions, timing-dependent behavior, and failure scenarios.
pub struct BreakpointedRepository<R: MergeStateRepository> {
    inner: R,
    breakpoints: Arc<Mutex<Vec<OperationBreakpoint>>>,
    injected_errors: Arc<Mutex<Vec<InjectedError>>>,
}

impl<R: MergeStateRepository> BreakpointedRepository<R> {
    pub fn new(inner: R) -> Self {
        Self {
            inner,
            breakpoints: Arc::new(Mutex::new(Vec::new())),
            injected_errors: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Add a breakpoint that will pause execution before the matching operation.
    pub async fn add_breakpoint(&self, breakpoint: OperationBreakpoint) {
        self.breakpoints.lock().await.push(breakpoint);
    }

    /// Inject an error that will be returned when the matching operation is attempted.
    /// The error is consumed on first match (one-shot).
    pub async fn inject_error(&self, error: InjectedError) {
        self.injected_errors.lock().await.push(error);
    }

    /// Complete a breakpoint, allowing the paused operation to proceed.
    pub async fn complete_breakpoint(&self, operation: &RepositoryOperation) {
        let breakpoints = self.breakpoints.lock().await;
        if let Some(bp) = breakpoints.iter().find(|bp| &bp.operation == operation) {
            bp.complete();
        }
    }

    /// Complete all pending breakpoints.
    pub async fn complete_all_breakpoints(&self) {
        let breakpoints = self.breakpoints.lock().await;
        for bp in breakpoints.iter() {
            bp.complete();
        }
    }

    async fn wait_for_breakpoint(&self, operation: &RepositoryOperation) {
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

    /// Check for and consume an injected error for the given operation.
    async fn check_injected_error(&self, operation: &RepositoryOperation) -> Option<String> {
        let mut errors = self.injected_errors.lock().await;
        if let Some(pos) = errors.iter().position(|e| &e.operation == operation) {
            let error = errors.remove(pos);
            Some(error.error_message)
        } else {
            None
        }
    }
}

#[async_trait]
impl<R: MergeStateRepository> MergeStateRepository for BreakpointedRepository<R> {
    async fn get(&self, merge_id: &str) -> ApiResult<Option<MergeState>> {
        let operation = RepositoryOperation::Get {
            merge_id: merge_id.to_string(),
        };
        self.wait_for_breakpoint(&operation).await;
        if let Some(error_msg) = self.check_injected_error(&operation).await {
            return Err(error_msg.into());
        }
        self.inner.get(merge_id).await
    }

    async fn set(&self, state: MergeState) -> ApiResult<()> {
        let operation = RepositoryOperation::Set {
            merge_id: state.merge_id().to_string(),
            step: state.step(),
        };
        self.wait_for_breakpoint(&operation).await;
        if let Some(error_msg) = self.check_injected_error(&operation).await {
            return Err(error_msg.into());
        }
        self.inner.set(state).await
    }

    async fn delete(&self, merge_id: &str) -> ApiResult<()> {
        let operation = RepositoryOperation::Delete {
            merge_id: merge_id.to_string(),
        };
        self.wait_for_breakpoint(&operation).await;
        if let Some(error_msg) = self.check_injected_error(&operation).await {
            return Err(error_msg.into());
        }
        self.inner.delete(merge_id).await
    }

    async fn list_incomplete(&self) -> ApiResult<Vec<MergeState>> {
        self.inner.list_incomplete().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::{InMemoryMergeStateRepository, StartedState, TargetMarkedState};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tokio::time::{timeout, Duration};

    #[tokio::test]
    async fn test_breakpointed_repository_pauses_on_set() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = Arc::new(BreakpointedRepository::new(inner));

        // Add breakpoint before set with TargetMarked step
        repo.add_breakpoint(OperationBreakpoint::before_set(
            "merge-1",
            MergeStep::TargetMarked,
        ))
        .await;

        let repo_clone = repo.clone();
        let handle = tokio::spawn(async move {
            let state = MergeState::TargetMarked(TargetMarkedState {
                started: StartedState {
                    merge_id: "merge-1".to_string(),
                    target_distinct_id: "target".to_string(),
                    source_distinct_ids: vec![],
                    version: 1000,
                },
                target_person_uuid: "uuid".to_string(),
            });
            repo_clone.set(state).await.unwrap();
        });

        // Give the task time to reach the breakpoint
        tokio::time::sleep(Duration::from_millis(10)).await;

        // Task should still be running (blocked at breakpoint)
        assert!(!handle.is_finished());

        // Complete the breakpoint
        repo.complete_breakpoint(&RepositoryOperation::Set {
            merge_id: "merge-1".to_string(),
            step: MergeStep::TargetMarked,
        })
        .await;

        // Task should complete
        timeout(Duration::from_millis(100), handle)
            .await
            .expect("Task should complete")
            .unwrap();
    }

    #[tokio::test]
    async fn test_breakpointed_repository_controls_operation_order() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = Arc::new(BreakpointedRepository::new(inner));
        let order = Arc::new(Mutex::new(Vec::new()));

        // Add breakpoints for two different operations
        repo.add_breakpoint(OperationBreakpoint::before_set(
            "merge-1",
            MergeStep::Started,
        ))
        .await;
        repo.add_breakpoint(OperationBreakpoint::before_set(
            "merge-2",
            MergeStep::Started,
        ))
        .await;

        let repo1 = repo.clone();
        let order1 = order.clone();
        let task1 = tokio::spawn(async move {
            let state =
                MergeState::new("merge-1".to_string(), "target-1".to_string(), vec![], 1000);
            repo1.set(state).await.unwrap();
            order1.lock().await.push(1);
        });

        let repo2 = repo.clone();
        let order2 = order.clone();
        let task2 = tokio::spawn(async move {
            let state =
                MergeState::new("merge-2".to_string(), "target-2".to_string(), vec![], 2000);
            repo2.set(state).await.unwrap();
            order2.lock().await.push(2);
        });

        // Give tasks time to reach breakpoints
        tokio::time::sleep(Duration::from_millis(10)).await;

        // Complete task2's breakpoint first
        repo.complete_breakpoint(&RepositoryOperation::Set {
            merge_id: "merge-2".to_string(),
            step: MergeStep::Started,
        })
        .await;

        // Give task2 time to complete
        tokio::time::sleep(Duration::from_millis(10)).await;

        // Then complete task1's breakpoint
        repo.complete_breakpoint(&RepositoryOperation::Set {
            merge_id: "merge-1".to_string(),
            step: MergeStep::Started,
        })
        .await;

        // Wait for both tasks
        timeout(Duration::from_millis(100), task1)
            .await
            .expect("Task 1 should complete")
            .unwrap();
        timeout(Duration::from_millis(100), task2)
            .await
            .expect("Task 2 should complete")
            .unwrap();

        // Verify order: task2 completed before task1
        assert_eq!(*order.lock().await, vec![2, 1]);
    }

    #[tokio::test]
    async fn test_breakpointed_repository_without_breakpoint_proceeds_normally() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = BreakpointedRepository::new(inner);

        // No breakpoints added - operations should proceed immediately
        let state = MergeState::new("merge-1".to_string(), "target".to_string(), vec![], 1000);
        repo.set(state).await.unwrap();

        let retrieved = repo.get("merge-1").await.unwrap();
        assert!(retrieved.is_some());

        repo.delete("merge-1").await.unwrap();
        let retrieved = repo.get("merge-1").await.unwrap();
        assert!(retrieved.is_none());
    }

    #[tokio::test]
    async fn test_complete_all_breakpoints() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = Arc::new(BreakpointedRepository::new(inner));
        let counter = Arc::new(AtomicUsize::new(0));

        // Add multiple breakpoints
        repo.add_breakpoint(OperationBreakpoint::before_set(
            "merge-1",
            MergeStep::Started,
        ))
        .await;
        repo.add_breakpoint(OperationBreakpoint::before_set(
            "merge-2",
            MergeStep::Started,
        ))
        .await;

        let repo1 = repo.clone();
        let counter1 = counter.clone();
        let task1 = tokio::spawn(async move {
            let state =
                MergeState::new("merge-1".to_string(), "target-1".to_string(), vec![], 1000);
            repo1.set(state).await.unwrap();
            counter1.fetch_add(1, Ordering::SeqCst);
        });

        let repo2 = repo.clone();
        let counter2 = counter.clone();
        let task2 = tokio::spawn(async move {
            let state =
                MergeState::new("merge-2".to_string(), "target-2".to_string(), vec![], 2000);
            repo2.set(state).await.unwrap();
            counter2.fetch_add(1, Ordering::SeqCst);
        });

        // Give tasks time to reach breakpoints
        tokio::time::sleep(Duration::from_millis(10)).await;
        assert_eq!(counter.load(Ordering::SeqCst), 0);

        // Complete all breakpoints at once
        repo.complete_all_breakpoints().await;

        // Both tasks should complete
        timeout(Duration::from_millis(100), task1)
            .await
            .expect("Task 1 should complete")
            .unwrap();
        timeout(Duration::from_millis(100), task2)
            .await
            .expect("Task 2 should complete")
            .unwrap();

        assert_eq!(counter.load(Ordering::SeqCst), 2);
    }

    #[tokio::test]
    async fn test_injected_error_on_set() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = BreakpointedRepository::new(inner);

        // Inject an error for set operation
        repo.inject_error(InjectedError::on_set(
            "merge-1",
            MergeStep::Started,
            "network disconnection",
        ))
        .await;

        let state = MergeState::new("merge-1".to_string(), "target".to_string(), vec![], 1000);

        let result = repo.set(state).await;
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("network disconnection"));
    }

    #[tokio::test]
    async fn test_injected_error_on_get() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = BreakpointedRepository::new(inner);

        // First set a state successfully
        let state = MergeState::new("merge-1".to_string(), "target".to_string(), vec![], 1000);
        repo.set(state).await.unwrap();

        // Inject an error for get operation
        repo.inject_error(InjectedError::on_get("merge-1", "connection timeout"))
            .await;

        let result = repo.get("merge-1").await;
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("connection timeout"));

        // Error should be consumed - second get should succeed
        let result = repo.get("merge-1").await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_injected_error_on_delete() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = BreakpointedRepository::new(inner);

        // Inject an error for delete operation
        repo.inject_error(InjectedError::on_delete("merge-1", "storage unavailable"))
            .await;

        let result = repo.delete("merge-1").await;
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("storage unavailable"));
    }

    #[tokio::test]
    async fn test_injected_error_is_one_shot() {
        let inner = InMemoryMergeStateRepository::new();
        let repo = BreakpointedRepository::new(inner);

        // Inject an error
        repo.inject_error(InjectedError::on_set(
            "merge-1",
            MergeStep::Started,
            "temporary failure",
        ))
        .await;

        let state = MergeState::new("merge-1".to_string(), "target".to_string(), vec![], 1000);

        // First attempt fails
        let result = repo.set(state.clone()).await;
        assert!(result.is_err());

        // Second attempt succeeds (error was consumed)
        let result = repo.set(state).await;
        assert!(result.is_ok());
    }
}
