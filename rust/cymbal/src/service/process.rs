use std::{pin::Pin, sync::Arc, time::Instant};

use cymbal_proto::cymbal::process::v1::{
    cymbal_process_server::CymbalProcess, process_outcome, ProcessBatchRequest,
    ProcessBatchResponse, ProcessError, ProcessErrorKind, ProcessItem, ProcessOutcome,
    ServiceState, SubscribeRequest,
};
use futures::{Stream, StreamExt};
use tokio::sync::{mpsc, Semaphore};
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status, Streaming};
use tracing::warn;
use uuid::Uuid;

use crate::metric_consts::{
    PROCESS_SERVICE_IN_FLIGHT_ITEMS, PROCESS_SERVICE_ITEM_DURATION_SECONDS,
    PROCESS_SERVICE_STREAMS_TOTAL, PROCESS_SERVICE_TERMINAL_OUTCOMES_TOTAL,
};

#[derive(Clone, Debug)]
pub struct ProcessServiceConfig {
    pub stream_output_buffer: usize,
}

impl ProcessServiceConfig {
    pub fn new(stream_output_buffer: usize) -> Self {
        Self {
            stream_output_buffer: stream_output_buffer.max(1),
        }
    }
}

#[derive(Clone)]
pub struct CymbalProcessService {
    config: ProcessServiceConfig,
    item_limiter: Arc<Semaphore>,
}

impl CymbalProcessService {
    pub fn new(config: ProcessServiceConfig, item_limiter: Arc<Semaphore>) -> Self {
        Self {
            config,
            item_limiter,
        }
    }
}

type ProcessResponseStream =
    Pin<Box<dyn Stream<Item = Result<ProcessOutcome, Status>> + Send + 'static>>;
type SubscribeResponseStream =
    Pin<Box<dyn Stream<Item = Result<ServiceState, Status>> + Send + 'static>>;

#[tonic::async_trait]
impl CymbalProcess for CymbalProcessService {
    type ProcessStreamStream = ProcessResponseStream;
    type SubscribeStream = SubscribeResponseStream;

    async fn process_stream(
        &self,
        request: Request<Streaming<ProcessItem>>,
    ) -> Result<Response<Self::ProcessStreamStream>, Status> {
        let (tx, rx) = mpsc::channel(self.config.stream_output_buffer);
        let input = request.into_inner();
        let item_limiter = self.item_limiter.clone();

        tokio::spawn(async move {
            run_process(input, tx, item_limiter).await;
        });

        Ok(Response::new(Box::pin(ReceiverStream::new(rx))))
    }

    async fn process_batch(
        &self,
        request: Request<ProcessBatchRequest>,
    ) -> Result<Response<ProcessBatchResponse>, Status> {
        let request = request.into_inner();
        let mut outcomes = Vec::with_capacity(request.items.len());

        for mut item in request.items {
            if item.timeout_ms.is_none() {
                item.timeout_ms = request.timeout_ms;
            }
            outcomes.push(process_item_with_limiter(item, self.item_limiter.clone()).await);
        }

        Ok(Response::new(ProcessBatchResponse { outcomes }))
    }

    async fn subscribe(
        &self,
        _request: Request<SubscribeRequest>,
    ) -> Result<Response<Self::SubscribeStream>, Status> {
        let (tx, rx) = mpsc::channel(1);
        tokio::spawn(async move {
            let _ignored = tx
                .send(Ok(ServiceState {
                    service_instance_id: std::env::var("HOSTNAME")
                        .unwrap_or_else(|_| "cymbal-process".to_string()),
                    draining: false,
                    healthy: true,
                    sequence: 1,
                    message: "ready".to_string(),
                }))
                .await;
        });

        Ok(Response::new(Box::pin(ReceiverStream::new(rx))))
    }
}

async fn run_process<S>(
    mut input: S,
    tx: mpsc::Sender<Result<ProcessOutcome, Status>>,
    item_limiter: Arc<Semaphore>,
) where
    S: Stream<Item = Result<ProcessItem, Status>> + Unpin,
{
    metrics::counter!(PROCESS_SERVICE_STREAMS_TOTAL, "event" => "opened").increment(1);
    let mut item_tasks = tokio::task::JoinSet::new();

    loop {
        tokio::select! {
            _ = tx.closed() => {
                metrics::counter!(PROCESS_SERVICE_STREAMS_TOTAL, "event" => "closed", "reason" => "cancelled").increment(1);
                return;
            }
            maybe_item = input.next() => {
                let item = match maybe_item {
                    Some(Ok(item)) => item,
                    Some(Err(err)) => {
                        warn!(error = %err, "process gRPC input stream failed");
                        metrics::counter!(PROCESS_SERVICE_STREAMS_TOTAL, "event" => "closed", "reason" => "input_error").increment(1);
                        return;
                    }
                    None => break,
                };

                let item_limiter = item_limiter.clone();
                let item_tx = tx.clone();
                item_tasks.spawn(async move {
                    let outcome = process_item_with_limiter(item, item_limiter).await;
                    let _ignored = item_tx.send(Ok(outcome)).await;
                });
            }
        }
    }

    while item_tasks.join_next().await.is_some() {}
    metrics::counter!(PROCESS_SERVICE_STREAMS_TOTAL, "event" => "closed", "reason" => "completed")
        .increment(1);
}

