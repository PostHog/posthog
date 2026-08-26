//! Transport selection: HTTP request/response vs ordered gRPC worker streams.
//!
//! The consumer talks to workers through one [`Transport`], picked by
//! `INGESTION_TRANSPORT`. Sends are two-phase everywhere: [`Transport::begin_send`]
//! establishes send order and must be called where that order is decided (the
//! consumer loop right after assignment, or the serialized flush paths);
//! [`PendingSend::wait`] resolves like an HTTP response. The HTTP transport
//! implements `begin_send` lazily (nothing happens until `wait`), which keeps
//! its behavior identical to the direct `send_batch` call it replaces; the
//! gRPC transport enqueues synchronously onto the worker's ordered stream.

use std::str::FromStr;
use std::sync::Arc;

use crate::grpc_transport::{GrpcTransport, PendingWorkerStreamSend};
use crate::transport::{HttpTransport, SendError};
use crate::types::SerializedKafkaMessage;

/// Which transport carries sub-batches to the workers.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum TransportMode {
    #[default]
    Http,
    Grpc,
}

impl FromStr for TransportMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "http" => Ok(TransportMode::Http),
            "grpc" => Ok(TransportMode::Grpc),
            other => Err(format!(
                "unknown ingestion transport '{other}' (expected 'http' or 'grpc')"
            )),
        }
    }
}

impl TransportMode {
    pub fn as_str(&self) -> &'static str {
        match self {
            TransportMode::Http => "http",
            TransportMode::Grpc => "grpc",
        }
    }
}

/// The consumer's worker transport.
pub enum Transport {
    Http(Arc<HttpTransport>),
    Grpc(Arc<GrpcTransport>),
}

/// A sub-batch whose send order is established; await it for the outcome.
pub enum PendingSend {
    Http {
        transport: Arc<HttpTransport>,
        worker_url: String,
        batch_id: String,
        messages: Vec<SerializedKafkaMessage>,
        replay: bool,
    },
    Grpc(PendingWorkerStreamSend),
}

impl PendingSend {
    pub async fn wait(self) -> Result<u32, SendError> {
        match self {
            PendingSend::Http {
                transport,
                worker_url,
                batch_id,
                messages,
                replay,
            } => {
                transport
                    .send_batch(&worker_url, &batch_id, messages, replay)
                    .await
            }
            PendingSend::Grpc(pending) => pending.wait().await,
        }
    }
}

impl Transport {
    /// Establish send order for a sub-batch. Synchronous — call it in the
    /// order sends must reach the worker; the per-key ordering guarantee on
    /// the gRPC path is exactly "begin_send order per worker".
    pub fn begin_send(
        &self,
        worker_url: &str,
        batch_id: &str,
        messages: Vec<SerializedKafkaMessage>,
        replay: bool,
    ) -> PendingSend {
        match self {
            Transport::Http(transport) => PendingSend::Http {
                transport: Arc::clone(transport),
                worker_url: worker_url.to_string(),
                batch_id: batch_id.to_string(),
                messages,
                replay,
            },
            Transport::Grpc(transport) => {
                PendingSend::Grpc(transport.begin_send(worker_url, batch_id, messages, replay))
            }
        }
    }

    pub async fn wait_for_workers_ready(
        &self,
        worker_urls: &[String],
        shutdown: &lifecycle::Handle,
    ) -> anyhow::Result<()> {
        match self {
            Transport::Http(transport) => {
                transport
                    .wait_for_workers_ready(worker_urls, shutdown)
                    .await
            }
            Transport::Grpc(transport) => {
                transport
                    .wait_for_workers_ready(worker_urls, shutdown)
                    .await
            }
        }
    }

    /// Drop a departed worker's transport state (semaphore or worker stream).
    pub fn remove_worker(&self, worker_url: &str) {
        match self {
            Transport::Http(transport) => transport.remove_worker(worker_url),
            Transport::Grpc(transport) => transport.remove_worker(worker_url),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_transport_mode_parses_known_values() {
        assert_eq!("http".parse(), Ok(TransportMode::Http));
        assert_eq!(" gRPC ".parse(), Ok(TransportMode::Grpc));
        assert!("carrier-pigeon".parse::<TransportMode>().is_err());
        assert_eq!(TransportMode::default(), TransportMode::Http);
    }
}
