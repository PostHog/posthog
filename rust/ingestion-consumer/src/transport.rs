use std::collections::HashMap;
use std::time::Duration;

use async_trait::async_trait;
use tonic::transport::Channel;
use tracing::{info, warn};

use crate::error::IngestionError;
use crate::types::{IngestBatchRequest, IngestionServiceClient, KafkaMessage};

#[async_trait]
pub trait IngestionTransport: Send + Sync {
    async fn send_batch(
        &self,
        target: &str,
        messages: Vec<KafkaMessage>,
    ) -> Result<(), IngestionError>;
}

pub struct GrpcTransport {
    clients: HashMap<String, IngestionServiceClient<Channel>>,
    max_retries: u32,
}

impl GrpcTransport {
    pub async fn new(
        targets: &[String],
        timeout: Duration,
        max_retries: u32,
    ) -> Result<Self, IngestionError> {
        let mut clients = HashMap::new();

        for target in targets {
            let channel = Channel::from_shared(target.clone())
                .map_err(|e| IngestionError::Transport {
                    target: target.clone(),
                    source: anyhow::anyhow!("invalid URI: {e}"),
                })?
                .timeout(timeout)
                .connect_timeout(Duration::from_secs(5))
                .connect_lazy();

            clients.insert(target.clone(), IngestionServiceClient::new(channel));
            info!(target, "gRPC channel created");
        }

        Ok(Self {
            clients,
            max_retries,
        })
    }
}

fn should_retry(code: tonic::Code) -> bool {
    matches!(
        code,
        tonic::Code::Unavailable | tonic::Code::DeadlineExceeded
    )
}

#[async_trait]
impl IngestionTransport for GrpcTransport {
    async fn send_batch(
        &self,
        target: &str,
        messages: Vec<KafkaMessage>,
    ) -> Result<(), IngestionError> {
        let mut client = self
            .clients
            .get(target)
            .ok_or_else(|| IngestionError::Transport {
                target: target.to_string(),
                source: anyhow::anyhow!("no gRPC client for target"),
            })?
            .clone();

        let request = IngestBatchRequest { messages };
        let mut backoff = Duration::from_millis(100);
        let max_backoff = Duration::from_secs(30);

        for attempt in 0..=self.max_retries {
            let result = client
                .ingest_batch(tonic::Request::new(request.clone()))
                .await;

            match result {
                Ok(response) => {
                    let resp = response.into_inner();
                    if resp.status == 0 {
                        return Ok(());
                    }
                    return Err(IngestionError::Transport {
                        target: target.to_string(),
                        source: anyhow::anyhow!("server returned error: {}", resp.error),
                    });
                }
                Err(status) => {
                    if should_retry(status.code()) && attempt < self.max_retries {
                        warn!(
                            attempt,
                            code = ?status.code(),
                            target,
                            "retryable gRPC error, backing off"
                        );
                        tokio::time::sleep(backoff).await;
                        backoff = (backoff * 2).min(max_backoff);
                        continue;
                    }

                    return Err(IngestionError::Grpc {
                        target: target.to_string(),
                        status,
                    });
                }
            }
        }

        info!(target, "all retries exhausted");
        Err(IngestionError::RetriesExhausted {
            target: target.to_string(),
        })
    }
}