struct ProcessServiceInFlightGuard;

impl ProcessServiceInFlightGuard {
    fn start() -> Self {
        metrics::gauge!(PROCESS_SERVICE_IN_FLIGHT_ITEMS).increment(1.0);
        Self
    }
}

impl Drop for ProcessServiceInFlightGuard {
    fn drop(&mut self) {
        metrics::gauge!(PROCESS_SERVICE_IN_FLIGHT_ITEMS).decrement(1.0);
    }
}

async fn process_item_with_limiter(
    item: ProcessItem,
    item_limiter: Arc<Semaphore>,
) -> ProcessOutcome {
    let started_at = Instant::now();
    let global_permit = match item_limiter.try_acquire_owned() {
        Ok(permit) => permit,
        Err(_) => {
            let outcome = error_outcome(
                item.id,
                ProcessErrorKind::Overloaded,
                true,
                0,
                "process global item concurrency limit reached",
            );
            record_terminal_outcome(&outcome, started_at);
            return outcome;
        }
    };

    let _global_permit = global_permit;
    let _in_flight = ProcessServiceInFlightGuard::start();
    process_item_placeholder(Uuid::now_v7(), item).await
}

async fn process_item_placeholder(processing_id: Uuid, item: ProcessItem) -> ProcessOutcome {
    let started_at = Instant::now();
    let caller_id = item.id;
    let timeout_caller_id = caller_id.clone();

    let process_future = async move {
        warn!(
            processing_id = %processing_id,
            caller_id = %caller_id,
            "process gRPC pipeline adapter is not implemented yet"
        );
        error_outcome(
            caller_id,
            ProcessErrorKind::Unimplemented,
            false,
            0,
            "cymbal process gRPC pipeline adapter is not implemented yet",
        )
    };

    let outcome = match item.timeout_ms {
        Some(timeout_ms) => tokio::time::timeout(
            std::time::Duration::from_millis(timeout_ms as u64),
            process_future,
        )
        .await
        .unwrap_or_else(|_| {
            error_outcome(
                timeout_caller_id,
                ProcessErrorKind::Timeout,
                true,
                0,
                "process item deadline expired",
            )
        }),
        None => process_future.await,
    };

    record_terminal_outcome(&outcome, started_at);
    outcome
}

fn error_outcome(
    id: String,
    kind: ProcessErrorKind,
    retryable: bool,
    retry_after_ms: u32,
    message: impl Into<String>,
) -> ProcessOutcome {
    ProcessOutcome {
        id,
        result: Some(process_outcome::Result::Error(ProcessError {
            kind: kind as i32,
            retryable,
            retry_after_ms,
            message: message.into(),
            details_json: Vec::new(),
        })),
    }
}

fn record_terminal_outcome(outcome: &ProcessOutcome, started_at: Instant) {
    let (outcome_type, kind) = match outcome.result.as_ref() {
        Some(process_outcome::Result::Done(_)) => ("done", "ok"),
        Some(process_outcome::Result::Drop(drop)) => (
            "drop",
            cymbal_proto::cymbal::process::v1::ProcessDropReason::try_from(drop.reason)
                .unwrap_or(cymbal_proto::cymbal::process::v1::ProcessDropReason::Unspecified)
                .as_str_name(),
        ),
        Some(process_outcome::Result::Error(error)) => (
            "error",
            ProcessErrorKind::try_from(error.kind)
                .unwrap_or(ProcessErrorKind::Unspecified)
                .as_str_name(),
        ),
        None => ("error", "missing_result"),
    };

    metrics::counter!(
        PROCESS_SERVICE_TERMINAL_OUTCOMES_TOTAL,
        "type" => outcome_type,
        "kind" => kind,
    )
    .increment(1);
    metrics::histogram!(
        PROCESS_SERVICE_ITEM_DURATION_SECONDS,
        "type" => outcome_type,
        "kind" => kind,
    )
    .record(started_at.elapsed().as_secs_f64());
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::stream;

    #[tokio::test]
    async fn placeholder_echoes_duplicate_caller_ids_with_unimplemented_errors() {
        let (tx, mut rx) = mpsc::channel(4);
        let input = stream::iter(vec![
            Ok(ProcessItem {
                id: "duplicate".to_string(),
                event_json: b"{}".to_vec(),
                timeout_ms: Some(1_000),
            }),
            Ok(ProcessItem {
                id: "duplicate".to_string(),
                event_json: b"{}".to_vec(),
                timeout_ms: Some(1_000),
            }),
        ]);

        run_process(input, tx, Arc::new(Semaphore::new(2))).await;

        let mut outcomes = Vec::new();
        while let Some(Ok(outcome)) = rx.recv().await {
            outcomes.push(outcome);
        }

        assert_eq!(outcomes.len(), 2);
        for outcome in outcomes {
            assert_eq!(outcome.id, "duplicate");
            let Some(process_outcome::Result::Error(error)) = outcome.result else {
                panic!("expected error outcome");
            };
            assert_eq!(error.kind, ProcessErrorKind::Unimplemented as i32);
            assert!(!error.retryable);
        }
    }
}
