use std::sync::Arc;

use tonic::{Request, Response, Status};
use usage_ingestion_proto::usage_ingestion::v1::{
    usage_ingestion_server::UsageIngestion, IngestBillingUsageRequest, IngestBillingUsageResponse,
};

use crate::service::{ProcessingError, UsageIngestionService};

pub struct GrpcUsageIngestion {
    service: Arc<UsageIngestionService>,
}

impl GrpcUsageIngestion {
    pub fn new(service: Arc<UsageIngestionService>) -> Self {
        Self { service }
    }
}

#[tonic::async_trait]
impl UsageIngestion for GrpcUsageIngestion {
    async fn ingest_billing_usage(
        &self,
        request: Request<IngestBillingUsageRequest>,
    ) -> Result<Response<IngestBillingUsageResponse>, Status> {
        self.service
            .process(request.into_inner())
            .await
            .map(Response::new)
            .map_err(status)
    }
}

fn status(error: ProcessingError) -> Status {
    match error {
        ProcessingError::InvalidArgument(message) => Status::invalid_argument(message),
        ProcessingError::Unavailable(message) => Status::unavailable(message),
        ProcessingError::Internal(message) => Status::internal(message),
    }
}
