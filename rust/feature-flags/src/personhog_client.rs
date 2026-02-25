use std::collections::HashMap;
use std::time::Duration;

use async_trait::async_trait;
use common_types::{Person, PersonId, TeamId};
use personhog_proto::personhog::service::v1::person_hog_service_client::PersonHogServiceClient;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, GetGroupsRequest, GetHashKeyOverrideContextRequest,
    GetPersonByDistinctIdRequest, GroupIdentifier, HashKeyOverrideContext,
    UpsertHashKeyOverridesRequest,
};
use serde_json::Value;
use tonic::transport::Channel;
use tonic::Request;
use tracing::warn;

use crate::api::errors::FlagError;
use crate::cohorts::cohort_models::CohortId;
use crate::flags::flag_group_type_mapping::GroupTypeIndex;
use crate::metrics::consts::FLAG_PERSONHOG_ERRORS_COUNTER;

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
        distinct_ids: Vec<String>,
        feature_flag_keys: Vec<String>,
        hash_key: String,
    ) -> Result<(), FlagError>;
}

#[derive(Clone)]
pub struct PersonhogClient {
    client: PersonHogServiceClient<Channel>,
}

impl PersonhogClient {
    pub fn new(
        url: &str,
        timeout_ms: u64,
        connect_timeout_ms: u64,
        keep_alive_interval_secs: u64,
        keep_alive_timeout_secs: u64,
    ) -> Result<Self, FlagError> {
        let channel = Channel::from_shared(url.to_string())
            .map_err(|e| FlagError::PersonhogError {
                code: tonic::Code::InvalidArgument,
                message: format!("Invalid personhog URL: {e}"),
            })?
            .timeout(Duration::from_millis(timeout_ms))
            .connect_timeout(Duration::from_millis(connect_timeout_ms))
            .http2_keep_alive_interval(Duration::from_secs(keep_alive_interval_secs))
            .keep_alive_timeout(Duration::from_secs(keep_alive_timeout_secs))
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
            .map_err(|s| {
                common_metrics::inc(
                    FLAG_PERSONHOG_ERRORS_COUNTER,
                    &[
                        ("method".to_string(), "GetPersonByDistinctId".to_string()),
                        ("grpc_code".to_string(), format!("{:?}", s.code())),
                    ],
                    1,
                );
                FlagError::PersonhogError {
                    code: s.code(),
                    message: format!("GetPersonByDistinctId failed: {}", s.message()),
                }
            })?;

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
            uuid: proto_person.uuid.parse().unwrap_or_else(|e| {
                warn!(
                    person_id = proto_person.id,
                    raw_uuid = proto_person.uuid,
                    error = %e,
                    "Failed to parse person UUID from personhog, falling back to nil"
                );
                uuid::Uuid::nil()
            }),
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
            .map_err(|s| {
                common_metrics::inc(
                    FLAG_PERSONHOG_ERRORS_COUNTER,
                    &[
                        ("method".to_string(), "CheckCohortMembership".to_string()),
                        ("grpc_code".to_string(), format!("{:?}", s.code())),
                    ],
                    1,
                );
                FlagError::PersonhogError {
                    code: s.code(),
                    message: format!("CheckCohortMembership failed: {}", s.message()),
                }
            })?;

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

        let response = self.client.clone().get_groups(request).await.map_err(|s| {
            common_metrics::inc(
                FLAG_PERSONHOG_ERRORS_COUNTER,
                &[
                    ("method".to_string(), "GetGroups".to_string()),
                    ("grpc_code".to_string(), format!("{:?}", s.code())),
                ],
                1,
            );
            FlagError::PersonhogError {
                code: s.code(),
                message: format!("GetGroups failed: {}", s.message()),
            }
        })?;

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
        let first_distinct_id = distinct_ids.first().cloned();

        let request = Request::new(GetHashKeyOverrideContextRequest {
            team_id: team_id as i64,
            distinct_ids,
            check_person_exists: false,
            read_options: None,
        });

        let response = self
            .client
            .clone()
            .get_hash_key_override_context(request)
            .await
            .map_err(|s| {
                common_metrics::inc(
                    FLAG_PERSONHOG_ERRORS_COUNTER,
                    &[
                        (
                            "method".to_string(),
                            "GetHashKeyOverrideContext".to_string(),
                        ),
                        ("grpc_code".to_string(), format!("{:?}", s.code())),
                    ],
                    1,
                );
                FlagError::PersonhogError {
                    code: s.code(),
                    message: format!("GetHashKeyOverrideContext failed: {}", s.message()),
                }
            })?;

        let results = response.into_inner().results;
        Ok(merge_hash_key_overrides(
            &results,
            first_distinct_id.as_deref(),
        ))
    }

