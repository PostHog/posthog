use async_trait::async_trait;
use std::collections::HashMap;
use std::sync::Mutex;

use crate::types::ApiResult;

#[cfg(test)]
pub mod breakpointed;

/// Represents the current step in the merge process.
/// This is a separate enum from MergeState to allow matching on the step without the data,
/// useful for breakpoints and logging.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MergeStep {
    Started,
    TargetMarked,
    SourcesMarked,
    PropertiesMerged,
    DistinctIdsMerged,
    TargetCleared,
    Completed,
    Failed,
}

/// State: merge has started with initial request parameters.
#[derive(Debug, Clone, PartialEq)]
pub struct StartedState {
    pub merge_id: String,
    pub target_distinct_id: String,
    pub source_distinct_ids: Vec<String>,
    pub version: i64,
}

impl StartedState {
    pub fn new(
        merge_id: String,
        target_distinct_id: String,
        source_distinct_ids: Vec<String>,
        version: i64,
    ) -> Self {
        Self {
            merge_id,
            target_distinct_id,
            source_distinct_ids,
            version,
        }
    }
}

/// State: target has been marked for merging.
#[derive(Debug, Clone, PartialEq)]
pub struct TargetMarkedState {
    pub started: StartedState,
    pub target_person_uuid: String,
}

/// State: sources have been marked, ready to merge properties.
#[derive(Debug, Clone, PartialEq)]
pub struct SourcesMarkedState {
    pub merge_id: String,
    pub target_distinct_id: String,
    pub source_distinct_ids: Vec<String>,
    pub version: i64,
    pub target_person_uuid: String,
    pub valid_sources: HashMap<String, String>,
    pub source_person_uuids: Vec<String>,
    pub conflicts: Vec<crate::types::MergeConflict>,
}

/// State: properties have been merged, ready to update distinct IDs.
#[derive(Debug, Clone, PartialEq)]
pub struct PropertiesMergedState {
    pub merge_id: String,
    pub target_distinct_id: String,
    pub source_distinct_ids: Vec<String>,
    pub version: i64,
    pub target_person_uuid: String,
    pub valid_sources: HashMap<String, String>,
    pub source_person_uuids: Vec<String>,
    pub conflicts: Vec<crate::types::MergeConflict>,
}

/// State: distinct IDs have been updated, ready to clear target.
#[derive(Debug, Clone, PartialEq)]
pub struct DistinctIdsMergedState {
    pub merge_id: String,
    pub target_distinct_id: String,
    pub source_distinct_ids: Vec<String>,
    pub version: i64,
    pub target_person_uuid: String,
    pub valid_sources: HashMap<String, String>,
    pub source_person_uuids: Vec<String>,
    pub conflicts: Vec<crate::types::MergeConflict>,
}

/// State: target has been cleared, ready to delete source persons.
#[derive(Debug, Clone, PartialEq)]
pub struct TargetClearedState {
    pub merge_id: String,
    pub target_distinct_id: String,
    pub source_distinct_ids: Vec<String>,
    pub version: i64,
    pub target_person_uuid: String,
    pub valid_sources: HashMap<String, String>,
    pub source_person_uuids: Vec<String>,
    pub conflicts: Vec<crate::types::MergeConflict>,
}

/// State: merge completed successfully.
#[derive(Debug, Clone, PartialEq)]
pub struct CompletedState {
    pub merge_id: String,
    pub target_distinct_id: String,
    pub source_distinct_ids: Vec<String>,
    pub version: i64,
    pub target_person_uuid: String,
    pub valid_sources: HashMap<String, String>,
    pub source_person_uuids: Vec<String>,
    pub conflicts: Vec<crate::types::MergeConflict>,
}

