use std::collections::HashMap;
use std::time::Duration;

use async_trait::async_trait;
use common_types::{Person, PersonId, TeamId};
use personhog_proto::personhog::service::v1::person_hog_service_client::PersonHogServiceClient;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, GetGroupsRequest, GetHashKeyOverrideContextRequest,
    GetPersonByDistinctIdRequest, GroupIdentifier, HashKeyOverrideInput,
    UpsertHashKeyOverridesRequest,
};
use serde_json::Value;
use tonic::transport::Channel;
use tonic::Request;

use crate::api::errors::FlagError;
use crate::cohorts::cohort_models::CohortId;
use crate::flags::flag_group_type_mapping::GroupTypeIndex;

/// Abstraction over person/group data fetching from the personhog service.
///
/// Production code uses `PersonhogClient` (gRPC). Tests inject `MockPersonhogClient`
/// so we can exercise the personhog code paths without a running personhog-router.
#[async_trait]
pub trait PersonhogFetcher: Send + Sync {
    async fn get_person_by_distinct_id(
        &self,
        team_id: TeamId,
        distinct_id: &str,
    ) -> Result<Option<Person>, FlagError>;

    async fn check_cohort_membership(
        &self,
        person_id: PersonId,
        cohort_ids: &[CohortId],
    ) -> Result<HashMap<CohortId, bool>, FlagError>;

    async fn get_groups(
        &self,
        team_id: TeamId,
        group_identifiers: Vec<(GroupTypeIndex, String)>,
    ) -> Result<HashMap<GroupTypeIndex, HashMap<String, Value>>, FlagError>;

    async fn get_hash_key_override_context(
        &self,
        team_id: TeamId,
        distinct_ids: Vec<String>,
    ) -> Result<HashMap<String, String>, FlagError>;

    async fn upsert_hash_key_overrides(
        &self,
        team_id: TeamId,
        person_id: PersonId,
        feature_flag_keys: Vec<String>,
        hash_key: String,
    ) -> Result<(), FlagError>;
}

#[derive(Clone)]
pub struct PersonhogClient {
    client: PersonHogServiceClient<Channel>,
}

impl PersonhogClient {
    pub fn new(url: &str, timeout_ms: u64) -> Result<Self, FlagError> {
        let channel = Channel::from_shared(url.to_string())
            .map_err(|e| FlagError::PersonhogError(format!("Invalid personhog URL: {e}")))?
            .timeout(Duration::from_millis(timeout_ms))
            .connect_lazy();

        Ok(Self {
            client: PersonHogServiceClient::new(channel),
        })
    }
}

#[async_trait]
impl PersonhogFetcher for PersonhogClient {
    async fn get_person_by_distinct_id(
        &self,
        team_id: TeamId,
        distinct_id: &str,
    ) -> Result<Option<Person>, FlagError> {
        let request = Request::new(GetPersonByDistinctIdRequest {
            team_id: team_id as i64,
            distinct_id: distinct_id.to_string(),
            read_options: None,
        });

        let response = self
            .client
            .clone()
            .get_person_by_distinct_id(request)
            .await
            .map_err(|s| FlagError::PersonhogError(format!("GetPersonByDistinctId failed: {s}")))?;

        let proto_person = match response.into_inner().person {
            Some(p) => p,
            None => return Ok(None),
        };

        let properties: Value = serde_json::from_slice(&proto_person.properties).map_err(|e| {
            FlagError::DataParsingErrorWithContext(format!(
                "Failed to parse person properties from personhog: {e}"
            ))
        })?;

        Ok(Some(Person {
            id: proto_person.id,
            team_id: proto_person.team_id as i32,
            uuid: proto_person
                .uuid
                .parse()
                .unwrap_or_else(|_| uuid::Uuid::nil()),
            properties,
            is_identified: proto_person.is_identified,
            is_user_id: if proto_person.is_user_id {
                Some(1)
            } else {
                None
            },
            version: Some(proto_person.version),
            created_at: chrono::DateTime::from_timestamp(proto_person.created_at, 0)
                .unwrap_or_default(),
        }))
    }

