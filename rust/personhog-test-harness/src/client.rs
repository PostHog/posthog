use std::time::Duration;

use anyhow::{Context, Result};
use personhog_common::client::RouterClient;
use personhog_proto::personhog::{
    identity::v1::person_hog_identity_client::PersonHogIdentityClient,
    types::v1::{
        ConsistencyLevel, GetOrCreatePersonEntry, GetOrCreatePersonResult,
        GetOrCreatePersonsByDistinctIdsRequest, Person, UpdatePersonPropertiesRequest,
        UpdatePersonPropertiesResponse,
    },
};
use tonic::transport::Channel;
use tonic::Request;

const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);

/// Harness wrapper over the shared router client: same wire behavior,
/// anyhow-flavored results for scenario code.
#[derive(Clone)]
pub struct HarnessClient {
    inner: RouterClient,
}

impl HarnessClient {
    pub async fn connect(url: &str) -> Result<Self> {
        let inner = RouterClient::new(url, REQUEST_TIMEOUT).context("invalid router URL")?;
        Ok(Self { inner })
    }

    pub async fn get_person(
        &self,
        team_id: i64,
        person_id: i64,
        consistency: ConsistencyLevel,
    ) -> Result<Option<Person>> {
        self.inner
            .get_person(team_id, person_id, consistency)
            .await
            .context("GetPerson failed")
    }

    pub async fn update_properties(
        &self,
        team_id: i64,
        person_id: i64,
        set_properties: serde_json::Value,
        set_once_properties: serde_json::Value,
        unset_properties: Vec<String>,
    ) -> Result<UpdatePersonPropertiesResponse> {
        self.inner
            .update_person_properties(UpdatePersonPropertiesRequest {
                team_id,
                person_id,
                event_name: "$set".to_string(),
                set_properties: serde_json::to_vec(&set_properties)?,
                set_once_properties: serde_json::to_vec(&set_once_properties)?,
                unset_properties,
            })
            .await
            .context("UpdatePersonProperties failed")
    }
}

/// Client for the personhog-identity service — the get-or-create entry
/// point. Called directly, not through the router, so no routing headers.
#[derive(Clone)]
pub struct IdentityClient {
    inner: PersonHogIdentityClient<Channel>,
}

impl IdentityClient {
    pub async fn connect(url: &str) -> Result<Self> {
        let channel = Channel::from_shared(url.to_string())
            .context("invalid identity URL")?
            .timeout(REQUEST_TIMEOUT)
            .connect_timeout(Duration::from_secs(5))
            .tcp_nodelay(true)
            .connect_lazy();

        Ok(Self {
            inner: PersonHogIdentityClient::new(channel),
        })
    }

    pub async fn get_or_create_persons(
        &self,
        entries: Vec<GetOrCreatePersonEntry>,
    ) -> Result<Vec<GetOrCreatePersonResult>> {
        let resp = self
            .inner
            .clone()
            .get_or_create_persons_by_distinct_ids(Request::new(
                GetOrCreatePersonsByDistinctIdsRequest { entries },
            ))
            .await
            .context("GetOrCreatePersonsByDistinctIds failed")?;
        Ok(resp.into_inner().results)
    }
}
