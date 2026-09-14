use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use common_kafka_consumer::Partition;
use ingestion_consumer::batcher::{Batcher, BatcherOutputs};
use ingestion_consumer::dispatcher::Dispatcher;
use ingestion_consumer::grpc_transport::{GrpcPort, GrpcTransport};
use ingestion_consumer::routing::RoutingStrategy;
use ingestion_consumer::scheduler::SchedulerKind;
use ingestion_consumer::types::Accumulator;
use ingestion_consumer::worker_registry::{WorkerRegistry, WorkerRegistryConfig};
use ingestion_worker_proto::ingestion::worker::v1::worker_ingest_server::{
    WorkerIngest, WorkerIngestServer,
};
use ingestion_worker_proto::ingestion::worker::v1::{
    ingest_stream_request, ingest_stream_response, IngestStreamRequest, IngestStreamResponse,
    StreamReady, SubBatchAck, SubBatchStatus,
};
use lifecycle::{ComponentOptions, Manager, MonitorGuard};
use tokio::sync::{mpsc, oneshot};
use tokio::task::JoinHandle;
use tokio_stream::wrappers::UnboundedReceiverStream;
use tokio_stream::StreamExt;
use tokio_util::sync::CancellationToken;
use tonic::{Request, Response, Status, Streaming};

use super::msg;

/// Real key-table batcher, dispatcher and transport; only worker replies are controlled.
pub struct WatchdogHarness {
    batcher: Batcher,
    outputs: BatcherOutputs,
    attempts: Option<mpsc::UnboundedReceiver<HeldRequest>>,
    watchdog_deadline: Duration,
    lifecycle_shutdown: CancellationToken,
    worker_shutdown: CancellationToken,
    _servers: Vec<AbortOnDrop>,
    _monitor: MonitorGuard,
}

impl WatchdogHarness {
    pub async fn start(worker_count: usize, watchdog_deadline: Duration) -> Self {
        let (attempts_tx, attempts) = mpsc::unbounded_channel();
        let worker_shutdown = CancellationToken::new();
        let mut worker_urls = Vec::new();
        let mut servers = Vec::new();
        for worker in 0..worker_count {
            let (addr, server) =
                start_controlled_busy_worker(worker, attempts_tx.clone(), worker_shutdown.clone())
                    .await;
            worker_urls.push(format!("http://{addr}"));
            servers.push(server);
        }
        let registry = Arc::new(WorkerRegistry::new(&worker_urls, registry_config()));
        let dispatcher = Arc::new(Dispatcher::with_scheduler(
            registry,
            RoutingStrategy::BinPack,
            SchedulerKind::KeyTable,
        ));
        let transport = Arc::new(GrpcTransport::new(
            GrpcPort::OffsetFromHttp(0),
            1,
            Duration::from_secs(30),
        ));
        let mut manager = Manager::builder("key-table-watchdog-test")
            .with_trap_signals(false)
            .build();
        let handle = manager.register("batcher", ComponentOptions::new());
        let lifecycle_shutdown = handle.shutdown_token();
        let monitor = manager.monitor_background();
        let (batcher, outputs) = Batcher::new(
            dispatcher,
            transport,
            handle,
            watchdog_deadline,
            Duration::from_millis(20),
        );
        Self {
            batcher,
            outputs,
            attempts: Some(attempts),
            watchdog_deadline,
            lifecycle_shutdown,
            worker_shutdown,
            _servers: servers,
            _monitor: monitor,
        }
    }

    pub fn submit_keys(&self, keys: &[&str]) {
        let mut accumulator = Accumulator::default();
        for (index, key) in keys.iter().enumerate() {
            accumulator.push(Partition(0), msg(key, index as i64 + 1).into());
        }
        self.batcher.submit(accumulator);
    }

    pub async fn hold_next_request(&mut self) -> HeldRequest {
        let attempts = self
            .attempts
            .as_mut()
            .expect("requests have not been handed to the busy controller");
        tokio::time::timeout(Duration::from_secs(1), attempts.recv())
            .await
            .expect("send reaches a worker")
            .expect("attempt channel stays open")
    }

