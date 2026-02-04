use std::collections::HashSet;
use std::sync::Arc;

use crate::state::{
    MergeState, MergeStateRepository, SourcesMarkedData, StartedData, TargetMarkedData,
};
use crate::types::{
    ApiResult, DistinctIdInfo, MergeConflict, MergeResult, MergeStatus, Person,
    PersonDistinctIdsApi, PersonPropertiesApi, SetMergingSourceResult, SetMergingTargetResult,
};

#[cfg(test)]
mod tests;

/// Implements person merging with conflict detection for concurrent merge operations.
///
/// The merge process:
/// 1. Mark target as merging target
/// 2. Mark sources as merging source
/// 3. Copy properties from source persons to target
/// 4. Update distinct ID mappings
/// 5. Clear merge status on target
/// 6. Delete source persons
/// 7. Completed
pub struct PersonMergeService<S: MergeStateRepository> {
    person_properties_api: Arc<dyn PersonPropertiesApi>,
    person_distinct_ids_api: Arc<dyn PersonDistinctIdsApi>,
    state_repository: Arc<S>,
}

impl<S: MergeStateRepository> PersonMergeService<S> {
    pub fn new(
        person_properties_api: Arc<dyn PersonPropertiesApi>,
        person_distinct_ids_api: Arc<dyn PersonDistinctIdsApi>,
        state_repository: Arc<S>,
    ) -> Self {
        Self {
            person_properties_api,
            person_distinct_ids_api,
            state_repository,
        }
    }

    async fn save_state(&self, state: &MergeState) -> ApiResult<()> {
        self.state_repository.set(state.clone()).await
    }

    /// Start a new merge operation.
    ///
    /// The merge process:
    /// 1. Mark target as merging target
    /// 2. Mark sources as merging source
    /// 3. Copy properties from source persons to target
    /// 4. Update distinct ID mappings
    /// 5. Clear merge status on target
    /// 6. Delete source persons
    /// 7. Completed
    ///
    /// All merge logic is implemented in the `resume_from_*` methods. This method
    /// creates the initial state and delegates to `resume_from_started`.
    ///
    /// # Arguments
    /// * `merge_id` - Unique identifier for this merge operation, used for tracking and resumption
    /// * `target_distinct_id` - The distinct ID to merge sources into
    /// * `source_distinct_ids` - The distinct IDs to merge into the target
    /// * `version` - Version number for idempotent operations
    pub async fn merge(
        &self,
        merge_id: &str,
        target_distinct_id: &str,
        source_distinct_ids: &[String],
        version: i64,
    ) -> ApiResult<MergeResult> {
        let started_data = StartedData::new(
            merge_id.to_string(),
            target_distinct_id.to_string(),
            source_distinct_ids.to_vec(),
            version,
        );

        // Save initial state and delegate to the resume flow
        self.state_repository
            .set(MergeState::Started(started_data.clone()))
            .await?;

        self.resume_from_started(started_data).await
    }

    /// Resume all incomplete merges from the state repository concurrently.
    /// Returns a list of (merge_id, result) pairs for each resumed merge.
    pub async fn resume_all(&self) -> ApiResult<Vec<(String, ApiResult<MergeResult>)>> {
        let incomplete_states = self.state_repository.list_incomplete().await?;

        let resume_futures: Vec<_> = incomplete_states
            .into_iter()
            .map(|state| {
                let merge_id = state.merge_id().to_string();
                async move {
                    let result = self.resume_merge(state).await;
                    (merge_id, result)
                }
            })
            .collect();

        Ok(futures::future::join_all(resume_futures).await)
    }

