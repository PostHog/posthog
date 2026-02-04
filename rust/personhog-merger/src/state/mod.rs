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

/// Data available at the Started step - the initial request parameters.
#[derive(Debug, Clone, PartialEq)]
pub struct StartedData {
    pub merge_id: String,
    pub target_distinct_id: String,
    pub source_distinct_ids: Vec<String>,
    pub version: i64,
}

impl StartedData {
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

/// Data available after target is marked - we now know the target person UUID.
#[derive(Debug, Clone, PartialEq)]
pub struct TargetMarkedData {
    pub started: StartedData,
    pub target_person_uuid: String,
}

/// Data available after sources are marked - we know which sources are valid.
#[derive(Debug, Clone, PartialEq)]
pub struct SourcesMarkedData {
    pub target_marked: TargetMarkedData,
    /// Mapping of successfully marked source distinct IDs to their person UUIDs.
    pub valid_sources: HashMap<String, String>,
    /// Deduplicated list of source person UUIDs to be merged.
    pub source_person_uuids: Vec<String>,
}

/// State of a merge operation as a union type.
/// Each variant carries only the fields relevant to that step.
#[derive(Debug, Clone, PartialEq)]
pub enum MergeState {
    Started(StartedData),
    TargetMarked(TargetMarkedData),
    SourcesMarked(SourcesMarkedData),
    PropertiesMerged(SourcesMarkedData),
    DistinctIdsMerged(SourcesMarkedData),
    TargetCleared(SourcesMarkedData),
    Completed(SourcesMarkedData),
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
        MergeState::Started(StartedData {
            merge_id,
            target_distinct_id,
            source_distinct_ids,
            version,
        })
    }

    /// Get the merge ID for this state.
    pub fn merge_id(&self) -> &str {
        match self {
            MergeState::Started(d) => &d.merge_id,
            MergeState::TargetMarked(d) => &d.started.merge_id,
            MergeState::SourcesMarked(d)
            | MergeState::PropertiesMerged(d)
            | MergeState::DistinctIdsMerged(d)
            | MergeState::TargetCleared(d)
            | MergeState::Completed(d) => &d.target_marked.started.merge_id,
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
            MergeState::Started(d) => d.version,
            MergeState::TargetMarked(d) => d.started.version,
            MergeState::SourcesMarked(d)
            | MergeState::PropertiesMerged(d)
            | MergeState::DistinctIdsMerged(d)
            | MergeState::TargetCleared(d)
            | MergeState::Completed(d) => d.target_marked.started.version,
            MergeState::Failed { .. } => 0, // Failed states don't need version
        }
    }

    /// Get the target distinct ID.
    pub fn target_distinct_id(&self) -> Option<&str> {
        match self {
            MergeState::Started(d) => Some(&d.target_distinct_id),
            MergeState::TargetMarked(d) => Some(&d.started.target_distinct_id),
            MergeState::SourcesMarked(d)
            | MergeState::PropertiesMerged(d)
            | MergeState::DistinctIdsMerged(d)
            | MergeState::TargetCleared(d)
            | MergeState::Completed(d) => Some(&d.target_marked.started.target_distinct_id),
            MergeState::Failed { .. } => None,
        }
    }

    /// Get the source distinct IDs.
    pub fn source_distinct_ids(&self) -> Option<&[String]> {
        match self {
            MergeState::Started(d) => Some(&d.source_distinct_ids),
            MergeState::TargetMarked(d) => Some(&d.started.source_distinct_ids),
            MergeState::SourcesMarked(d)
            | MergeState::PropertiesMerged(d)
            | MergeState::DistinctIdsMerged(d)
            | MergeState::TargetCleared(d)
            | MergeState::Completed(d) => Some(&d.target_marked.started.source_distinct_ids),
            MergeState::Failed { .. } => None,
        }
    }

    /// Get the target person UUID (only available after TargetMarked step).
    pub fn target_person_uuid(&self) -> Option<&str> {
        match self {
            MergeState::Started(_) => None,
            MergeState::TargetMarked(d) => Some(&d.target_person_uuid),
            MergeState::SourcesMarked(d)
            | MergeState::PropertiesMerged(d)
            | MergeState::DistinctIdsMerged(d)
            | MergeState::TargetCleared(d)
            | MergeState::Completed(d) => Some(&d.target_marked.target_person_uuid),
            MergeState::Failed { .. } => None,
        }
    }

    /// Get the valid source distinct IDs (only available after SourcesMarked step).
    pub fn valid_source_distinct_ids(&self) -> Vec<String> {
        match self {
            MergeState::Started(_) | MergeState::TargetMarked(_) | MergeState::Failed { .. } => {
                Vec::new()
            }
            MergeState::SourcesMarked(d)
            | MergeState::PropertiesMerged(d)
            | MergeState::DistinctIdsMerged(d)
            | MergeState::TargetCleared(d)
            | MergeState::Completed(d) => d.valid_sources.keys().cloned().collect(),
        }
    }

    /// Get the source person UUIDs (only available after SourcesMarked step).
    pub fn source_person_uuids(&self) -> Option<&[String]> {
        match self {
            MergeState::Started(_) | MergeState::TargetMarked(_) | MergeState::Failed { .. } => None,
            MergeState::SourcesMarked(d)
            | MergeState::PropertiesMerged(d)
            | MergeState::DistinctIdsMerged(d)
            | MergeState::TargetCleared(d)
            | MergeState::Completed(d) => Some(&d.source_person_uuids),
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
        let started_data = StartedData {
            merge_id: "merge-1".to_string(),
            target_distinct_id: "target-did".to_string(),
            source_distinct_ids: vec!["source-did".to_string()],
            version: 1000,
        };
        let updated_state = MergeState::TargetMarked(TargetMarkedData {
            started: started_data,
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
        let completed = MergeState::Completed(SourcesMarkedData {
            target_marked: TargetMarkedData {
                started: StartedData {
                    merge_id: "merge-2".to_string(),
                    target_distinct_id: "target-2".to_string(),
                    source_distinct_ids: vec!["source-2".to_string()],
                    version: 2000,
                },
                target_person_uuid: "uuid-2".to_string(),
            },
            valid_sources: HashMap::new(),
            source_person_uuids: Vec::new(),
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
