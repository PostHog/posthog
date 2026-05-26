//! Per-call remote stage client and the connection options it depends on.
//!
//! [`RemoteStageClient`] is a short-lived wrapper around a shared tonic
//! `Channel`. The connection manager owns long-lived channels; here we only
//! deal with one batch at a time: build the `StageBatch` envelope, dispatch it
//! to the configured stage, and surface the raw `StageBatchResult` (including
//! any trailer-borne `StageLoad`).

use std::time::Duration;

use cymbal_api::cymbal::v1::cymbal_stage_runtime_client::CymbalStageRuntimeClient;
use cymbal_api::cymbal::v1::{StageBatch, StageBatchResult, StageItem, StageStart};
use cymbal_core::{BatchContext, StageType};
use tonic::transport::{Channel, Endpoint};
use tonic::Status;

#[derive(Debug, Clone)]
pub struct RemoteStageConfig {
    pub endpoint: String,
    pub stage_id: String,
    pub input_type: String,
    pub output_type: String,
}

impl RemoteStageConfig {
    pub fn new(
        endpoint: impl Into<String>,
        stage_id: impl Into<String>,
        input_type: StageType,
        output_type: StageType,
    ) -> Self {
        Self {
            endpoint: endpoint.into(),
            stage_id: stage_id.into(),
            input_type: input_type.to_string(),
            output_type: output_type.to_string(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct RemoteStageConnectionOptions {
    pub connect_timeout: Duration,
    pub tcp_keepalive: Option<Duration>,
    pub http2_keep_alive_interval: Option<Duration>,
    pub keep_alive_timeout: Duration,
    pub stage_timeout: Option<Duration>,
}

impl Default for RemoteStageConnectionOptions {
    fn default() -> Self {
        Self {
            connect_timeout: Duration::from_secs(5),
            tcp_keepalive: Some(Duration::from_secs(30)),
            http2_keep_alive_interval: Some(Duration::from_secs(30)),
            keep_alive_timeout: Duration::from_secs(10),
            stage_timeout: Some(Duration::from_secs(30)),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RemoteStageItem {
    pub item_id: String,
    pub item_type: String,
    pub payload: Vec<u8>,
}

impl RemoteStageItem {
    pub fn new(item_id: impl Into<String>, item_type: StageType, payload: Vec<u8>) -> Self {
        Self {
            item_id: item_id.into(),
            item_type: item_type.to_string(),
            payload,
        }
    }
}

#[derive(Debug, Clone)]
pub struct RemoteStageClient {
    config: RemoteStageConfig,
    client: CymbalStageRuntimeClient<Channel>,
}

impl RemoteStageClient {
    pub async fn connect(config: RemoteStageConfig) -> Result<Self, tonic::transport::Error> {
        let channel = Endpoint::from_shared(config.endpoint.clone())?
            .connect_timeout(RemoteStageConnectionOptions::default().connect_timeout)
            .connect()
            .await?;
        Ok(Self::from_channel(config, channel))
    }

    pub fn from_channel(config: RemoteStageConfig, channel: Channel) -> Self {
        Self {
            config,
            client: CymbalStageRuntimeClient::new(channel),
        }
    }

    pub async fn process_items(
        &mut self,
        context: BatchContext,
        items: Vec<RemoteStageItem>,
    ) -> Result<StageBatchResult, Status> {
        let start = StageStart {
            batch_id: context.batch_id,
            stage_id: self.config.stage_id.clone(),
            input_type: self.config.input_type.clone(),
            output_type: self.config.output_type.clone(),
            metadata: context.metadata,
        };
        let item_count = items.len();
        let items = items
            .into_iter()
            .map(|item| StageItem {
                item_id: item.item_id,
                r#type: item.item_type,
                payload: item.payload,
            })
            .collect::<Vec<_>>();
        tracing::debug!(
            stage_id = %self.config.stage_id,
            input_type = %self.config.input_type,
            output_type = %self.config.output_type,
            items = item_count,
            "sending remote stage batch"
        );
        let request = StageBatch {
            start: Some(start),
            items,
        };

        self.client
            .process_stage(request)
            .await
            .map(|response| response.into_inner())
    }
}
