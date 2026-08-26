//! In-process usage-ingestion server for tests. `usage-ingestion-proto` builds the server
//! stubs alongside the client, so a test can watch what the reporter actually sent instead
//! of asserting that a counter moved.

use std::collections::VecDeque;
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};

use tonic::{Code, Request, Response, Status};
use usage_ingestion_proto::usage_ingestion::v1::usage_ingestion_server::{
    UsageIngestion, UsageIngestionServer,
};
use usage_ingestion_proto::usage_ingestion::v1::{
    BillingUsageRecord, IngestBillingUsageRequest, IngestBillingUsageResponse,
};

/// Records every request, and answers with the queued codes before it starts accepting.
#[derive(Clone, Default)]
pub struct RecordingIngestion {
    requests: Arc<Mutex<Vec<Vec<BillingUsageRecord>>>>,
    replies: Arc<Mutex<VecDeque<Code>>>,
}

impl RecordingIngestion {
    /// Fails the next request with `code`. Queue more than one to fail more attempts.
    pub fn fail_next(&self, code: Code) {
        self.replies.lock().unwrap().push_back(code);
    }

    /// One entry per request received, in arrival order.
    pub fn requests(&self) -> Vec<Vec<BillingUsageRecord>> {
        self.requests.lock().unwrap().clone()
    }
}

#[tonic::async_trait]
impl UsageIngestion for RecordingIngestion {
    async fn ingest_billing_usage(
        &self,
        request: Request<IngestBillingUsageRequest>,
    ) -> Result<Response<IngestBillingUsageResponse>, Status> {
        let records = request.into_inner().records;
        let accepted_record_ids = records
            .iter()
            .map(|record| record.record_id.clone())
            .collect();
        self.requests.lock().unwrap().push(records);
        if let Some(code) = self.replies.lock().unwrap().pop_front() {
            return Err(Status::new(code, "test"));
        }
        Ok(Response::new(IngestBillingUsageResponse {
            accepted_record_ids,
        }))
    }
}

/// Serves `service` on an ephemeral port and returns its address. The listener is bound
/// before this returns, so a client can connect while the server task is still starting.
pub async fn serve(service: RecordingIngestion) -> SocketAddr {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        tonic::transport::Server::builder()
            .add_service(UsageIngestionServer::new(service))
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    });
    addr
}
