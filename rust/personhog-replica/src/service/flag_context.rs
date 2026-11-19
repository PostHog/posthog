use personhog_proto::personhog::types::v1::{
    CohortMembership, GetFlagContextRequest, GetFlagContextResponse, Group, HashKeyOverride,
    HashKeyOverrideContext, Person,
};
use tonic::metadata::MetadataMap;
use tonic::Status;

use super::error::log_and_convert_error;
use super::followed::followed_or_stored;
use super::PersonHogReplicaService;
use crate::storage;
use crate::storage::postgres::ConsistencyLevel;

impl PersonHogReplicaService {
    /// Everything flag evaluation reads about one visitor, in one call. The person comes
    /// from a follower when the router sent the call to one that can answer; every other
    /// part is the same eventual read its own call makes.
    pub(super) async fn flag_context(
        &self,
        metadata: &MetadataMap,
        req: GetFlagContextRequest,
    ) -> Result<GetFlagContextResponse, Status> {
        let team_id = req.team_id;
        let person = async {
            let Some(person_id) = req.person_id else {
                return Ok(None);
            };
            let followed = self.followed_person(metadata, team_id, person_id);
            followed_or_stored(followed, || async {
                self.storage
                    .get_person_by_id(team_id, person_id)
                    .await
                    .map(|person| person.map(Into::into))
                    .map_err(|e| log_and_convert_error(e, "get_flag_context_person"))
            })
            .await
        };
        let cohort_memberships = async {
            let Some(person_id) = req.person_id.filter(|_| !req.static_cohort_ids.is_empty())
            else {
                return Ok(Vec::new());
            };
            let memberships = self
                .storage
                .check_cohort_membership(
                    person_id,
                    &req.static_cohort_ids,
                    ConsistencyLevel::Eventual,
                )
                .await
                .map_err(|e| log_and_convert_error(e, "get_flag_context_cohorts"))?;
            Ok(memberships
                .into_iter()
                .map(|m| CohortMembership {
                    cohort_id: m.cohort_id,
                    is_member: m.is_member,
                })
                .collect())
        };
        let groups = async {
            if req.group_identifiers.is_empty() {
                return Ok(Vec::new());
            }
            let identifiers: Vec<storage::GroupIdentifier> = req
                .group_identifiers
                .iter()
                .map(|gi| storage::GroupIdentifier {
                    group_type_index: gi.group_type_index,
                    group_key: gi.group_key.clone(),
                })
                .collect();
            let groups = self
                .storage
                .get_groups(team_id, &identifiers, ConsistencyLevel::Eventual, true)
                .await
                .map_err(|e| log_and_convert_error(e, "get_flag_context_groups"))?;
            Ok(groups.into_iter().map(Group::from).collect())
        };
        let hash_key_overrides = async {
            if req.override_distinct_ids.is_empty() {
                return Ok(Vec::new());
            }
            let contexts = self
                .storage
                .get_hash_key_override_context(
                    team_id,
                    &req.override_distinct_ids,
                    false,
                    ConsistencyLevel::Eventual,
                )
                .await
                .map_err(|e| log_and_convert_error(e, "get_flag_context_overrides"))?;
            Ok(contexts
                .into_iter()
                .map(|context| HashKeyOverrideContext {
                    person_id: context.person_id,
                    distinct_id: context.distinct_id,
                    overrides: context
                        .overrides
                        .into_iter()
                        .map(|o| HashKeyOverride {
                            feature_flag_key: o.feature_flag_key,
                            hash_key: o.hash_key,
                        })
                        .collect(),
                    existing_feature_flag_keys: context.existing_feature_flag_keys,
                })
                .collect())
        };
        let (person, cohort_memberships, groups, hash_key_overrides): (
            Option<Person>,
            Vec<CohortMembership>,
            Vec<Group>,
            Vec<HashKeyOverrideContext>,
        ) = tokio::try_join!(person, cohort_memberships, groups, hash_key_overrides)?;
        // Memberships are looked up by person id alone. The person read is the one scoped
        // to the team, so memberships are returned only for a person found in it.
        let cohort_memberships = if person.is_some() {
            cohort_memberships
        } else {
            Vec::new()
        };
        Ok(GetFlagContextResponse {
            person,
            cohort_memberships,
            groups,
            hash_key_overrides,
        })
    }
}
