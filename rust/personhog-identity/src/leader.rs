use async_trait::async_trait;
use tonic::{Code, Status};

use personhog_common::client::RouterClient;
use personhog_proto::personhog::types::v1::{
    ConsistencyLevel, FencePersonRequest, FencePersonResponse, FencePersonsRequest,
    FencePersonsResponse, FoldPersonDocumentRequest, FoldPersonDocumentResponse,
    ReleaseFenceRequest, ReleaseFenceResponse, ReleaseFencesRequest, ReleaseFencesResponse,
    UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};

/// The leader's view of a person's identified flag; identity's own row lags it through the writer.
#[async_trait]
pub trait PersonStateReader: Send + Sync {
    /// `None` when the leader holds no live person under the id.
    async fn is_identified(&self, team_id: i64, person_id: i64) -> Result<Option<bool>, Status>;
}

#[async_trait]
impl PersonStateReader for RouterClient {
    async fn is_identified(&self, team_id: i64, person_id: i64) -> Result<Option<bool>, Status> {
        match RouterClient::get_person(self, team_id, person_id, ConsistencyLevel::Strong).await {
            Ok(person) => Ok(person.map(|person| person.is_identified)),
            // The leader answers NOT_FOUND for a destroyed or absent person.
            Err(status) if status.code() == Code::NotFound => Ok(None),
            Err(status) => Err(status),
        }
    }
}

/// Writes initial person properties on the creation branch. Production goes
/// through the router (which routes to the owning leader); tests mock this.
#[async_trait]
pub trait PropertyWriter: Send + Sync {
    async fn update_person_properties(
        &self,
        request: UpdatePersonPropertiesRequest,
    ) -> Result<UpdatePersonPropertiesResponse, Status>;
}

#[async_trait]
impl PropertyWriter for RouterClient {
    async fn update_person_properties(
        &self,
        request: UpdatePersonPropertiesRequest,
    ) -> Result<UpdatePersonPropertiesResponse, Status> {
        RouterClient::update_person_properties(self, request).await
    }
}

/// The lifecycle sagas' leader surface: fence, release, and fold. Production
/// goes through the router (which routes each call to the owning leader);
/// tests mock this.
#[async_trait]
pub trait LifecycleLeader: Send + Sync {
    async fn fence_person(
        &self,
        request: FencePersonRequest,
    ) -> Result<FencePersonResponse, Status>;

    async fn fence_persons(
        &self,
        request: FencePersonsRequest,
    ) -> Result<FencePersonsResponse, Status>;

    async fn release_fence(
        &self,
        request: ReleaseFenceRequest,
    ) -> Result<ReleaseFenceResponse, Status>;

    async fn release_fences(
        &self,
        request: ReleaseFencesRequest,
    ) -> Result<ReleaseFencesResponse, Status>;

    async fn fold_person_document(
        &self,
        request: FoldPersonDocumentRequest,
    ) -> Result<FoldPersonDocumentResponse, Status>;
}

#[async_trait]
impl LifecycleLeader for RouterClient {
    async fn fence_person(
        &self,
        request: FencePersonRequest,
    ) -> Result<FencePersonResponse, Status> {
        RouterClient::fence_person(self, request).await
    }

    async fn fence_persons(
        &self,
        request: FencePersonsRequest,
    ) -> Result<FencePersonsResponse, Status> {
        RouterClient::fence_persons(self, request).await
    }

    async fn release_fence(
        &self,
        request: ReleaseFenceRequest,
    ) -> Result<ReleaseFenceResponse, Status> {
        RouterClient::release_fence(self, request).await
    }

    async fn release_fences(
        &self,
        request: ReleaseFencesRequest,
    ) -> Result<ReleaseFencesResponse, Status> {
        RouterClient::release_fences(self, request).await
    }

    async fn fold_person_document(
        &self,
        request: FoldPersonDocumentRequest,
    ) -> Result<FoldPersonDocumentResponse, Status> {
        RouterClient::fold_person_document(self, request).await
    }
}
