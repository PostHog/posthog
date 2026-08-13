use std::time::Duration;

use anyhow::{Context, Result};
use personhog_common::client::RouterClient;
use personhog_proto::personhog::{
    identity::v1::{
        person_hog_identity_client::PersonHogIdentityClient, GetOrCreatePersonEntry,
        GetOrCreatePersonResult, GetOrCreatePersonsByDistinctIdsRequest,
    },
    lifecycle::v1::{
        person_hog_lifecycle_client::PersonHogLifecycleClient, DeletePersonOutcome,
        DeletePersonsRequest,
    },
    types::v1::{
        ConsistencyLevel, FencePersonRequest, FencePersonResponse, LifecycleOpType, Person,
        ReleaseFenceRequest, ReleaseOutcome, UpdatePersonPropertiesRequest,
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
        Self::connect_with_channels(url, 1).await
    }

    /// Connect over `channels` router connections, selected round-robin.
    /// Load-driving scenarios pass more than one so an instance spreads
    /// across router pods instead of pinning to whichever pod its single
    /// connection landed on.
    pub async fn connect_with_channels(url: &str, channels: usize) -> Result<Self> {
        let inner = RouterClient::with_channels(url, REQUEST_TIMEOUT, channels)
            .context("invalid router URL")?;
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

    /// Fence a person for a delete op, returning the sealed version.
    pub async fn fence_person(
        &self,
        team_id: i64,
        person_id: i64,
        op_id: &uuid::Uuid,
    ) -> Result<FencePersonResponse> {
        self.inner
            .fence_person(FencePersonRequest {
                team_id,
                person_id,
                op_id: op_id.to_string(),
                op_type: LifecycleOpType::Delete.into(),
            })
            .await
            .context("FencePerson failed")
    }

    /// Release a fence with the aborted outcome: the person resumes life.
    pub async fn release_fence_aborted(
        &self,
        team_id: i64,
        person_id: i64,
        op_id: &uuid::Uuid,
    ) -> Result<()> {
        self.inner
            .release_fence(ReleaseFenceRequest {
                team_id,
                person_id,
                person_uuid: String::new(),
                op_id: op_id.to_string(),
                outcome: ReleaseOutcome::Aborted.into(),
                sealed_version: None,
                created_at: 0,
            })
            .await
            .context("ReleaseFence failed")?;
        Ok(())
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
                is_identified: None,
                last_seen_at: None,
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

/// Client for the lifecycle saga service, co-served on the identity
/// server's address.
#[derive(Clone)]
pub struct LifecycleClient {
    inner: PersonHogLifecycleClient<Channel>,
}

impl LifecycleClient {
    pub async fn connect(url: &str) -> Result<Self> {
        let channel = Channel::from_shared(url.to_string())
            .context("invalid lifecycle URL")?
            .timeout(REQUEST_TIMEOUT)
            .connect_timeout(Duration::from_secs(5))
            .tcp_nodelay(true)
            .connect_lazy();

        Ok(Self {
            inner: PersonHogLifecycleClient::new(channel),
        })
    }

    /// Destroy persons through the durable delete saga, returning each
    /// person's outcome. The op id is scoped to this attempt — never
    /// derived from the rows, which revive with the same id.
    pub async fn delete_persons(
        &self,
        team_id: i64,
        person_ids: Vec<i64>,
        op_id: &uuid::Uuid,
    ) -> Result<Vec<(i64, DeletePersonOutcome)>> {
        let resp = self
            .inner
            .clone()
            .delete_persons(Request::new(DeletePersonsRequest {
                team_id,
                person_ids,
                op_id: op_id.to_string(),
            }))
            .await
            .context("DeletePersons failed")?;
        Ok(resp
            .into_inner()
            .results
            .into_iter()
            .map(|result| (result.person_id, result.outcome()))
            .collect())
    }
}