/// State of a merge operation as a union type.
/// Each variant carries only the fields relevant to that step.
#[derive(Debug, Clone, PartialEq)]
pub enum MergeState {
    Started(StartedState),
    TargetMarked(TargetMarkedState),
    SourcesMarked(SourcesMarkedState),
    PropertiesMerged(PropertiesMergedState),
    DistinctIdsMerged(DistinctIdsMergedState),
    TargetCleared(TargetClearedState),
    Completed(CompletedState),
    Failed { merge_id: String, error: String },
}

impl MergeState {
    /// Create a new merge state in the Started step.
    pub fn new(
        merge_id: String,
        target_distinct_id: String,
        source_distinct_ids: Vec<String>,
        version: i64,
    ) -> Self {
        MergeState::Started(StartedState {
            merge_id,
            target_distinct_id,
            source_distinct_ids,
            version,
        })
    }

    /// Get the merge ID for this state.
    pub fn merge_id(&self) -> &str {
        match self {
            MergeState::Started(s) => &s.merge_id,
            MergeState::TargetMarked(s) => &s.started.merge_id,
            MergeState::SourcesMarked(s) => &s.merge_id,
            MergeState::PropertiesMerged(s) => &s.merge_id,
            MergeState::DistinctIdsMerged(s) => &s.merge_id,
            MergeState::TargetCleared(s) => &s.merge_id,
            MergeState::Completed(s) => &s.merge_id,
            MergeState::Failed { merge_id, .. } => merge_id,
        }
    }

    /// Get the current step as a MergeStep enum.
    pub fn step(&self) -> MergeStep {
        match self {
            MergeState::Started(_) => MergeStep::Started,
            MergeState::TargetMarked(_) => MergeStep::TargetMarked,
            MergeState::SourcesMarked(_) => MergeStep::SourcesMarked,
            MergeState::PropertiesMerged(_) => MergeStep::PropertiesMerged,
            MergeState::DistinctIdsMerged(_) => MergeStep::DistinctIdsMerged,
            MergeState::TargetCleared(_) => MergeStep::TargetCleared,
            MergeState::Completed(_) => MergeStep::Completed,
            MergeState::Failed { .. } => MergeStep::Failed,
        }
    }

    /// Get the version number for this merge operation.
    pub fn version(&self) -> i64 {
        match self {
            MergeState::Started(s) => s.version,
            MergeState::TargetMarked(s) => s.started.version,
            MergeState::SourcesMarked(s) => s.version,
            MergeState::PropertiesMerged(s) => s.version,
            MergeState::DistinctIdsMerged(s) => s.version,
            MergeState::TargetCleared(s) => s.version,
            MergeState::Completed(s) => s.version,
            MergeState::Failed { .. } => 0,
        }
    }

    /// Get the target distinct ID.
    pub fn target_distinct_id(&self) -> Option<&str> {
        match self {
            MergeState::Started(s) => Some(&s.target_distinct_id),
            MergeState::TargetMarked(s) => Some(&s.started.target_distinct_id),
            MergeState::SourcesMarked(s) => Some(&s.target_distinct_id),
            MergeState::PropertiesMerged(s) => Some(&s.target_distinct_id),
            MergeState::DistinctIdsMerged(s) => Some(&s.target_distinct_id),
            MergeState::TargetCleared(s) => Some(&s.target_distinct_id),
            MergeState::Completed(s) => Some(&s.target_distinct_id),
            MergeState::Failed { .. } => None,
        }
    }

    /// Get the source distinct IDs.
    pub fn source_distinct_ids(&self) -> Option<&[String]> {
        match self {
            MergeState::Started(s) => Some(&s.source_distinct_ids),
            MergeState::TargetMarked(s) => Some(&s.started.source_distinct_ids),
            MergeState::SourcesMarked(s) => Some(&s.source_distinct_ids),
            MergeState::PropertiesMerged(s) => Some(&s.source_distinct_ids),
            MergeState::DistinctIdsMerged(s) => Some(&s.source_distinct_ids),
            MergeState::TargetCleared(s) => Some(&s.source_distinct_ids),
            MergeState::Completed(s) => Some(&s.source_distinct_ids),
            MergeState::Failed { .. } => None,
        }
    }

