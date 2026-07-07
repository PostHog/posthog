//! Per-endpoint bidirectional Resolve stream mux.
//!
//! A mux owns exactly one long-lived `Resolve` stream for one endpoint. Callers
//! submit independent [`ResolveItem`]s through a bounded local queue; the mux
//! allocates per-stream ids, writes items to the gRPC request stream, and
//! demultiplexes [`ResolveOutcome`]s back to per-item waiters.

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
#[cfg(test)]
use std::time::Duration;

use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_client::CymbalResolutionClient;
use cymbal_proto::cymbal::resolution::v1::{
    resolve_outcome, Error, ErrorKind, ResolveItem, ResolveOutcome,
};
use futures::StreamExt;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::ReceiverStream;
use tonic::transport::Channel;
use tonic::{Code, Request, Status};
use tracing::warn;

use crate::metric_consts::{
    REMOTE_RESOLUTION_ENDPOINT_ADMISSION_REJECTIONS, REMOTE_RESOLUTION_ENDPOINT_MUX_IN_FLIGHT,
};

use super::client::{classify_status, with_internal_api_secret, RemoteCallError};

#[derive(Clone)]
pub struct ResolveMux {
    inner: Arc<ResolveMuxInner>,
}

struct ResolveMuxInner {
    addr: SocketAddr,
    outbound: mpsc::Sender<ResolveItem>,
    waiters: Mutex<HashMap<u64, Waiter>>,
    task: Mutex<Option<JoinHandle<()>>>,
    next_token: AtomicU64,
    closed: AtomicBool,
}

struct Waiter {
    caller_id: u64,
    tx: mpsc::Sender<Result<ResolveOutcome, RemoteCallError>>,
}

pub(super) struct ResolveItemSession {
    pub(super) outcomes: mpsc::Receiver<Result<ResolveOutcome, RemoteCallError>>,
    inner: Option<Arc<ResolveMuxInner>>,
    stream_id: u64,
}

#[derive(Debug, Clone)]
struct StreamFailure {
    code: Code,
    message: String,
    retryable: bool,
}

impl StreamFailure {
    fn from_status(status: Status) -> Self {
        let classified = classify_status(status);
        match classified {
            RemoteCallError::Retryable(status) => Self {
                code: status.code(),
                message: status.message().to_string(),
                retryable: true,
            },
            RemoteCallError::Terminal(status) => Self {
                code: status.code(),
                message: status.message().to_string(),
                retryable: false,
            },
            RemoteCallError::Deadline(deadline) => Self {
                code: Code::DeadlineExceeded,
                message: format!("deadline exceeded after {deadline:?}"),
                retryable: true,
            },
        }
    }

    fn to_remote_error(&self) -> RemoteCallError {
        let status = Status::new(self.code, self.message.clone());
        if self.retryable {
            RemoteCallError::Retryable(status)
        } else {
            RemoteCallError::Terminal(status)
        }
    }
}

impl ResolveItemSession {
    pub(super) fn cancel(&self) {
        if let Some(inner) = &self.inner {
            inner.remove_waiter(self.stream_id);
        }
    }

    #[cfg(test)]
    async fn wait_terminal(
        mut self,
        deadline: Duration,
    ) -> Result<ResolveOutcome, RemoteCallError> {
        match tokio::time::timeout(deadline, self.outcomes.recv()).await {
            Ok(Some(result)) => result,
            Ok(None) => Err(RemoteCallError::Retryable(Status::unavailable(
                "remote resolution session was dropped",
            ))),
            Err(_) => {
                self.cancel();
                Err(RemoteCallError::Deadline(deadline))
            }
        }
    }
}

impl ResolveMux {
    pub fn new(
        addr: SocketAddr,
        channel: Channel,
        internal_api_secret: String,
        queue_capacity: usize,
    ) -> Self {
        let (outbound, inbound) = mpsc::channel(queue_capacity.max(1));
        let inner = Arc::new(ResolveMuxInner {
            addr,
            outbound,
            waiters: Mutex::new(HashMap::new()),
            task: Mutex::new(None),
            next_token: AtomicU64::new(1),
            closed: AtomicBool::new(false),
        });
        let task_inner = inner.clone();
        let task = tokio::spawn(async move {
            run_stream(task_inner, channel, inbound, internal_api_secret).await;
        });
        *inner.task.lock().expect("mux task slot poisoned") = Some(task);
        Self { inner }
    }

