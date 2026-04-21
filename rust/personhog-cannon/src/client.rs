use anyhow::{Context, Result};
use personhog_proto::personhog::{
    service::v1::person_hog_service_client::PersonHogServiceClient,
    types::v1::{
        ConsistencyLevel, GetPersonRequest, GetPersonsByDistinctIdsInTeamRequest,
        GetPersonsRequest, Person, PersonWithDistinctIds, ReadOptions,
        UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
    },
};
use std::time::Duration;
use tonic::transport::Channel;

#[derive(Clone)]
pub struct CannonClient {
    inner: PersonHogServiceClient<Channel>,
}

impl CannonClient {
    pub async fn connect(url: &str) -> Result<Self> {
        let channel = Channel::from_shared(url.to_string())
            .context("invalid router URL")?
            .timeout(Duration::from_secs(10))
            .connect_timeout(Duration::from_secs(5))
            .tcp_nodelay(true)
            .connect_lazy();

        Ok(Self {
            inner: PersonHogServiceClient::new(channel),
        })
    }

    pub async fn discover_by_distinct_ids(
        &self,
        team_id: i64,
        distinct_ids: Vec<String>,
    ) -> Result<Vec<PersonWithDistinctIds>> {
        let resp = self
            .inner
            .clone()
            .get_persons_by_distinct_ids_in_team(GetPersonsByDistinctIdsInTeamRequest {
                team_id,
                distinct_ids,
                read_options: Some(ReadOptions {
                    consistency: ConsistencyLevel::Eventual.into(),
                }),
            })
            .await
            .context("GetPersonsByDistinctIdsInTeam failed")?;

        Ok(resp.into_inner().results)
    }

    pub async fn get_persons(&self, team_id: i64, person_ids: Vec<i64>) -> Result<Vec<Person>> {
        let resp = self
            .inner
            .clone()
            .get_persons(GetPersonsRequest {
                team_id,
                person_ids,
                read_options: Some(ReadOptions {
                    consistency: ConsistencyLevel::Eventual.into(),
                }),
            })
            .await
            .context("GetPersons failed")?;

        Ok(resp.into_inner().persons)
    }

    pub async fn get_person(
        &self,
        team_id: i64,
        person_id: i64,
        consistency: ConsistencyLevel,
    ) -> Result<Option<Person>> {
        let resp = self
            .inner
            .clone()
            .get_person(GetPersonRequest {
                team_id,
                person_id,
                read_options: Some(ReadOptions {
                    consistency: consistency.into(),
                }),
            })
            .await
            .context("GetPerson failed")?;

        Ok(resp.into_inner().person)
    }

    pub async fn update_properties(
        &self,
        team_id: i64,
        person_id: i64,
        set_properties: serde_json::Value,
        set_once_properties: serde_json::Value,
        unset_properties: Vec<String>,
    ) -> Result<UpdatePersonPropertiesResponse> {
        let resp = self
            .inner
            .clone()
            .update_person_properties(UpdatePersonPropertiesRequest {
                team_id,
                person_id,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&set_properties)?,
                set_once_properties: serde_json::to_vec(&set_once_properties)?,
                unset_properties,
                partition: 0, // router computes this
            })
            .await
            .context("UpdatePersonProperties failed")?;

        Ok(resp.into_inner())
    }
}