    /// Get the target person UUID (only available after TargetMarked step).
    pub fn target_person_uuid(&self) -> Option<&str> {
        match self {
            MergeState::Started(_) => None,
            MergeState::TargetMarked(s) => Some(&s.target_person_uuid),
            MergeState::SourcesMarked(s) => Some(&s.target_person_uuid),
            MergeState::PropertiesMerged(s) => Some(&s.target_person_uuid),
            MergeState::DistinctIdsMerged(s) => Some(&s.target_person_uuid),
            MergeState::TargetCleared(s) => Some(&s.target_person_uuid),
            MergeState::Completed(s) => Some(&s.target_person_uuid),
            MergeState::Failed { .. } => None,
        }
    }

    /// Get the valid source distinct IDs (only available after SourcesMarked step).
    pub fn valid_source_distinct_ids(&self) -> Vec<String> {
        match self {
            MergeState::Started(_) | MergeState::TargetMarked(_) | MergeState::Failed { .. } => {
                Vec::new()
            }
            MergeState::SourcesMarked(s) => s.valid_sources.keys().cloned().collect(),
            MergeState::PropertiesMerged(s) => s.valid_sources.keys().cloned().collect(),
            MergeState::DistinctIdsMerged(s) => s.valid_sources.keys().cloned().collect(),
            MergeState::TargetCleared(s) => s.valid_sources.keys().cloned().collect(),
            MergeState::Completed(s) => s.valid_sources.keys().cloned().collect(),
        }
    }

    /// Get the source person UUIDs (only available after SourcesMarked step).
    pub fn source_person_uuids(&self) -> Option<&[String]> {
        match self {
            MergeState::Started(_) | MergeState::TargetMarked(_) | MergeState::Failed { .. } => {
                None
            }
            MergeState::SourcesMarked(s) => Some(&s.source_person_uuids),
            MergeState::PropertiesMerged(s) => Some(&s.source_person_uuids),
            MergeState::DistinctIdsMerged(s) => Some(&s.source_person_uuids),
            MergeState::TargetCleared(s) => Some(&s.source_person_uuids),
            MergeState::Completed(s) => Some(&s.source_person_uuids),
        }
    }

    /// Check if this state is a terminal state (Completed or Failed).
    pub fn is_terminal(&self) -> bool {
        matches!(self, MergeState::Completed(_) | MergeState::Failed { .. })
    }
}

/// Repository for storing merge state.
#[async_trait]
pub trait MergeStateRepository: Send + Sync {
    /// Get the merge state by its ID.
    async fn get(&self, merge_id: &str) -> ApiResult<Option<MergeState>>;

    /// Set the merge state.
    async fn set(&self, state: MergeState) -> ApiResult<()>;

    /// Delete the merge state by its ID.
    async fn delete(&self, merge_id: &str) -> ApiResult<()>;

    /// List all merge states that are not completed (for resumption).
    async fn list_incomplete(&self) -> ApiResult<Vec<MergeState>>;
}

/// In-memory implementation of MergeStateRepository for testing.
pub struct InMemoryMergeStateRepository {
    states: Mutex<HashMap<String, MergeState>>,
}

impl InMemoryMergeStateRepository {
    pub fn new() -> Self {
        Self {
            states: Mutex::new(HashMap::new()),
        }
    }

    pub fn get_all_states(&self) -> HashMap<String, MergeState> {
        self.states.lock().unwrap().clone()
    }
}

impl Default for InMemoryMergeStateRepository {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl MergeStateRepository for InMemoryMergeStateRepository {
    async fn get(&self, merge_id: &str) -> ApiResult<Option<MergeState>> {
        Ok(self.states.lock().unwrap().get(merge_id).cloned())
    }

