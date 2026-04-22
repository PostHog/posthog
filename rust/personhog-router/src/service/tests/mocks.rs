use async_trait::async_trait;
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, CohortMembershipResponse, CountCohortMembersRequest,
    CountCohortMembersResponse, DeleteCohortMemberRequest, DeleteCohortMemberResponse,
    DeleteCohortMembersBulkRequest, DeleteCohortMembersBulkResponse,
    DeleteHashKeyOverridesByTeamsRequest, DeleteHashKeyOverridesByTeamsResponse,
    DeletePersonsBatchForTeamRequest, DeletePersonsBatchForTeamResponse, DeletePersonsRequest,
    DeletePersonsResponse, GetDistinctIdsForPersonRequest, GetDistinctIdsForPersonResponse,
    GetDistinctIdsForPersonsRequest, GetDistinctIdsForPersonsResponse, GetGroupRequest,
    GetGroupResponse, GetGroupTypeMappingsByProjectIdRequest,
    GetGroupTypeMappingsByProjectIdsRequest, GetGroupTypeMappingsByTeamIdRequest,
    GetGroupTypeMappingsByTeamIdsRequest, GetGroupsBatchRequest, GetGroupsBatchResponse,
    GetGroupsRequest, GetHashKeyOverrideContextRequest, GetHashKeyOverrideContextResponse,
    GetPersonByDistinctIdRequest, GetPersonByUuidRequest, GetPersonRequest, GetPersonResponse,
    GetPersonsByDistinctIdsInTeamRequest, GetPersonsByDistinctIdsRequest, GetPersonsByUuidsRequest,
    GetPersonsRequest, GroupTypeMappingsBatchResponse, GroupTypeMappingsResponse, GroupsResponse,
    InsertCohortMembersRequest, InsertCohortMembersResponse, ListCohortMemberIdsRequest,
    ListCohortMemberIdsResponse, Person, PersonsByDistinctIdsInTeamResponse,
    PersonsByDistinctIdsResponse, PersonsResponse, UpsertHashKeyOverridesRequest,
    UpsertHashKeyOverridesResponse,
};
use std::sync::Mutex;
use tonic::Status;

use crate::backend::PersonHogBackend;

pub struct MockBackend {
    person_response: Mutex<Option<Person>>,
    error: Mutex<Option<Status>>,
}

impl MockBackend {
    pub fn new() -> Self {
        Self {
            person_response: Mutex::new(None),
            error: Mutex::new(None),
        }
    }

    pub fn set_person_response(&self, person: Option<Person>) {
        *self.person_response.lock().unwrap() = person;
    }

    pub fn set_error(&self, status: Status) {
        *self.error.lock().unwrap() = Some(status);
    }

    #[allow(clippy::result_large_err)] // tonic::Status is large but we can't change it
    fn check_error(&self) -> Result<(), Status> {
        if let Some(status) = self.error.lock().unwrap().clone() {
            return Err(status);
        }
        Ok(())
    }
}

#[async_trait]
impl PersonHogBackend for MockBackend {
    async fn get_person(&self, _request: GetPersonRequest) -> Result<GetPersonResponse, Status> {
        self.check_error()?;
        Ok(GetPersonResponse {
            person: self.person_response.lock().unwrap().clone(),
        })
    }

    async fn get_persons(&self, _request: GetPersonsRequest) -> Result<PersonsResponse, Status> {
        self.check_error()?;
        Ok(PersonsResponse {
            persons: vec![],
            missing_ids: vec![],
        })
    }

    async fn get_person_by_uuid(
        &self,
        _request: GetPersonByUuidRequest,
    ) -> Result<GetPersonResponse, Status> {
        self.check_error()?;
        Ok(GetPersonResponse {
            person: self.person_response.lock().unwrap().clone(),
        })
    }

    async fn get_persons_by_uuids(
        &self,
        _request: GetPersonsByUuidsRequest,
    ) -> Result<PersonsResponse, Status> {
        self.check_error()?;
        Ok(PersonsResponse {
            persons: vec![],
            missing_ids: vec![],
        })
    }

    async fn get_person_by_distinct_id(
        &self,
        _request: GetPersonByDistinctIdRequest,
    ) -> Result<GetPersonResponse, Status> {
        self.check_error()?;
        Ok(GetPersonResponse {
            person: self.person_response.lock().unwrap().clone(),
        })
    }

    async fn get_persons_by_distinct_ids_in_team(
        &self,
        _request: GetPersonsByDistinctIdsInTeamRequest,
    ) -> Result<PersonsByDistinctIdsInTeamResponse, Status> {
        self.check_error()?;
        Ok(PersonsByDistinctIdsInTeamResponse { results: vec![] })
    }

    async fn get_persons_by_distinct_ids(
        &self,
        _request: GetPersonsByDistinctIdsRequest,
    ) -> Result<PersonsByDistinctIdsResponse, Status> {
        self.check_error()?;
        Ok(PersonsByDistinctIdsResponse { results: vec![] })
    }

    async fn get_distinct_ids_for_person(
        &self,
        _request: GetDistinctIdsForPersonRequest,
    ) -> Result<GetDistinctIdsForPersonResponse, Status> {
        self.check_error()?;
        Ok(GetDistinctIdsForPersonResponse {
            distinct_ids: vec![],
        })
    }