    async fn upsert_hash_key_overrides(
        &self,
        team_id: TeamId,
        distinct_ids: Vec<String>,
        feature_flag_keys: Vec<String>,
        hash_key: String,
    ) -> Result<(), FlagError> {
        let request = Request::new(UpsertHashKeyOverridesRequest {
            team_id: team_id as i64,
            distinct_ids,
            hash_key,
            feature_flag_keys,
        });

        self.client
            .clone()
            .upsert_hash_key_overrides(request)
            .await
            .map_err(|s| {
                common_metrics::inc(
                    FLAG_PERSONHOG_ERRORS_COUNTER,
                    &[
                        ("method".to_string(), "UpsertHashKeyOverrides".to_string()),
                        ("grpc_code".to_string(), format!("{:?}", s.code())),
                    ],
                    1,
                );
                FlagError::PersonhogError {
                    code: s.code(),
                    message: format!("UpsertHashKeyOverrides failed: {}", s.message()),
                }
            })?;

        Ok(())
    }
}

/// Merges hash key override results, giving priority to the first distinct_id.
///
/// Results from the server may arrive in any order. All overrides are collected,
/// but `primary_distinct_id`'s entries are applied last so they win on conflict.
fn merge_hash_key_overrides(
    results: &[HashKeyOverrideContext],
    primary_distinct_id: Option<&str>,
) -> HashMap<String, String> {
    let mut overrides = HashMap::new();

    for context in results.iter() {
        if primary_distinct_id.is_some_and(|id| id == context.distinct_id) {
            continue;
        }
        for hash_override in &context.overrides {
            overrides.insert(
                hash_override.feature_flag_key.clone(),
                hash_override.hash_key.clone(),
            );
        }
    }

    if let Some(primary_context) =
        primary_distinct_id.and_then(|id| results.iter().find(|c| c.distinct_id == id))
    {
        for hash_override in &primary_context.overrides {
            overrides.insert(
                hash_override.feature_flag_key.clone(),
                hash_override.hash_key.clone(),
            );
        }
    }

    overrides
}

#[cfg(test)]
pub mod mock {
    use super::*;
    use std::sync::{Arc, Mutex};

    type CohortCall = (PersonId, Vec<CohortId>);
    type GroupCall = (TeamId, Vec<(GroupTypeIndex, String)>);
    type HashKeyContextCall = (TeamId, Vec<String>);
    type UpsertCall = (TeamId, Vec<String>, Vec<String>, String);

    pub struct MockPersonhogClient {
        person_responses: HashMap<(TeamId, String), Option<Person>>,
        cohort_responses: HashMap<PersonId, HashMap<CohortId, bool>>,
        group_responses: HashMap<TeamId, HashMap<GroupTypeIndex, HashMap<String, Value>>>,
        hash_key_override_responses: HashMap<TeamId, HashMap<String, String>>,
        cohort_calls: Arc<Mutex<Vec<CohortCall>>>,
        group_calls: Arc<Mutex<Vec<GroupCall>>>,
        hash_key_context_calls: Arc<Mutex<Vec<HashKeyContextCall>>>,
        upsert_calls: Arc<Mutex<Vec<UpsertCall>>>,
        error: Option<(tonic::Code, String)>,
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
                cohort_calls: Arc::new(Mutex::new(Vec::new())),
                group_calls: Arc::new(Mutex::new(Vec::new())),
                hash_key_context_calls: Arc::new(Mutex::new(Vec::new())),
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

        pub fn with_error(mut self, code: tonic::Code, message: impl Into<String>) -> Self {
            self.error = Some((code, message.into()));
            self
        }

        pub fn get_cohort_calls(&self) -> Vec<CohortCall> {
            self.cohort_calls.lock().unwrap().clone()
        }

        pub fn get_group_calls(&self) -> Vec<GroupCall> {
            self.group_calls.lock().unwrap().clone()
        }

