use async_trait::async_trait;
use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq)]
pub struct VersionedProperty {
    pub value: serde_json::Value,
    pub version: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Person {
    pub person_uuid: String,
    pub properties: HashMap<String, VersionedProperty>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DistinctIdInfo {
    pub person_uuid: String,
    pub distinct_id: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MergeStatus {
    MergingSource,
    MergingTarget,
}

#[derive(Debug, Clone, PartialEq)]
pub enum SetMergingSourceResult {
    Ok {
        distinct_id: String,
        person_uuid: String,
    },
    Conflict {
        distinct_id: String,
        person_uuid: String,
        current_merge_status: MergeStatus,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub enum SetMergingTargetResult {
    Ok {
        distinct_id: String,
        person_uuid: String,
    },
    Conflict {
        distinct_id: String,
        person_uuid: String,
        merging_into_distinct_id: String,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub enum MergeConflict {
    SourceAlreadyMergingElsewhere {
        distinct_id: String,
        person_uuid: String,
    },
    SourceIsMergeTarget {
        distinct_id: String,
        person_uuid: String,
    },
    TargetIsSourceInAnotherMerge {
        distinct_id: String,
        person_uuid: String,
        merging_into_distinct_id: String,
    },
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct MergeResult {
    pub merged: Vec<DistinctIdInfo>,
    pub conflicts: Vec<MergeConflict>,
}

pub type ApiResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

/// Result of fetching persons for merge, including the target person.
#[derive(Debug, Clone, PartialEq)]
pub struct GetPersonsForMergeResult {
    pub target_person: Person,
    pub source_persons: HashMap<String, Person>,
}

/// Trait for person properties operations.
#[async_trait]
pub trait PersonPropertiesApi: Send + Sync {
    /// Fetches persons for merge and marks them as being merged.
    ///
    /// This method marks the source persons as being merged into the target. Once marked,
    /// the persons API should reject writes to these source persons until the merge completes.
    /// Returns both the target person and the source persons.
    async fn get_persons_for_merge(
        &self,
        target_person_uuid: &str,
        source_person_uuids: &[String],
    ) -> ApiResult<GetPersonsForMergeResult>;

    async fn merge_person_properties(
        &self,
        target_person_uuid: &str,
        source_persons: &[Person],
    ) -> ApiResult<()>;

    /// Deletes a person after their distinct IDs have been merged into another person.
    async fn delete_person(&self, person_uuid: &str) -> ApiResult<()>;
}

/// Trait for distinct ID operations during merge.
#[async_trait]
pub trait PersonDistinctIdsApi: Send + Sync {
    async fn add_person_distinct_id(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        version: i64,
    ) -> ApiResult<DistinctIdInfo>;

    async fn delete_person_distinct_id(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        version: i64,
    ) -> ApiResult<DistinctIdInfo>;

    async fn set_person_uuid(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        version: i64,
    ) -> ApiResult<DistinctIdInfo>;

    async fn set_merging_source(
        &self,
        distinct_ids: &[String],
        version: i64,
    ) -> ApiResult<Vec<SetMergingSourceResult>>;

    async fn set_merging_target(
        &self,
        distinct_id: &str,
        version: i64,
    ) -> ApiResult<SetMergingTargetResult>;

    async fn set_merged(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        version: i64,
    ) -> ApiResult<DistinctIdInfo>;
}
