//! Mock implementations of the API traits using MockMethod infrastructure.

use std::sync::Arc;

use async_trait::async_trait;

use super::mock::MockMethod;
use crate::types::{
    ApiResult, DistinctIdInfo, GetPersonsForMergeResult, Person, PersonDistinctIdsApi,
    PersonPropertiesApi, SetMergingSourceResult, SetMergingTargetResult,
};

// =============================================================================
// Argument types for capturing method parameters
// =============================================================================

#[derive(Debug, Clone, PartialEq)]
pub struct SetMergingTargetArgs {
    pub distinct_id: String,
    pub version: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SetMergingSourceArgs {
    pub distinct_ids: Vec<String>,
    pub version: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SetMergedArgs {
    pub distinct_id: String,
    pub person_uuid: String,
    pub version: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct GetPersonsForMergeArgs {
    pub target_person_uuid: String,
    pub source_person_uuids: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct MergePersonPropertiesArgs {
    pub target_person_uuid: String,
    pub source_persons: Vec<Person>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DeletePersonArgs {
    pub person_uuid: String,
}

// =============================================================================
// Mock PersonDistinctIdsApi
// =============================================================================

/// Mock implementation of PersonDistinctIdsApi using MockMethod.
///
/// Each method has a corresponding MockMethod field. Set up expectations with
/// `mock.set_merging_target.expect(result)` and await the returned future to
/// wait for and control the call.
pub struct MockPersonDistinctIdsApi {
    pub set_merging_target: Arc<MockMethod<SetMergingTargetArgs, SetMergingTargetResult>>,
    pub set_merging_source: Arc<MockMethod<SetMergingSourceArgs, Vec<SetMergingSourceResult>>>,
    pub set_merged: Arc<MockMethod<SetMergedArgs, DistinctIdInfo>>,
}

impl MockPersonDistinctIdsApi {
    pub fn new() -> Self {
        Self {
            set_merging_target: Arc::new(MockMethod::new("set_merging_target")),
            set_merging_source: Arc::new(MockMethod::new("set_merging_source")),
            set_merged: Arc::new(MockMethod::new("set_merged")),
        }
    }
}

impl Default for MockPersonDistinctIdsApi {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl PersonDistinctIdsApi for MockPersonDistinctIdsApi {
    async fn add_person_distinct_id(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        _version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        // Not typically used in merge tests, just return success
        Ok(DistinctIdInfo {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
        })
    }

    async fn delete_person_distinct_id(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        _version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        Ok(DistinctIdInfo {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
        })
    }

    async fn set_person_uuid(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        _version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        Ok(DistinctIdInfo {
            distinct_id: distinct_id.to_string(),
            person_uuid: person_uuid.to_string(),
        })
    }

    async fn set_merging_source(
        &self,
        distinct_ids: &[String],
        version: i64,
    ) -> ApiResult<Vec<SetMergingSourceResult>> {
        Ok(self
            .set_merging_source
            .call(SetMergingSourceArgs {
                distinct_ids: distinct_ids.to_vec(),
                version,
            })
            .await)
    }

    async fn set_merging_target(
        &self,
        distinct_id: &str,
        version: i64,
    ) -> ApiResult<SetMergingTargetResult> {
        Ok(self
            .set_merging_target
            .call(SetMergingTargetArgs {
                distinct_id: distinct_id.to_string(),
                version,
            })
            .await)
    }

    async fn set_merged(
        &self,
        distinct_id: &str,
        person_uuid: &str,
        version: i64,
    ) -> ApiResult<DistinctIdInfo> {
        Ok(self
            .set_merged
            .call(SetMergedArgs {
                distinct_id: distinct_id.to_string(),
                person_uuid: person_uuid.to_string(),
                version,
            })
            .await)
    }
}

// =============================================================================
// Mock PersonPropertiesApi
// =============================================================================

/// Mock implementation of PersonPropertiesApi using MockMethod.
pub struct MockPersonPropertiesApi {
    pub get_persons_for_merge: Arc<MockMethod<GetPersonsForMergeArgs, GetPersonsForMergeResult>>,
    pub merge_person_properties: Arc<MockMethod<MergePersonPropertiesArgs, ()>>,
    pub delete_person: Arc<MockMethod<DeletePersonArgs, ()>>,
}

impl MockPersonPropertiesApi {
    pub fn new() -> Self {
        Self {
            get_persons_for_merge: Arc::new(MockMethod::new("get_persons_for_merge")),
            merge_person_properties: Arc::new(MockMethod::new("merge_person_properties")),
            delete_person: Arc::new(MockMethod::new("delete_person")),
        }
    }
}

impl Default for MockPersonPropertiesApi {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl PersonPropertiesApi for MockPersonPropertiesApi {
    async fn get_persons_for_merge(
        &self,
        target_person_uuid: &str,
        source_person_uuids: &[String],
    ) -> ApiResult<GetPersonsForMergeResult> {
        Ok(self
            .get_persons_for_merge
            .call(GetPersonsForMergeArgs {
                target_person_uuid: target_person_uuid.to_string(),
                source_person_uuids: source_person_uuids.to_vec(),
            })
            .await)
    }

    async fn merge_person_properties(
        &self,
        target_person_uuid: &str,
        source_persons: &[Person],
    ) -> ApiResult<()> {
        self.merge_person_properties
            .call(MergePersonPropertiesArgs {
                target_person_uuid: target_person_uuid.to_string(),
                source_persons: source_persons.to_vec(),
            })
            .await;
        Ok(())
    }

    async fn delete_person(&self, person_uuid: &str) -> ApiResult<()> {
        self.delete_person
            .call(DeletePersonArgs {
                person_uuid: person_uuid.to_string(),
            })
            .await;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use tokio::time::{timeout, Duration};

    const TEST_TIMEOUT: Duration = Duration::from_secs(2);

    #[tokio::test]
    async fn test_mock_distinct_ids_api_basic() {
        timeout(TEST_TIMEOUT, async {
            let mock = Arc::new(MockPersonDistinctIdsApi::new());

            // Set up expectation
            let call = mock.set_merging_target.expect(SetMergingTargetResult::Ok {
                distinct_id: "target".to_string(),
                person_uuid: "uuid".to_string(),
            });

            // Spawn caller
            let mock_clone = mock.clone();
            let handle =
                tokio::spawn(async move { mock_clone.set_merging_target("target", 1000).await });

            // Wait for call and check args
            let guard = call.await;
            assert_eq!(guard.distinct_id, "target");
            assert_eq!(guard.version, 1000);
            drop(guard);

            let result = handle.await.unwrap().unwrap();
            assert!(matches!(result, SetMergingTargetResult::Ok { .. }));
        })
        .await
        .expect("Test timed out");
    }

    #[tokio::test]
    async fn test_mock_properties_api_basic() {
        timeout(TEST_TIMEOUT, async {
            let mock = Arc::new(MockPersonPropertiesApi::new());

            let call = mock.get_persons_for_merge.expect(GetPersonsForMergeResult {
                target_person: Person {
                    person_uuid: "target-uuid".to_string(),
                    properties: HashMap::new(),
                },
                source_persons: HashMap::new(),
            });

            let mock_clone = mock.clone();
            let handle = tokio::spawn(async move {
                mock_clone
                    .get_persons_for_merge("target-uuid", &["source-uuid".to_string()])
                    .await
            });

            let guard = call.await;
            assert_eq!(guard.target_person_uuid, "target-uuid");
            assert_eq!(guard.source_person_uuids, vec!["source-uuid"]);
            drop(guard);

            let result = handle.await.unwrap().unwrap();
            assert_eq!(result.target_person.person_uuid, "target-uuid");
        })
        .await
        .expect("Test timed out");
    }
}