    /// Resume a single merge from its saved state.
    /// Assumes the underlying APIs are idempotent when called with the same version.
    pub async fn resume_merge(&self, state: MergeState) -> ApiResult<MergeResult> {
        match state {
            MergeState::Started(data) => self.resume_from_started(data).await,
            MergeState::TargetMarked(data) => self.resume_from_target_marked(data).await,
            MergeState::SourcesMarked(data) => self.resume_from_sources_marked(data).await,
            MergeState::PropertiesMerged(data) => self.resume_from_properties_merged(data).await,
            MergeState::DistinctIdsMerged(data) => self.resume_from_distinct_ids_merged(data).await,
            MergeState::TargetCleared(data) => self.resume_from_target_cleared(data).await,
            MergeState::Completed(data) => {
                // Nothing to do - return current state as result
                Ok(MergeResult {
                    merged: data
                        .valid_sources
                        .keys()
                        .map(|distinct_id| DistinctIdInfo {
                            distinct_id: distinct_id.clone(),
                            person_uuid: data.target_marked.target_person_uuid.clone(),
                        })
                        .collect(),
                    conflicts: Vec::new(),
                })
            }
            MergeState::Failed { .. } => {
                // Nothing to do - already failed
                Ok(MergeResult {
                    merged: Vec::new(),
                    conflicts: Vec::new(),
                })
            }
        }
    }

    /// Resume merge from Started step - need to mark target and continue.
    async fn resume_from_started(&self, data: StartedData) -> ApiResult<MergeResult> {
        // Mark target as merging (idempotent with same version)
        let target_result = self
            .person_distinct_ids_api
            .set_merging_target(&data.target_distinct_id, data.version)
            .await?;

        match target_result {
            SetMergingTargetResult::Ok { person_uuid, .. } => {
                // Transition to TargetMarked state
                let target_marked_data = TargetMarkedData {
                    started: data,
                    target_person_uuid: person_uuid,
                };
                let state = MergeState::TargetMarked(target_marked_data.clone());
                self.save_state(&state).await?;
                self.resume_from_target_marked(target_marked_data).await
            }
            SetMergingTargetResult::Conflict {
                distinct_id,
                person_uuid,
                merging_into_distinct_id,
            } => {
                // Target is being merged elsewhere - mark as failed
                let state = MergeState::Failed {
                    merge_id: data.merge_id.clone(),
                    error: format!(
                        "Target {} is being merged into {}",
                        distinct_id, merging_into_distinct_id
                    ),
                };
                self.save_state(&state).await?;
                Ok(MergeResult {
                    merged: Vec::new(),
                    conflicts: vec![MergeConflict::TargetIsSourceInAnotherMerge {
                        distinct_id,
                        person_uuid,
                        merging_into_distinct_id,
                    }],
                })
            }
        }
    }

    /// Resume merge from TargetMarked step - need to mark sources and continue.
    async fn resume_from_target_marked(&self, data: TargetMarkedData) -> ApiResult<MergeResult> {
        let mut conflicts: Vec<MergeConflict> = Vec::new();

        // Mark sources as merging (idempotent with same version)
        let source_results = self
            .person_distinct_ids_api
            .set_merging_source(&data.started.source_distinct_ids, data.started.version)
            .await?;

        let mut valid_sources = std::collections::HashMap::new();
        let mut source_person_uuids_set = HashSet::new();

        for result in source_results {
            match result {
                SetMergingSourceResult::Ok {
                    distinct_id,
                    person_uuid,
                } => {
                    valid_sources.insert(distinct_id, person_uuid.clone());
                    source_person_uuids_set.insert(person_uuid);
                }
                SetMergingSourceResult::Conflict {
                    distinct_id,
                    person_uuid,
                    current_merge_status,
                } => match current_merge_status {
                    MergeStatus::MergingSource => {
                        conflicts.push(MergeConflict::SourceAlreadyMergingElsewhere {
                            distinct_id,
                            person_uuid,
                        });
                    }
                    MergeStatus::MergingTarget => {
                        conflicts.push(MergeConflict::SourceIsMergeTarget {
                            distinct_id,
                            person_uuid,
                        });
                    }
                },
            }
        }

        // Transition to SourcesMarked state
        let sources_marked_data = SourcesMarkedData {
            target_marked: data,
            valid_sources,
            source_person_uuids: source_person_uuids_set.into_iter().collect(),
        };
        let state = MergeState::SourcesMarked(sources_marked_data.clone());
        self.save_state(&state).await?;

        if sources_marked_data.valid_sources.is_empty() {
            // No valid sources - clear target and complete
            self.person_distinct_ids_api
                .set_merged(
                    &sources_marked_data.target_marked.started.target_distinct_id,
                    &sources_marked_data.target_marked.target_person_uuid,
                    sources_marked_data.target_marked.started.version,
                )
                .await?;
            let completed_state = MergeState::Completed(sources_marked_data);
            self.save_state(&completed_state).await?;
            return Ok(MergeResult {
                merged: Vec::new(),
                conflicts,
            });
        }

        // Continue with property merge
        let mut result = self.resume_from_sources_marked(sources_marked_data).await?;
        result.conflicts = conflicts;
        Ok(result)
    }

