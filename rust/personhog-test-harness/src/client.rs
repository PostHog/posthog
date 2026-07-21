use std::time::Duration;

use anyhow::{Context, Result};
use personhog_proto::personhog::{
    service::v1::person_hog_service_client::PersonHogServiceClient,
    types::v1::{
        ConsistencyLevel, GetPersonRequest, Person, ReadOptions, UpdatePersonPropertiesRequest,
        UpdatePersonPropertiesResponse,
    },
};
use tonic::metadata::MetadataValue;
use tonic::transport::Channel;
use tonic::Request;

/// Routing headers the leader-mode router requires on leader-bound calls.
/// `UpdatePersonProperties` always routes to a leader; `GetPerson` routes to
/// a leader only when `x-read-consistency: strong` is present.
const TEAM_ID_HEADER: &str = "x-team-id";
const PERSON_ID_HEADER: &str = "x-person-id";
const READ_CONSISTENCY_HEADER: &str = "x-read-consistency";

#[derive(Clone)]
pub struct HarnessClient {
    inner: PersonHogServiceClient<Channel>,
}

impl HarnessClient {
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

    pub async fn get_person(
        &self,
        team_id: i64,
        person_id: i64,
        consistency: ConsistencyLevel,
    ) -> Result<Option<Person>> {
        let mut request = Request::new(GetPersonRequest {
            team_id,
            person_id,
            read_options: Some(ReadOptions {
                consistency: consistency.into(),
                ..Default::default()
            }),
        });
        if consistency == ConsistencyLevel::Strong {
            stamp_routing_headers(&mut request, team_id, person_id)?;
            request.metadata_mut().insert(
                READ_CONSISTENCY_HEADER,
                MetadataValue::from_static("strong"),
            );
        }

        let resp = self
            .inner
            .clone()
            .get_person(request)
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
        let mut request = Request::new(UpdatePersonPropertiesRequest {
            team_id,
            person_id,
            event_name: "$set".to_string(),
            set_properties: serde_json::to_vec(&set_properties)?,
            set_once_properties: serde_json::to_vec(&set_once_properties)?,
            unset_properties,
        });
        stamp_routing_headers(&mut request, team_id, person_id)?;

        let resp = self
            .inner
            .clone()
            .update_person_properties(request)
            .await
            .context("UpdatePersonProperties failed")?;

        Ok(resp.into_inner())
    }
}

fn stamp_routing_headers<T>(request: &mut Request<T>, team_id: i64, person_id: i64) -> Result<()> {
    let metadata = request.metadata_mut();
    metadata.insert(
        TEAM_ID_HEADER,
        MetadataValue::try_from(team_id.to_string()).context("invalid team id header")?,
    );
    metadata.insert(
        PERSON_ID_HEADER,
        MetadataValue::try_from(person_id.to_string()).context("invalid person id header")?,
    );
    Ok(())
}
