use std::collections::HashSet;
use std::sync::Arc;

use async_trait::async_trait;

use crate::state::{
    CompletedState, DistinctIdsMergedState, MergeState, PropertiesMergedState, SourcesMarkedState,
    StartedState, TargetClearedState, TargetMarkedState,
};
use crate::types::{
    DistinctIdInfo, MergeConflict, MergeResult, MergeStatus, Person, PersonDistinctIdsApi,
    PersonPropertiesApi, SetMergingSourceResult, SetMergingTargetResult,
};

/// Context providing access to APIs needed for merge processing.
pub struct MergeContext {
    pub person_properties_api: Arc<dyn PersonPropertiesApi>,
    pub person_distinct_ids_api: Arc<dyn PersonDistinctIdsApi>,
}

impl MergeContext {
    pub fn new(
        person_properties_api: Arc<dyn PersonPropertiesApi>,
        person_distinct_ids_api: Arc<dyn PersonDistinctIdsApi>,
    ) -> Self {
        Self {
            person_properties_api,
            person_distinct_ids_api,
        }
    }
}

/// Result of processing a state in the merge state machine.
pub enum ProcessResult {
    /// Continue processing with the next state.
    Next(MergeState),
    /// Processing completed successfully. Includes result and optional state to save.
    Completed(MergeResult, Option<MergeState>),
    /// Processing failed with an error (API error, not a merge conflict).
    Failed(Box<dyn std::error::Error + Send + Sync>),
}

/// Trait for states that can be processed in the merge state machine.
#[async_trait]
pub trait Processable {
    /// Process this state and return the result.
    async fn process(self, ctx: &MergeContext) -> ProcessResult;
}

// =============================================================================
// Processable implementations for each state
// =============================================================================

#[async_trait]
impl Processable for StartedState {
    async fn process(self, ctx: &MergeContext) -> ProcessResult {
        let target_result = match ctx
            .person_distinct_ids_api
            .set_merging_target(&self.target_distinct_id, self.version)
            .await
        {
            Ok(r) => r,
            Err(e) => return ProcessResult::Failed(e),
        };

        match target_result {
            SetMergingTargetResult::Ok { person_uuid, .. } => {
                ProcessResult::Next(MergeState::TargetMarked(TargetMarkedState {
                    started: self,
                    target_person_uuid: person_uuid,
                }))
            }
            SetMergingTargetResult::Conflict {
                distinct_id,
                person_uuid,
                merging_into_distinct_id,
            } => {
                // Target is being merged elsewhere - this is a terminal conflict
                // No state to save since we didn't get past Started
                ProcessResult::Completed(
                    MergeResult {
                        merged: Vec::new(),
                        conflicts: vec![MergeConflict::TargetIsSourceInAnotherMerge {
                            distinct_id,
                            person_uuid,
                            merging_into_distinct_id,
                        }],
                    },
                    None,
                )
            }
        }
    }
}

#[async_trait]
impl Processable for TargetMarkedState {
    async fn process(self, ctx: &MergeContext) -> ProcessResult {
        let mut conflicts: Vec<MergeConflict> = Vec::new();

        let source_results = match ctx
            .person_distinct_ids_api
            .set_merging_source(&self.started.source_distinct_ids, self.started.version)
            .await
        {
            Ok(r) => r,
            Err(e) => return ProcessResult::Failed(e),
        };

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

        ProcessResult::Next(MergeState::SourcesMarked(SourcesMarkedState {
            merge_id: self.started.merge_id,
            target_distinct_id: self.started.target_distinct_id,
            source_distinct_ids: self.started.source_distinct_ids,
            version: self.started.version,
            target_person_uuid: self.target_person_uuid,
            valid_sources,
            source_person_uuids: source_person_uuids_set.into_iter().collect(),
            conflicts,
        }))
    }
}

#[async_trait]
impl Processable for SourcesMarkedState {
    async fn process(self, ctx: &MergeContext) -> ProcessResult {
        if self.source_person_uuids.is_empty() {
            // No sources to merge, just clear target and complete
            if let Err(e) = ctx
                .person_distinct_ids_api
                .set_merged(
                    &self.target_distinct_id,
                    &self.target_person_uuid,
                    self.version,
                )
                .await
            {
                return ProcessResult::Failed(e);
            }
            return ProcessResult::Completed(
                build_merge_result(&self),
                Some(MergeState::Completed(CompletedState {
                    merge_id: self.merge_id,
                    target_distinct_id: self.target_distinct_id,
                    source_distinct_ids: self.source_distinct_ids,
                    version: self.version,
                    target_person_uuid: self.target_person_uuid,
                    valid_sources: self.valid_sources,
                    source_person_uuids: self.source_person_uuids,
                    conflicts: self.conflicts,
                })),
            );
        }

        // Merge properties
        let merge_result = match ctx
            .person_properties_api
            .get_persons_for_merge(&self.target_person_uuid, &self.source_person_uuids)
            .await
        {
            Ok(r) => r,
            Err(e) => return ProcessResult::Failed(e),
        };

        let source_persons: Vec<Person> = self
            .source_person_uuids
            .iter()
            .filter_map(|uuid| merge_result.source_persons.get(uuid).cloned())
            .collect();

        if !source_persons.is_empty() {
            if let Err(e) = ctx
                .person_properties_api
                .merge_person_properties(&self.target_person_uuid, &source_persons)
                .await
            {
                return ProcessResult::Failed(e);
            }
        }

        ProcessResult::Next(MergeState::PropertiesMerged(PropertiesMergedState {
            merge_id: self.merge_id,
            target_distinct_id: self.target_distinct_id,
            source_distinct_ids: self.source_distinct_ids,
            version: self.version,
            target_person_uuid: self.target_person_uuid,
            valid_sources: self.valid_sources,
            source_person_uuids: self.source_person_uuids,
            conflicts: self.conflicts,
        }))
    }
}