    /// Resume merge from SourcesMarked step - properties need to be merged.
    async fn resume_from_sources_marked(&self, data: SourcesMarkedData) -> ApiResult<MergeResult> {
        let target_person_uuid = &data.target_marked.target_person_uuid;

        if data.source_person_uuids.is_empty() {
            // No sources to merge, just clear target and complete
            self.person_distinct_ids_api
                .set_merged(
                    &data.target_marked.started.target_distinct_id,
                    target_person_uuid,
                    data.target_marked.started.version,
                )
                .await?;
            let completed_state = MergeState::Completed(data);
            self.save_state(&completed_state).await?;
            return Ok(MergeResult {
                merged: Vec::new(),
                conflicts: Vec::new(),
            });
        }

        // Merge properties
        let merge_result = self
            .person_properties_api
            .get_persons_for_merge(target_person_uuid, &data.source_person_uuids)
            .await?;

        let source_persons: Vec<Person> = data
            .source_person_uuids
            .iter()
            .filter_map(|uuid| merge_result.source_persons.get(uuid).cloned())
            .collect();

        if !source_persons.is_empty() {
            self.person_properties_api
                .merge_person_properties(target_person_uuid, &source_persons)
                .await?;
        }

        // Transition to PropertiesMerged state
        let state = MergeState::PropertiesMerged(data.clone());
        self.save_state(&state).await?;

        // Continue with the rest
        self.resume_from_properties_merged(data).await
    }

    /// Resume merge from PropertiesMerged step - distinct IDs need to be updated.
    async fn resume_from_properties_merged(
        &self,
        data: SourcesMarkedData,
    ) -> ApiResult<MergeResult> {
        let target_person_uuid = &data.target_marked.target_person_uuid;
        let version = data.target_marked.started.version;

        let set_merged_futures: Vec<_> = data
            .valid_sources
            .keys()
            .map(|distinct_id| {
                self.person_distinct_ids_api
                    .set_merged(distinct_id, target_person_uuid, version)
            })
            .collect();

        futures::future::try_join_all(set_merged_futures).await?;

        // Transition to DistinctIdsMerged state
        let state = MergeState::DistinctIdsMerged(data.clone());
        self.save_state(&state).await?;

        self.resume_from_distinct_ids_merged(data).await
    }

    /// Resume merge from DistinctIdsMerged step - target needs to be cleared.
    async fn resume_from_distinct_ids_merged(
        &self,
        data: SourcesMarkedData,
    ) -> ApiResult<MergeResult> {
        self.person_distinct_ids_api
            .set_merged(
                &data.target_marked.started.target_distinct_id,
                &data.target_marked.target_person_uuid,
                data.target_marked.started.version,
            )
            .await?;

        // Transition to TargetCleared state
        let state = MergeState::TargetCleared(data.clone());
        self.save_state(&state).await?;

        self.resume_from_target_cleared(data).await
    }

    /// Resume merge from TargetCleared step - delete source persons and complete.
    async fn resume_from_target_cleared(&self, data: SourcesMarkedData) -> ApiResult<MergeResult> {
        let delete_futures: Vec<_> = data
            .source_person_uuids
            .iter()
            .map(|person_uuid| self.person_properties_api.delete_person(person_uuid))
            .collect();

        futures::future::try_join_all(delete_futures).await?;

        let target_person_uuid = data.target_marked.target_person_uuid.clone();
        let merged: Vec<DistinctIdInfo> = data
            .valid_sources
            .keys()
            .map(|distinct_id| DistinctIdInfo {
                distinct_id: distinct_id.clone(),
                person_uuid: target_person_uuid.clone(),
            })
            .collect();

        let state = MergeState::Completed(data);
        self.save_state(&state).await?;

        Ok(MergeResult {
            merged,
            conflicts: Vec::new(),
        })
    }
}