    async fn get_distinct_ids_for_persons(
        &self,
        _request: GetDistinctIdsForPersonsRequest,
    ) -> Result<GetDistinctIdsForPersonsResponse, Status> {
        self.check_error()?;
        Ok(GetDistinctIdsForPersonsResponse {
            person_distinct_ids: vec![],
        })
    }

    async fn get_hash_key_override_context(
        &self,
        _request: GetHashKeyOverrideContextRequest,
    ) -> Result<GetHashKeyOverrideContextResponse, Status> {
        self.check_error()?;
        Ok(GetHashKeyOverrideContextResponse { results: vec![] })
    }

    async fn upsert_hash_key_overrides(
        &self,
        _request: UpsertHashKeyOverridesRequest,
    ) -> Result<UpsertHashKeyOverridesResponse, Status> {
        self.check_error()?;
        Ok(UpsertHashKeyOverridesResponse { inserted_count: 0 })
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        _request: DeleteHashKeyOverridesByTeamsRequest,
    ) -> Result<DeleteHashKeyOverridesByTeamsResponse, Status> {
        self.check_error()?;
        Ok(DeleteHashKeyOverridesByTeamsResponse { deleted_count: 0 })
    }

    async fn delete_persons(
        &self,
        _request: DeletePersonsRequest,
    ) -> Result<DeletePersonsResponse, Status> {
        self.check_error()?;
        Ok(DeletePersonsResponse { deleted_count: 0 })
    }

    async fn delete_persons_batch_for_team(
        &self,
        _request: DeletePersonsBatchForTeamRequest,
    ) -> Result<DeletePersonsBatchForTeamResponse, Status> {
        self.check_error()?;
        Ok(DeletePersonsBatchForTeamResponse { deleted_count: 0 })
    }

    async fn check_cohort_membership(
        &self,
        _request: CheckCohortMembershipRequest,
    ) -> Result<CohortMembershipResponse, Status> {
        self.check_error()?;
        Ok(CohortMembershipResponse {
            memberships: vec![],
        })
    }

    async fn count_cohort_members(
        &self,
        _request: CountCohortMembersRequest,
    ) -> Result<CountCohortMembersResponse, Status> {
        self.check_error()?;
        Ok(CountCohortMembersResponse { count: 0 })
    }

    async fn delete_cohort_member(
        &self,
        _request: DeleteCohortMemberRequest,
    ) -> Result<DeleteCohortMemberResponse, Status> {
        self.check_error()?;
        Ok(DeleteCohortMemberResponse { deleted: false })
    }

    async fn delete_cohort_members_bulk(
        &self,
        _request: DeleteCohortMembersBulkRequest,
    ) -> Result<DeleteCohortMembersBulkResponse, Status> {
        self.check_error()?;
        Ok(DeleteCohortMembersBulkResponse { deleted_count: 0 })
    }

    async fn insert_cohort_members(
        &self,
        _request: InsertCohortMembersRequest,
    ) -> Result<InsertCohortMembersResponse, Status> {
        self.check_error()?;
        Ok(InsertCohortMembersResponse { inserted_count: 0 })
    }

    async fn list_cohort_member_ids(
        &self,
        _request: ListCohortMemberIdsRequest,
    ) -> Result<ListCohortMemberIdsResponse, Status> {
        self.check_error()?;
        Ok(ListCohortMemberIdsResponse {
            person_ids: vec![],
            next_cursor: 0,
        })
    }

    async fn get_group(&self, _request: GetGroupRequest) -> Result<GetGroupResponse, Status> {
        self.check_error()?;
        Ok(GetGroupResponse { group: None })
    }

    async fn get_groups(&self, _request: GetGroupsRequest) -> Result<GroupsResponse, Status> {
        self.check_error()?;
        Ok(GroupsResponse {
            groups: vec![],
            missing_groups: vec![],
        })
    }

    async fn get_groups_batch(
        &self,
        _request: GetGroupsBatchRequest,
    ) -> Result<GetGroupsBatchResponse, Status> {
        self.check_error()?;
        Ok(GetGroupsBatchResponse { results: vec![] })
    }

    async fn get_group_type_mappings_by_team_id(
        &self,
        _request: GetGroupTypeMappingsByTeamIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        self.check_error()?;
        Ok(GroupTypeMappingsResponse { mappings: vec![] })
    }

    async fn get_group_type_mappings_by_team_ids(
        &self,
        _request: GetGroupTypeMappingsByTeamIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        self.check_error()?;
        Ok(GroupTypeMappingsBatchResponse { results: vec![] })
    }

    async fn get_group_type_mappings_by_project_id(
        &self,
        _request: GetGroupTypeMappingsByProjectIdRequest,
    ) -> Result<GroupTypeMappingsResponse, Status> {
        self.check_error()?;
        Ok(GroupTypeMappingsResponse { mappings: vec![] })
    }

    async fn get_group_type_mappings_by_project_ids(
        &self,
        _request: GetGroupTypeMappingsByProjectIdsRequest,
    ) -> Result<GroupTypeMappingsBatchResponse, Status> {
        self.check_error()?;
        Ok(GroupTypeMappingsBatchResponse { results: vec![] })
    }
}