    async fn check_cohort_membership(
        &self,
        person_id: PersonId,
        cohort_ids: &[CohortId],
    ) -> Result<HashMap<CohortId, bool>, FlagError> {
        let request = Request::new(CheckCohortMembershipRequest {
            person_id,
            cohort_ids: cohort_ids.iter().map(|id| *id as i64).collect(),
            read_options: None,
        });

        let response = self
            .client
            .clone()
            .check_cohort_membership(request)
            .await
            .map_err(|s| FlagError::PersonhogError(format!("CheckCohortMembership failed: {s}")))?;

        let memberships = response
            .into_inner()
            .memberships
            .into_iter()
            .map(|m| (m.cohort_id as CohortId, m.is_member))
            .collect();

        Ok(memberships)
    }

    async fn get_groups(
        &self,
        team_id: TeamId,
        group_identifiers: Vec<(GroupTypeIndex, String)>,
    ) -> Result<HashMap<GroupTypeIndex, HashMap<String, Value>>, FlagError> {
        let identifiers = group_identifiers
            .into_iter()
            .map(|(idx, key)| GroupIdentifier {
                group_type_index: idx,
                group_key: key,
            })
            .collect();

        let request = Request::new(GetGroupsRequest {
            team_id: team_id as i64,
            group_identifiers: identifiers,
            read_options: None,
        });

        let response = self
            .client
            .clone()
            .get_groups(request)
            .await
            .map_err(|s| FlagError::PersonhogError(format!("GetGroups failed: {s}")))?;

        let mut result = HashMap::new();
        for group in response.into_inner().groups {
            let properties: Value =
                serde_json::from_slice(&group.group_properties).map_err(|e| {
                    FlagError::DataParsingErrorWithContext(format!(
                        "Failed to parse group properties from personhog: {e}"
                    ))
                })?;

            if let Value::Object(props) = properties {
                let properties_map = props.into_iter().collect();
                result.insert(group.group_type_index, properties_map);
            }
        }

        Ok(result)
    }

    async fn get_hash_key_override_context(
        &self,
        team_id: TeamId,
        distinct_ids: Vec<String>,
    ) -> Result<HashMap<String, String>, FlagError> {
        let request = Request::new(GetHashKeyOverrideContextRequest {
            team_id: team_id as i64,
            distinct_ids: distinct_ids.clone(),
            check_person_exists: false,
            read_options: None,
        });

        let response = self
            .client
            .clone()
            .get_hash_key_override_context(request)
            .await
            .map_err(|s| {
                FlagError::PersonhogError(format!("GetHashKeyOverrideContext failed: {s}"))
            })?;

        let mut overrides = HashMap::new();

        // Process results: priority is based on distinct_id order (first = highest priority)
        // We process in reverse so highest priority (first distinct_id) writes last
        let results = response.into_inner().results;
        for context in results.iter().rev() {
            for hash_override in &context.overrides {
                overrides.insert(
                    hash_override.feature_flag_key.clone(),
                    hash_override.hash_key.clone(),
                );
            }
        }

        // Now process in forward order so the first distinct_id's overrides take precedence
        for context in &results {
            if !distinct_ids.is_empty() && context.distinct_id == distinct_ids[0] {
                for hash_override in &context.overrides {
                    overrides.insert(
                        hash_override.feature_flag_key.clone(),
                        hash_override.hash_key.clone(),
                    );
                }
            }
        }

        Ok(overrides)
    }

    async fn upsert_hash_key_overrides(
        &self,
        team_id: TeamId,
        person_id: PersonId,
        feature_flag_keys: Vec<String>,
        hash_key: String,
    ) -> Result<(), FlagError> {
        let overrides = feature_flag_keys
            .into_iter()
            .map(|key| HashKeyOverrideInput {
                person_id,
                feature_flag_key: key,
            })
            .collect();

        let request = Request::new(UpsertHashKeyOverridesRequest {
            team_id: team_id as i64,
            overrides,
            hash_key,
        });

        self.client
            .clone()
            .upsert_hash_key_overrides(request)
            .await
            .map_err(|s| {
                FlagError::PersonhogError(format!("UpsertHashKeyOverrides failed: {s}"))
            })?;

        Ok(())
    }
}

#[cfg(test)]
pub mod mock {
    use super::*;
    use std::sync::{Arc, Mutex};

    type UpsertCall = (TeamId, PersonId, Vec<String>, String);