        pub fn get_hash_key_context_calls(&self) -> Vec<HashKeyContextCall> {
            self.hash_key_context_calls.lock().unwrap().clone()
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
            if let Some((code, message)) = &self.error {
                return Err(FlagError::PersonhogError {
                    code: *code,
                    message: message.clone(),
                });
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
            cohort_ids: &[CohortId],
        ) -> Result<HashMap<CohortId, bool>, FlagError> {
            if let Some((code, message)) = &self.error {
                return Err(FlagError::PersonhogError {
                    code: *code,
                    message: message.clone(),
                });
            }
            self.cohort_calls
                .lock()
                .unwrap()
                .push((person_id, cohort_ids.to_vec()));
            Ok(self
                .cohort_responses
                .get(&person_id)
                .cloned()
                .unwrap_or_default())
        }

        async fn get_groups(
            &self,
            team_id: TeamId,
            group_identifiers: Vec<(GroupTypeIndex, String)>,
        ) -> Result<HashMap<GroupTypeIndex, HashMap<String, Value>>, FlagError> {
            if let Some((code, message)) = &self.error {
                return Err(FlagError::PersonhogError {
                    code: *code,
                    message: message.clone(),
                });
            }
            self.group_calls
                .lock()
                .unwrap()
                .push((team_id, group_identifiers));
            Ok(self
                .group_responses
                .get(&team_id)
                .cloned()
                .unwrap_or_default())
        }

        async fn get_hash_key_override_context(
            &self,
            team_id: TeamId,
            distinct_ids: Vec<String>,
        ) -> Result<HashMap<String, String>, FlagError> {
            if let Some((code, message)) = &self.error {
                return Err(FlagError::PersonhogError {
                    code: *code,
                    message: message.clone(),
                });
            }
            self.hash_key_context_calls
                .lock()
                .unwrap()
                .push((team_id, distinct_ids));
            Ok(self
                .hash_key_override_responses
                .get(&team_id)
                .cloned()
                .unwrap_or_default())
        }

        async fn upsert_hash_key_overrides(
            &self,
            team_id: TeamId,
            distinct_ids: Vec<String>,
            feature_flag_keys: Vec<String>,
            hash_key: String,
        ) -> Result<(), FlagError> {
            if let Some((code, message)) = &self.error {
                return Err(FlagError::PersonhogError {
                    code: *code,
                    message: message.clone(),
                });
            }
            self.upsert_calls.lock().unwrap().push((
                team_id,
                distinct_ids,
                feature_flag_keys,
                hash_key,
            ));
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use personhog_proto::personhog::types::v1::HashKeyOverride;

    fn make_context(distinct_id: &str, overrides: Vec<(&str, &str)>) -> HashKeyOverrideContext {
        HashKeyOverrideContext {
            person_id: 0,
            distinct_id: distinct_id.to_string(),
            overrides: overrides
                .into_iter()
                .map(|(key, val)| HashKeyOverride {
                    feature_flag_key: key.to_string(),
                    hash_key: val.to_string(),
                })
                .collect(),
            existing_feature_flag_keys: vec![],
        }
    }

    #[test]
    fn test_merge_primary_distinct_id_wins_on_conflict() {
        let results = vec![
            make_context("user_b", vec![("flag_1", "hash_b")]),
            make_context("user_a", vec![("flag_1", "hash_a")]),
        ];

        let overrides = merge_hash_key_overrides(&results, Some("user_a"));
        assert_eq!(overrides.get("flag_1").unwrap(), "hash_a");
    }

    #[test]
    fn test_merge_non_conflicting_overrides_from_all_distinct_ids() {
        let results = vec![
            make_context("user_a", vec![("flag_1", "hash_a")]),
            make_context("user_b", vec![("flag_2", "hash_b")]),
        ];

        let overrides = merge_hash_key_overrides(&results, Some("user_a"));
        assert_eq!(overrides.get("flag_1").unwrap(), "hash_a");
        assert_eq!(overrides.get("flag_2").unwrap(), "hash_b");
    }

    #[test]
    fn test_merge_works_regardless_of_result_order() {
        // primary comes first in results
        let results_primary_first = vec![
            make_context("user_a", vec![("flag_1", "hash_a")]),
            make_context("user_b", vec![("flag_1", "hash_b")]),
        ];
        // primary comes last in results
        let results_primary_last = vec![
            make_context("user_b", vec![("flag_1", "hash_b")]),
            make_context("user_a", vec![("flag_1", "hash_a")]),
        ];

        let overrides_first = merge_hash_key_overrides(&results_primary_first, Some("user_a"));
        let overrides_last = merge_hash_key_overrides(&results_primary_last, Some("user_a"));
        assert_eq!(overrides_first, overrides_last);
        assert_eq!(overrides_first.get("flag_1").unwrap(), "hash_a");
    }

    #[test]
    fn test_merge_with_no_primary_distinct_id() {
        let results = vec![
            make_context("user_a", vec![("flag_1", "hash_a")]),
            make_context("user_b", vec![("flag_1", "hash_b")]),
        ];

        // Without a primary, last writer wins (iteration order)
        let overrides = merge_hash_key_overrides(&results, None);
        assert_eq!(overrides.get("flag_1").unwrap(), "hash_b");
    }

    #[test]
    fn test_merge_with_empty_results() {
        let overrides = merge_hash_key_overrides(&[], Some("user_a"));
        assert!(overrides.is_empty());
    }
}