    async fn set(&self, state: MergeState) -> ApiResult<()> {
        self.states
            .lock()
            .unwrap()
            .insert(state.merge_id().to_string(), state);
        Ok(())
    }

    async fn delete(&self, merge_id: &str) -> ApiResult<()> {
        self.states.lock().unwrap().remove(merge_id);
        Ok(())
    }

    async fn list_incomplete(&self) -> ApiResult<Vec<MergeState>> {
        Ok(self
            .states
            .lock()
            .unwrap()
            .values()
            .filter(|s| !s.is_terminal())
            .cloned()
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_in_memory_repository_basic_operations() {
        let repo = InMemoryMergeStateRepository::new();

        // Initially empty
        let state = repo.get("merge-1").await.unwrap();
        assert!(state.is_none());

        // Set state
        let merge_state = MergeState::new(
            "merge-1".to_string(),
            "target-did".to_string(),
            vec!["source-did".to_string()],
            1000,
        );
        repo.set(merge_state.clone()).await.unwrap();

        // Get state
        let retrieved = repo.get("merge-1").await.unwrap();
        assert_eq!(retrieved, Some(merge_state));

        // Update state to TargetMarked
        let started_state = StartedState {
            merge_id: "merge-1".to_string(),
            target_distinct_id: "target-did".to_string(),
            source_distinct_ids: vec!["source-did".to_string()],
            version: 1000,
        };
        let updated_state = MergeState::TargetMarked(TargetMarkedState {
            started: started_state,
            target_person_uuid: "target-uuid".to_string(),
        });
        repo.set(updated_state.clone()).await.unwrap();

        let retrieved = repo.get("merge-1").await.unwrap();
        assert_eq!(retrieved.unwrap().step(), MergeStep::TargetMarked);

        // Delete state
        repo.delete("merge-1").await.unwrap();
        let state = repo.get("merge-1").await.unwrap();
        assert!(state.is_none());
    }

    #[tokio::test]
    async fn test_in_memory_repository_multiple_states() {
        let repo = InMemoryMergeStateRepository::new();

        let state1 = MergeState::new(
            "merge-1".to_string(),
            "target-1".to_string(),
            vec!["source-1".to_string()],
            1000,
        );
        let state2 = MergeState::new(
            "merge-2".to_string(),
            "target-2".to_string(),
            vec!["source-2".to_string()],
            2000,
        );

        repo.set(state1.clone()).await.unwrap();
        repo.set(state2.clone()).await.unwrap();

        assert_eq!(repo.get("merge-1").await.unwrap(), Some(state1));
        assert_eq!(repo.get("merge-2").await.unwrap(), Some(state2));

        let all_states = repo.get_all_states();
        assert_eq!(all_states.len(), 2);
    }

    #[tokio::test]
    async fn test_list_incomplete_filters_terminal_states() {
        let repo = InMemoryMergeStateRepository::new();

        // Add a started state
        let started = MergeState::new(
            "merge-1".to_string(),
            "target-1".to_string(),
            vec!["source-1".to_string()],
            1000,
        );
        repo.set(started).await.unwrap();

        // Add a completed state
        let completed = MergeState::Completed(CompletedState {
            merge_id: "merge-2".to_string(),
            target_distinct_id: "target-2".to_string(),
            source_distinct_ids: vec!["source-2".to_string()],
            version: 2000,
            target_person_uuid: "uuid-2".to_string(),
            valid_sources: HashMap::new(),
            source_person_uuids: Vec::new(),
            conflicts: Vec::new(),
        });
        repo.set(completed).await.unwrap();

        // Add a failed state
        let failed = MergeState::Failed {
            merge_id: "merge-3".to_string(),
            error: "some error".to_string(),
        };
        repo.set(failed).await.unwrap();

        // Only the started state should be returned
        let incomplete = repo.list_incomplete().await.unwrap();
        assert_eq!(incomplete.len(), 1);
        assert_eq!(incomplete[0].merge_id(), "merge-1");
    }
}