    pub(super) fn submit_session(&self, mut item: ResolveItem) -> ResolveItemSession {
        let caller_id = item.id;
        if self.is_closed() {
            self.inner.record_admission_rejection("closed");
            return immediate_session(overloaded_outcome(
                caller_id,
                "remote resolution stream is closed".to_string(),
            ));
        }

        let stream_id = self.inner.next_stream_id();
        item.id = stream_id;
        let (tx, rx) = mpsc::channel(2);
        {
            let mut waiters = self.inner.waiters.lock().expect("waiter map poisoned");
            waiters.insert(stream_id, Waiter { caller_id, tx });
            self.inner.record_waiter_count(waiters.len());
        }

        if let Err(err) = self.inner.outbound.try_send(item) {
            self.inner.remove_waiter(stream_id);
            let (reason, message) = match err {
                mpsc::error::TrySendError::Full(_) => {
                    self.inner.record_admission_rejection("queue_full");
                    ("queue_full", "remote resolution stream queue is full")
                }
                mpsc::error::TrySendError::Closed(_) => {
                    self.inner.record_admission_rejection("closed");
                    ("closed", "remote resolution stream is closed")
                }
            };
            return immediate_session(overloaded_outcome(
                caller_id,
                format!("{message} ({reason})"),
            ));
        }

        ResolveItemSession {
            outcomes: rx,
            inner: Some(self.inner.clone()),
            stream_id,
        }
    }

    pub fn close(&self) {
        if self.inner.closed.swap(true, Ordering::AcqRel) {
            return;
        }
        if let Some(task) = self
            .inner
            .task
            .lock()
            .expect("mux task slot poisoned")
            .take()
        {
            task.abort();
        }
        self.inner.fail_all(StreamFailure {
            code: Code::Unavailable,
            message: "remote resolution stream closed by endpoint lifecycle".to_string(),
            retryable: true,
        });
    }

    pub fn is_closed(&self) -> bool {
        self.inner.closed.load(Ordering::Acquire)
    }

    #[cfg(test)]
    fn waiter_count(&self) -> usize {
        self.inner
            .waiters
            .lock()
            .expect("waiter map poisoned")
            .len()
    }
}

impl ResolveMuxInner {
    fn next_stream_id(&self) -> u64 {
        let token = self.next_token.fetch_add(1, Ordering::AcqRel);
        debug_assert_ne!(token, 0, "stream token counter wrapped");
        token
    }

    fn remove_waiter(&self, stream_id: u64) {
        let mut waiters = self.waiters.lock().expect("waiter map poisoned");
        waiters.remove(&stream_id);
        self.record_waiter_count(waiters.len());
    }

    fn complete(&self, mut outcome: ResolveOutcome) {
        let is_terminal = !matches!(outcome.result, Some(resolve_outcome::Result::Accepted(_)));
        let waiter = {
            let mut waiters = self.waiters.lock().expect("waiter map poisoned");
            let waiter = if is_terminal {
                waiters.remove(&outcome.id)
            } else {
                waiters.get(&outcome.id).map(|waiter| Waiter {
                    caller_id: waiter.caller_id,
                    tx: waiter.tx.clone(),
                })
            };
            if is_terminal {
                self.record_waiter_count(waiters.len());
            }
            waiter
        };
        let Some(waiter) = waiter else {
            warn!(
                endpoint = %self.addr,
                stream_id = outcome.id,
                "remote resolution outcome had no waiter"
            );
            return;
        };
        outcome.id = waiter.caller_id;
        drop(waiter.tx.try_send(Ok(outcome)));
    }

    fn fail_all(&self, failure: StreamFailure) {
        let waiters: Vec<Waiter> = {
            let mut waiters = self.waiters.lock().expect("waiter map poisoned");
            let drained = waiters.drain().map(|(_, waiter)| waiter).collect();
            self.record_waiter_count(0);
            drained
        };
        for waiter in waiters {
            let result = if failure.retryable {
                Ok(overloaded_outcome(
                    waiter.caller_id,
                    failure.message.clone(),
                ))
            } else {
                Err(failure.to_remote_error())
            };
            drop(waiter.tx.try_send(result));
        }
    }