    pub struct MockPersonhogClient {
        person_responses: HashMap<(TeamId, String), Option<Person>>,
        cohort_responses: HashMap<PersonId, HashMap<CohortId, bool>>,
        group_responses: HashMap<TeamId, HashMap<GroupTypeIndex, HashMap<String, Value>>>,
        hash_key_override_responses: HashMap<TeamId, HashMap<String, String>>,
        upsert_calls: Arc<Mutex<Vec<UpsertCall>>>,
        error: Option<FlagError>,
    }

    impl Default for MockPersonhogClient {
        fn default() -> Self {
            Self::new()
        }
    }

    impl MockPersonhogClient {
        pub fn new() -> Self {
            Self {
                person_responses: HashMap::new(),
                cohort_responses: HashMap::new(),
                group_responses: HashMap::new(),
                hash_key_override_responses: HashMap::new(),
                upsert_calls: Arc::new(Mutex::new(Vec::new())),
                error: None,
            }
        }

        pub fn with_person(
            mut self,
            team_id: TeamId,
            distinct_id: &str,
            person: Option<Person>,
        ) -> Self {
            self.person_responses
                .insert((team_id, distinct_id.to_string()), person);
            self
        }

        pub fn with_cohort_membership(
            mut self,
            person_id: PersonId,
            memberships: HashMap<CohortId, bool>,
        ) -> Self {
            self.cohort_responses.insert(person_id, memberships);
            self
        }

        pub fn with_groups(
            mut self,
            team_id: TeamId,
            groups: HashMap<GroupTypeIndex, HashMap<String, Value>>,
        ) -> Self {
            self.group_responses.insert(team_id, groups);
            self
        }

        pub fn with_hash_key_overrides(
            mut self,
            team_id: TeamId,
            overrides: HashMap<String, String>,
        ) -> Self {
            self.hash_key_override_responses.insert(team_id, overrides);
            self
        }

        pub fn with_error(mut self, error: FlagError) -> Self {
            self.error = Some(error);
            self
        }

        pub fn get_upsert_calls(&self) -> Vec<UpsertCall> {
            self.upsert_calls.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl PersonhogFetcher for MockPersonhogClient {
        async fn get_person_by_distinct_id(
            &self,
            team_id: TeamId,
            distinct_id: &str,
        ) -> Result<Option<Person>, FlagError> {
            if let Some(ref error) = self.error {
                return Err(FlagError::PersonhogError(error.to_string()));
            }
            Ok(self
                .person_responses
                .get(&(team_id, distinct_id.to_string()))
                .cloned()
                .unwrap_or(None))
        }

        async fn check_cohort_membership(
            &self,
            person_id: PersonId,
            _cohort_ids: &[CohortId],
        ) -> Result<HashMap<CohortId, bool>, FlagError> {
            if let Some(ref error) = self.error {
                return Err(FlagError::PersonhogError(error.to_string()));
            }
            Ok(self
                .cohort_responses
                .get(&person_id)
                .cloned()
                .unwrap_or_default())
        }

        async fn get_groups(
            &self,
            team_id: TeamId,
            _group_identifiers: Vec<(GroupTypeIndex, String)>,
        ) -> Result<HashMap<GroupTypeIndex, HashMap<String, Value>>, FlagError> {
            if let Some(ref error) = self.error {
                return Err(FlagError::PersonhogError(error.to_string()));
            }
            Ok(self
                .group_responses
                .get(&team_id)
                .cloned()
                .unwrap_or_default())
        }

        async fn get_hash_key_override_context(
            &self,
            team_id: TeamId,
            _distinct_ids: Vec<String>,
        ) -> Result<HashMap<String, String>, FlagError> {
            if let Some(ref error) = self.error {
                return Err(FlagError::PersonhogError(error.to_string()));
            }
            Ok(self
                .hash_key_override_responses
                .get(&team_id)
                .cloned()
                .unwrap_or_default())
        }

        async fn upsert_hash_key_overrides(
            &self,
            team_id: TeamId,
            person_id: PersonId,
            feature_flag_keys: Vec<String>,
            hash_key: String,
        ) -> Result<(), FlagError> {
            if let Some(ref error) = self.error {
                return Err(FlagError::PersonhogError(error.to_string()));
            }
            self.upsert_calls.lock().unwrap().push((
                team_id,
                person_id,
                feature_flag_keys,
                hash_key,
            ));
            Ok(())
        }
    }
}