#[async_trait]
impl Processable for PropertiesMergedState {
    async fn process(self, ctx: &MergeContext) -> ProcessResult {
        let set_merged_futures: Vec<_> = self
            .valid_sources
            .keys()
            .map(|distinct_id| {
                ctx.person_distinct_ids_api.set_merged(
                    distinct_id,
                    &self.target_person_uuid,
                    self.version,
                )
            })
            .collect();

        if let Err(e) = futures::future::try_join_all(set_merged_futures).await {
            return ProcessResult::Failed(e);
        }

        ProcessResult::Next(MergeState::DistinctIdsMerged(DistinctIdsMergedState {
            merge_id: self.merge_id,
            target_distinct_id: self.target_distinct_id,
            source_distinct_ids: self.source_distinct_ids,
            version: self.version,
            target_person_uuid: self.target_person_uuid,
            valid_sources: self.valid_sources,
            source_person_uuids: self.source_person_uuids,
            conflicts: self.conflicts,
        }))
    }
}

#[async_trait]
impl Processable for DistinctIdsMergedState {
    async fn process(self, ctx: &MergeContext) -> ProcessResult {
        if let Err(e) = ctx
            .person_distinct_ids_api
            .set_merged(
                &self.target_distinct_id,
                &self.target_person_uuid,
                self.version,
            )
            .await
        {
            return ProcessResult::Failed(e);
        }

        ProcessResult::Next(MergeState::TargetCleared(TargetClearedState {
            merge_id: self.merge_id,
            target_distinct_id: self.target_distinct_id,
            source_distinct_ids: self.source_distinct_ids,
            version: self.version,
            target_person_uuid: self.target_person_uuid,
            valid_sources: self.valid_sources,
            source_person_uuids: self.source_person_uuids,
            conflicts: self.conflicts,
        }))
    }
}

#[async_trait]
impl Processable for TargetClearedState {
    async fn process(self, ctx: &MergeContext) -> ProcessResult {
        let delete_futures: Vec<_> = self
            .source_person_uuids
            .iter()
            .map(|person_uuid| ctx.person_properties_api.delete_person(person_uuid))
            .collect();

        if let Err(e) = futures::future::try_join_all(delete_futures).await {
            return ProcessResult::Failed(e);
        }

        ProcessResult::Completed(
            build_merge_result(&self),
            Some(MergeState::Completed(CompletedState {
                merge_id: self.merge_id,
                target_distinct_id: self.target_distinct_id,
                source_distinct_ids: self.source_distinct_ids,
                version: self.version,
                target_person_uuid: self.target_person_uuid,
                valid_sources: self.valid_sources,
                source_person_uuids: self.source_person_uuids,
                conflicts: self.conflicts,
            })),
        )
    }
}

/// Trait for states that have merge result data.
trait HasMergeResultData {
    fn target_person_uuid(&self) -> &str;
    fn valid_sources(&self) -> &std::collections::HashMap<String, String>;
    fn conflicts(&self) -> &[MergeConflict];
}

impl HasMergeResultData for SourcesMarkedState {
    fn target_person_uuid(&self) -> &str {
        &self.target_person_uuid
    }
    fn valid_sources(&self) -> &std::collections::HashMap<String, String> {
        &self.valid_sources
    }
    fn conflicts(&self) -> &[MergeConflict] {
        &self.conflicts
    }
}

impl HasMergeResultData for TargetClearedState {
    fn target_person_uuid(&self) -> &str {
        &self.target_person_uuid
    }
    fn valid_sources(&self) -> &std::collections::HashMap<String, String> {
        &self.valid_sources
    }
    fn conflicts(&self) -> &[MergeConflict] {
        &self.conflicts
    }
}

impl HasMergeResultData for CompletedState {
    fn target_person_uuid(&self) -> &str {
        &self.target_person_uuid
    }
    fn valid_sources(&self) -> &std::collections::HashMap<String, String> {
        &self.valid_sources
    }
    fn conflicts(&self) -> &[MergeConflict] {
        &self.conflicts
    }
}

/// Build the final MergeResult from state data.
fn build_merge_result<T: HasMergeResultData>(state: &T) -> MergeResult {
    let target_person_uuid = state.target_person_uuid();
    MergeResult {
        merged: state
            .valid_sources()
            .keys()
            .map(|distinct_id| DistinctIdInfo {
                distinct_id: distinct_id.clone(),
                person_uuid: target_person_uuid.to_string(),
            })
            .collect(),
        conflicts: state.conflicts().to_vec(),
    }
}

// =============================================================================
// MergeState process dispatch
// =============================================================================

impl MergeState {
    /// Process this state and return the result.
    /// Dispatches to the appropriate Processable implementation.
    pub async fn process(self, ctx: &MergeContext) -> ProcessResult {
        match self {
            MergeState::Started(state) => state.process(ctx).await,
            MergeState::TargetMarked(state) => state.process(ctx).await,
            MergeState::SourcesMarked(state) => state.process(ctx).await,
            MergeState::PropertiesMerged(state) => state.process(ctx).await,
            MergeState::DistinctIdsMerged(state) => state.process(ctx).await,
            MergeState::TargetCleared(state) => state.process(ctx).await,
            // Terminal states - already done, no state to save
            MergeState::Completed(state) => {
                ProcessResult::Completed(build_merge_result(&state), None)
            }
            MergeState::Failed { .. } => ProcessResult::Completed(
                MergeResult {
                    merged: Vec::new(),
                    conflicts: Vec::new(),
                },
                None,
            ),
        }
    }
}