    fn record_waiter_count(&self, count: usize) {
        metrics::gauge!(
            REMOTE_RESOLUTION_ENDPOINT_MUX_IN_FLIGHT,
            "endpoint" => self.addr.to_string(),
        )
        .set(count as f64);
    }

    fn record_admission_rejection(&self, reason: &'static str) {
        metrics::counter!(
            REMOTE_RESOLUTION_ENDPOINT_ADMISSION_REJECTIONS,
            "endpoint" => self.addr.to_string(),
            "reason" => reason,
        )
        .increment(1);
    }
}

fn immediate_session(outcome: ResolveOutcome) -> ResolveItemSession {
    let (tx, rx) = mpsc::channel(1);
    drop(tx.try_send(Ok(outcome)));
    ResolveItemSession {
        outcomes: rx,
        inner: None,
        stream_id: 0,
    }
}

async fn run_stream(
    inner: Arc<ResolveMuxInner>,
    channel: Channel,
    inbound: mpsc::Receiver<ResolveItem>,
    internal_api_secret: String,
) {
    let outbound = ReceiverStream::new(inbound);
    let request = match with_internal_api_secret(Request::new(outbound), &internal_api_secret) {
        Ok(request) => request,
        Err(status) => {
            inner.closed.store(true, Ordering::Release);
            inner.fail_all(StreamFailure::from_status(*status));
            return;
        }
    };

    let mut client = CymbalResolutionClient::new(channel);
    let response = client.resolve(request).await;

    let mut response_stream = match response {
        Ok(response) => response.into_inner(),
        Err(status) => {
            warn!(endpoint = %inner.addr, error = %status, "remote resolution stream failed to open");
            inner.closed.store(true, Ordering::Release);
            inner.fail_all(StreamFailure::from_status(status));
            return;
        }
    };

    loop {
        match response_stream.next().await {
            Some(Ok(outcome)) => inner.complete(outcome),
            Some(Err(status)) => {
                warn!(endpoint = %inner.addr, error = %status, "remote resolution stream broke");
                inner.closed.store(true, Ordering::Release);
                inner.fail_all(StreamFailure::from_status(status));
                return;
            }
            None => {
                warn!(endpoint = %inner.addr, "remote resolution stream ended");
                inner.closed.store(true, Ordering::Release);
                inner.fail_all(StreamFailure {
                    code: Code::Unavailable,
                    message: "remote resolution stream ended".to_string(),
                    retryable: true,
                });
                return;
            }
        }
    }
}

fn overloaded_outcome(id: u64, message: String) -> ResolveOutcome {
    ResolveOutcome {
        id,
        result: Some(resolve_outcome::Result::Error(Error {
            kind: ErrorKind::Overloaded as i32,
            message,
            details_json: Vec::new(),
        })),
    }
}

#[cfg(test)]
mod tests {
    use std::pin::Pin;
    use std::sync::atomic::AtomicUsize;
    use std::sync::Mutex as StdMutex;

    use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::{
        CymbalResolution, CymbalResolutionServer,
    };
    use cymbal_proto::cymbal::resolution::v1::{Done, LoadEvent, SubscribeRequest};
    use futures::Stream;
    use tokio_stream::wrappers::ReceiverStream;
    use tonic::transport::{Endpoint, Server};
    use tonic::Response;

    use super::*;

    #[derive(Clone, Default)]
    struct RecordingService {
        received_ids: Arc<StdMutex<Vec<u64>>>,
        stream_count: Arc<AtomicUsize>,
    }

    #[tonic::async_trait]
    impl CymbalResolution for RecordingService {
        type ResolveStream = Pin<Box<dyn Stream<Item = Result<ResolveOutcome, Status>> + Send>>;
        type SubscribeStream = Pin<Box<dyn Stream<Item = Result<LoadEvent, Status>> + Send>>;

