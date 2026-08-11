use async_trait::async_trait;
use tonic::Status;

use personhog_common::client::RouterClient;
use personhog_proto::personhog::types::v1::{
    FencePersonRequest, FencePersonResponse, FoldPersonDocumentRequest, FoldPersonDocumentResponse,
    ReleaseFenceRequest, ReleaseFenceResponse, UpdatePersonPropertiesRequest,
    UpdatePersonPropertiesResponse,
};

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

    async fn release_fence(
        &self,
        request: ReleaseFenceRequest,
    ) -> Result<ReleaseFenceResponse, Status>;

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

    async fn release_fence(
        &self,
        request: ReleaseFenceRequest,
    ) -> Result<ReleaseFenceResponse, Status> {
        RouterClient::release_fence(self, request).await
    }

    async fn fold_person_document(
        &self,
        request: FoldPersonDocumentRequest,
    ) -> Result<FoldPersonDocumentResponse, Status> {
        RouterClient::fold_person_document(self, request).await
    }
}