    pub async fn hold_two_requests_on_distinct_workers(&mut self) -> IndependentRequests {
        let first = self.hold_next_request().await;
        let second = self.hold_next_request().await;
        assert_ne!(
            first.worker, second.worker,
            "the two keys must occupy different workers"
        );
        IndependentRequests { first, second }
    }

    pub fn alternate_busy_replies_while_holding_one_request(
        &mut self,
        requests: IndependentRequests,
    ) -> OverlappingBusyRetries {
        // Transfer the incoming requests to the controller, which owns all further replies.
        let attempts = self
            .attempts
            .take()
            .expect("only one controller may own the worker requests");
        OverlappingBusyRetries::start(requests, attempts)
    }

    pub async fn expect_watchdog_failure_after_final_request_settles(
        &mut self,
        retries: &mut OverlappingBusyRetries,
    ) {
        let _error = tokio::time::timeout(Duration::from_secs(3), self.outputs.errors.recv())
            .await
            .expect("watchdog must bound retries that make no acceptance progress")
            .expect("batcher error channel stays open");
        assert!(
            retries.final_request_released.load(Ordering::Relaxed),
            "an in-flight attempt may settle after the deadline before the watchdog fails"
        );
        assert!(
            retries.busy_replies.load(Ordering::Relaxed) >= 2,
            "the reproduction must overlap busy retry rounds"
        );
        tokio::time::timeout(Duration::from_secs(1), &mut retries.task.0)
            .await
            .expect("busy controller stops after releasing the final request")
            .unwrap();
    }

    /// Signal the lifecycle token without dropping the batcher: parked work must still drain.
    pub fn request_lifecycle_shutdown(&self) {
        self.lifecycle_shutdown.cancel();
    }

    pub async fn expect_completion(&mut self, accepted: u32) {
        let completion =
            tokio::time::timeout(Duration::from_secs(1), self.outputs.completions.recv())
                .await
                .expect("accepted request completes")
                .expect("completion channel stays open");
        assert_eq!(completion.accepted, accepted);
    }

    pub async fn wait_past_watchdog_deadline(&self) {
        tokio::time::sleep(self.watchdog_deadline + Duration::from_millis(50)).await;
    }

    pub fn expect_no_watchdog_error(&mut self) {
        assert!(
            matches!(
                self.outputs.errors.try_recv(),
                Err(mpsc::error::TryRecvError::Empty)
            ),
            "the batcher must remain running without a watchdog failure"
        );
    }
}

impl Drop for WatchdogHarness {
    fn drop(&mut self) {
        self.lifecycle_shutdown.cancel();
        self.worker_shutdown.cancel();
    }
}

enum ControlledReply {
    Busy,
    Ok,
}

pub struct HeldRequest {
    worker: usize,
    reply: oneshot::Sender<ControlledReply>,
}

impl HeldRequest {
    pub fn reject_busy(self) {
        assert!(self.reply.send(ControlledReply::Busy).is_ok());
    }

    pub fn accept(self) {
        assert!(self.reply.send(ControlledReply::Ok).is_ok());
    }
}

pub struct IndependentRequests {
    first: HeldRequest,
    second: HeldRequest,
}

pub struct OverlappingBusyRetries {
    busy_replies: Arc<AtomicUsize>,
    final_request_released: Arc<AtomicBool>,
    task: AbortOnDrop,
}

impl OverlappingBusyRetries {
    fn start(
        requests: IndependentRequests,
        mut attempts: mpsc::UnboundedReceiver<HeldRequest>,
    ) -> Self {
        let busy_replies = Arc::new(AtomicUsize::new(0));
        let replies = Arc::clone(&busy_replies);
        let final_request_released = Arc::new(AtomicBool::new(false));
        let released = Arc::clone(&final_request_released);
        let task = AbortOnDrop(tokio::spawn(async move {
            let mut reject = requests.first;
            let mut held = requests.second;
            // Alternate Busy replies, always keeping one independently held request outstanding.
            // Once no replacement arrives, settle the final request: the watchdog may wait
            // for it beyond the deadline, but must then diagnose the lack of acceptance.
            loop {
                reject.reject_busy();
                replies.fetch_add(1, Ordering::Relaxed);
                match tokio::time::timeout(Duration::from_millis(750), attempts.recv()).await {
                    Ok(Some(next)) => {
                        reject = held;
                        held = next;
                    }
                    _ => {
                        held.reject_busy();
                        replies.fetch_add(1, Ordering::Relaxed);
                        released.store(true, Ordering::Relaxed);
                        return;
                    }
                }
            }
        }));
        Self {
            busy_replies,
            final_request_released,
            task,
        }
    }
}