        async fn resolve(
            &self,
            request: Request<tonic::Streaming<ResolveItem>>,
        ) -> Result<Response<Self::ResolveStream>, Status> {
            self.stream_count.fetch_add(1, Ordering::AcqRel);
            let mut inbound = request.into_inner();
            let (tx, rx) = mpsc::channel(8);
            let received_ids = self.received_ids.clone();
            tokio::spawn(async move {
                while let Some(item) = inbound.next().await {
                    let item = item.expect("test request item");
                    received_ids
                        .lock()
                        .expect("received ids poisoned")
                        .push(item.id);
                    let outcome = ResolveOutcome {
                        id: item.id,
                        result: Some(resolve_outcome::Result::Done(Done {
                            resolved_exception_json: item.exception_json,
                        })),
                    };
                    tx.send(Ok(outcome)).await.expect("test receiver is alive");
                }
            });
            Ok(Response::new(Box::pin(ReceiverStream::new(rx))))
        }

        async fn subscribe(
            &self,
            _request: Request<SubscribeRequest>,
        ) -> Result<Response<Self::SubscribeStream>, Status> {
            Ok(Response::new(Box::pin(futures::stream::empty())))
        }
    }

    async fn spawn_test_channel(service: RecordingService) -> (SocketAddr, Channel) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind test server");
        let addr = listener.local_addr().expect("test server addr");
        let incoming = futures::stream::unfold(listener, |listener| async {
            Some((listener.accept().await.map(|(stream, _)| stream), listener))
        });

        tokio::spawn(async move {
            Server::builder()
                .add_service(CymbalResolutionServer::new(service))
                .serve_with_incoming(incoming)
                .await
                .expect("test gRPC server exits cleanly");
        });

        let channel = Endpoint::from_shared(format!("http://{addr}"))
            .expect("valid test endpoint")
            .connect()
            .await
            .expect("connect test channel");
        (addr, channel)
    }

    fn item(id: u64) -> ResolveItem {
        ResolveItem {
            id,
            team_id: 7,
            exception_json: format!("exception-{id}").into_bytes(),
            metadata: Vec::new(),
            deadline_ms: 1_000,
        }
    }

    #[tokio::test]
    async fn resolve_many_reuses_one_stream_and_restores_caller_ids() {
        let service = RecordingService::default();
        let received_ids = service.received_ids.clone();
        let stream_count = service.stream_count.clone();
        let (addr, channel) = spawn_test_channel(service).await;
        let mux = ResolveMux::new(addr, channel, "test-secret".to_string(), 8);

        let outcomes = futures::future::join_all([item(101), item(102)].into_iter().map(|item| {
            mux.submit_session(item)
                .wait_terminal(Duration::from_secs(1))
        }))
        .await
        .into_iter()
        .collect::<Result<Vec<_>, _>>()
        .expect("resolve through mux");
        assert_eq!(
            outcomes
                .iter()
                .map(|outcome| outcome.id)
                .collect::<Vec<_>>(),
            vec![101, 102]
        );

        let outcomes = [mux
            .submit_session(item(103))
            .wait_terminal(Duration::from_secs(1))
            .await
            .expect("resolve through existing mux")];
        assert_eq!(outcomes[0].id, 103);

        assert_eq!(stream_count.load(Ordering::Acquire), 1);
        assert_eq!(
            received_ids.lock().expect("received ids poisoned").clone(),
            vec![1, 2, 3]
        );
        assert_eq!(mux.waiter_count(), 0);
    }

    #[tokio::test]
    async fn closed_mux_returns_overloaded_outcome_without_blocking() {
        let service = RecordingService::default();
        let (addr, channel) = spawn_test_channel(service).await;
        let mux = ResolveMux::new(addr, channel, "test-secret".to_string(), 1);
        mux.close();

        let outcomes = [mux
            .submit_session(item(7))
            .wait_terminal(Duration::from_secs(1))
            .await
            .expect("closed mux maps to overloaded item outcome")];
        assert_eq!(outcomes[0].id, 7);
        assert!(matches!(
            outcomes[0].result,
            Some(resolve_outcome::Result::Error(ref err)) if err.kind == ErrorKind::Overloaded as i32
        ));
        assert_eq!(mux.waiter_count(), 0);
    }
}
