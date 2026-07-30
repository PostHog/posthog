use async_trait::async_trait;
use tonic::Status;

use personhog_common::client::RouterClient;
use personhog_proto::personhog::types::v1::{
    UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
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