struct AbortOnDrop(JoinHandle<()>);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        self.0.abort();
    }
}

struct ControlledBusyWorker {
    worker: usize,
    attempts: mpsc::UnboundedSender<HeldRequest>,
    shutdown: CancellationToken,
}

#[tonic::async_trait]
impl WorkerIngest for ControlledBusyWorker {
    type IngestStreamStream = UnboundedReceiverStream<Result<IngestStreamResponse, Status>>;

    async fn ingest_stream(
        &self,
        request: Request<Streaming<IngestStreamRequest>>,
    ) -> Result<Response<Self::IngestStreamStream>, Status> {
        let mut inbound = request.into_inner();
        let attempts = self.attempts.clone();
        let worker = self.worker;
        let shutdown = self.shutdown.clone();
        let (tx, rx) = mpsc::unbounded_channel();
        tokio::spawn(async move {
            // The fixture cancels active stream handlers even when an assertion fails.
            tokio::select! {
                _ = shutdown.cancelled() => {}
                _ = async {
                    let _ = tx.send(Ok(IngestStreamResponse {
                        msg: Some(ingest_stream_response::Msg::Ready(StreamReady {})),
                    }));
                    while let Some(Ok(frame)) = inbound.next().await {
                        let Some(ingest_stream_request::Msg::SubBatch(sub_batch)) = frame.msg else {
                            continue;
                        };
                        let (reply, wait_for_reply) = oneshot::channel();
                        let Some(reply) = async {
                            attempts.send(HeldRequest { worker, reply }).ok()?;
                            wait_for_reply.await.ok()
                        }
                        .await
                        else {
                            return;
                        };
                        let (status, accepted, error) = match reply {
                            ControlledReply::Busy => {
                                (SubBatchStatus::Busy as i32, 0, "at capacity".to_string())
                            }
                            ControlledReply::Ok => (
                                SubBatchStatus::Ok as i32,
                                sub_batch.messages.len() as u32,
                                String::new(),
                            ),
                        };
                        let _ = tx.send(Ok(IngestStreamResponse {
                            msg: Some(ingest_stream_response::Msg::Ack(SubBatchAck {
                                seq: sub_batch.seq,
                                status,
                                accepted,
                                error,
                            })),
                        }));
                    }
                } => {}
            }
        });
        Ok(Response::new(UnboundedReceiverStream::new(rx)))
    }
}

async fn start_controlled_busy_worker(
    worker: usize,
    attempts: mpsc::UnboundedSender<HeldRequest>,
    shutdown: CancellationToken,
) -> (SocketAddr, AbortOnDrop) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let server = AbortOnDrop(tokio::spawn(async move {
        tonic::transport::Server::builder()
            .add_service(
                WorkerIngestServer::new(ControlledBusyWorker {
                    worker,
                    attempts,
                    shutdown,
                })
                .accept_compressed(tonic::codec::CompressionEncoding::Gzip)
                .send_compressed(tonic::codec::CompressionEncoding::Gzip),
            )
            .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
            .await
            .unwrap();
    }));
    (addr, server)
}

fn registry_config() -> WorkerRegistryConfig {
    WorkerRegistryConfig {
        probe_interval: Duration::from_secs(60),
        dead_declaration: Duration::from_secs(60),
        passive_window: Duration::from_secs(60),
        passive_error_threshold: 1.0,
        passive_min_samples: usize::MAX,
        degraded_hold: Duration::ZERO,
        min_state_duration: Duration::ZERO,
        probe_failure_threshold: u32::MAX,
        drain_timeout: Duration::from_secs(60),
    }
}
