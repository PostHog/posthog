// `tonic::Status` is ~176 bytes, so almost every helper that returns
// `Result<_, Status>` trips `clippy::result_large_err`. Boxing those returns in
// tests would add noise without changing what we exercise. The production crate
// silences the same lint at the crate root.
#![allow(clippy::result_large_err)]

use cymbal_api::cymbal::v1::cymbal_ingestion_client::CymbalIngestionClient;
use cymbal_api::cymbal::v1::cymbal_ingestion_server::CymbalIngestionServer;
use cymbal_api::cymbal::v1::cymbal_stage_runtime_server::CymbalStageRuntimeServer;
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use cymbal_alerting::{AlertingEvent, ALERTING_STAGE_ID};
use cymbal_api::cymbal::v1::cymbal_stage_runtime_server::CymbalStageRuntime;
use cymbal_api::cymbal::v1::{
    process_exception_batch_result, BatchContext, ExceptionEvent, ProcessExceptionBatchRequest,
    ProcessExceptionBatchResult, StageBatch, StageBatchResult, StageItem, StageItemError,
    StageItemResult,
};
use cymbal_core::routing::RoutingKey;
use cymbal_core::{Metadata, StagePayload};
use cymbal_domain::ExceptionProperties;
use cymbal_domain::{EventOutcome, EventResult, InputEvent};
use cymbal_linking::LINKING_STAGE_ID;
use cymbal_rate_limiting::{RateLimitingConfig, RateLimitingStage};
use cymbal_resolution::{ResolvedEvent, RESOLUTION_STAGE_ID};
use cymbal_runtime::RuntimeStages;
use cymbal_server::config::default_remote_routing_config;
use cymbal_server::pipeline::PipelineLimits;
use cymbal_server::registry::StageRegistry;
use cymbal_server::remote::{
    RemoteStageConnectionManager, RemoteStageConnectionOptions, RemoteStageTarget,
};
use cymbal_server::stage::CymbalStageService;
use cymbal_server::CymbalPipelineService;
use futures::TryStreamExt;
use limiters::{EvalResult, GlobalRateLimitResponse, GlobalRateLimiter};
use std::sync::atomic::{AtomicUsize, Ordering};
use tokio::net::TcpListener;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::TcpListenerStream;
use tonic::transport::{Channel, Server};
use tonic::{Code, Request, Response, Status};

struct TestServer {
    addr: std::net::SocketAddr,
    handle: JoinHandle<()>,
}

impl Drop for TestServer {
    fn drop(&mut self) {
        self.handle.abort();
    }
}

async fn start_test_server() -> TestServer {
    start_pipeline_server(CymbalPipelineService::new()).await
}

async fn start_pipeline_server(service: CymbalPipelineService) -> TestServer {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let handle = tokio::spawn(async move {
        Server::builder()
            .add_service(CymbalIngestionServer::new(service))
            .serve_with_incoming(TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    TestServer { addr, handle }
}

async fn start_stage_server() -> TestServer {
    start_cymbal_stage_server(CymbalStageService::new(StageRegistry::local_default())).await
}

async fn start_cymbal_stage_server<T>(service: T) -> TestServer
where
    T: CymbalStageRuntime + Send + Sync + 'static,
{
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    let handle = tokio::spawn(async move {
        Server::builder()
            .add_service(CymbalStageRuntimeServer::new(service))
            .serve_with_incoming(TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    TestServer { addr, handle }
}

#[derive(Debug, Default)]
struct PartialFailureResolutionStageService;

#[derive(Debug, Default)]
struct MetadataAlertingStageService;

#[derive(Debug, Default)]
struct FailingStageService;

#[derive(Debug, Clone, Copy)]
enum BadRemoteResultMode {
    Duplicate,
    Unknown,
}

#[derive(Debug, Clone, Copy)]
struct BadRemoteResultResolutionStageService {
    mode: BadRemoteResultMode,
}

#[derive(Debug, Default)]
struct MixedItemFailureResolutionStageService;

#[derive(Debug, Clone)]
struct CountingResolutionStageService {
    seen_event_ids: Arc<Mutex<Vec<String>>>,
}

#[derive(Debug, Clone)]
struct RecordingResolutionStageService {
    seen_event_ids: Arc<Mutex<Vec<String>>>,
    reverse_results: bool,
}

#[derive(Debug, Clone)]
struct OverloadedStageService {
    calls: Arc<AtomicUsize>,
}

#[derive(Debug, Clone)]
struct SlowStageService {
    calls: Arc<AtomicUsize>,
    delay: std::time::Duration,
}

#[derive(Debug, Clone)]
struct TerminalOrSlowResolutionStageService {
    delay: std::time::Duration,
}

#[derive(Debug, Clone, Copy)]
enum TerminalStageInput {
    Linking,
    Alerting,
}

#[derive(Clone)]
struct FakeLimiter {
    results: Arc<Mutex<VecDeque<EvalResult>>>,
    keys: Arc<Mutex<Vec<String>>>,
}

impl FakeLimiter {
    fn new(results: Vec<EvalResult>) -> Self {
        Self {
            results: Arc::new(Mutex::new(VecDeque::from(results))),
            keys: Arc::new(Mutex::new(Vec::new())),
        }
    }

    fn keys(&self) -> Vec<String> {
        self.keys.lock().unwrap().clone()
    }
}

#[async_trait::async_trait]
impl GlobalRateLimiter for FakeLimiter {
    async fn check_limit(
        &self,
        key: &str,
        count: u64,
        _timestamp: Option<chrono::DateTime<chrono::Utc>>,
    ) -> EvalResult {
        assert_eq!(count, 1);
        self.keys.lock().unwrap().push(key.to_string());
        self.results
            .lock()
            .unwrap()
            .pop_front()
            .unwrap_or(EvalResult::Allowed)
    }

    async fn check_custom_limit(
        &self,
        _key: &str,
        _count: u64,
        _timestamp: Option<chrono::DateTime<chrono::Utc>>,
    ) -> EvalResult {
        EvalResult::NotApplicable
    }

    fn is_custom_key(&self, _key: &str) -> bool {
        false
    }

    fn shutdown(&mut self) {}
}

fn limited_response(key: &str) -> GlobalRateLimitResponse {
    GlobalRateLimitResponse {
        key: key.to_string(),
        current_count: 2.0,
        threshold: 1,
        window_interval: std::time::Duration::from_secs(60),
        sync_interval: std::time::Duration::from_secs(15),
        is_custom_limited: false,
    }
}

fn runtime_stages(rate_limiting: RateLimitingStage) -> RuntimeStages {
    RuntimeStages {
        rate_limiting,
        resolution: cymbal_resolution::ResolutionStage::new(),
        grouping: cymbal_grouping::GroupingStage::new(),
        linking: cymbal_linking::LinkingStage::new(),
        alerting: cymbal_alerting::AlertingStage::new(),
    }
}

fn rate_limit_stage(limiter: FakeLimiter) -> RateLimitingStage {
    RateLimitingStage::with_limiter(
        RateLimitingConfig {
            enabled: true,
            threshold: 1,
            ..Default::default()
        },
        Arc::new(limiter),
    )
}

#[tonic::async_trait]
impl CymbalStageRuntime for PartialFailureResolutionStageService {
    async fn process_stage(
        &self,
        _request: Request<StageBatch>,
    ) -> Result<Response<StageBatchResult>, Status> {
        let resolved_event = ResolvedEvent {
            event_id: "event-1".to_string(),
            team_id: 1,
            properties: ExceptionProperties::from_map_preserving_invalid_exception_fields(
                serde_json::json!({ "index": 1 })
                    .as_object()
                    .unwrap()
                    .clone(),
            ),
            metadata: Metadata::new(),
        };
        let payload = serde_json::to_vec(&resolved_event).unwrap();
        Ok(Response::new(StageBatchResult {
            results: vec![StageItemResult {
                item_id: "event-1".to_string(),
                r#type: ResolvedEvent::TYPE.to_string(),
                payload,
            }],
            errors: vec![StageItemError {
                item_id: "event-2".to_string(),
                code: "stage_pod_terminated".to_string(),
                message: "stage pod terminated".to_string(),
                retryable: true,
            }],
            load: None,
        }))
    }
}

#[tonic::async_trait]
impl CymbalStageRuntime for MetadataAlertingStageService {
    async fn process_stage(
        &self,
        request: Request<StageBatch>,
    ) -> Result<Response<StageBatchResult>, Status> {
        let results = request
            .into_inner()
            .items
            .into_iter()
            .map(|item| {
                let event: AlertingEvent = serde_json::from_slice(&item.payload)
                    .map_err(|error| Status::invalid_argument(error.to_string()))?;
                let mut result = event.result;
                if let EventOutcome::Next { metadata, .. } = &mut result.outcome {
                    metadata.insert("remote_alerting".to_string(), "ran".to_string());
                }
                let payload = serde_json::to_vec(&result)
                    .map_err(|error| Status::internal(error.to_string()))?;

                Ok(StageItemResult {
                    item_id: result.event_id,
                    r#type: EventResult::TYPE.to_string(),
                    payload,
                })
            })
            .collect::<Result<Vec<_>, Status>>()?;

        Ok(Response::new(StageBatchResult {
            results,
            errors: Vec::new(),
            load: None,
        }))
    }
}

#[tonic::async_trait]
impl CymbalStageRuntime for FailingStageService {
    async fn process_stage(
        &self,
        _request: Request<StageBatch>,
    ) -> Result<Response<StageBatchResult>, Status> {
        Err(Status::unavailable("remote limiter unavailable"))
    }
}

#[tonic::async_trait]
impl CymbalStageRuntime for BadRemoteResultResolutionStageService {
    async fn process_stage(
        &self,
        request: Request<StageBatch>,
    ) -> Result<Response<StageBatchResult>, Status> {
        let mut items = request.into_inner().items;
        let first = items
            .pop()
            .ok_or_else(|| Status::invalid_argument("expected at least one item"))?;
        let first_event: InputEvent = serde_json::from_slice(&first.payload)
            .map_err(|error| Status::invalid_argument(error.to_string()))?;
        let first_result = resolved_stage_item(
            match self.mode {
                BadRemoteResultMode::Duplicate => first_event.event_id.as_str(),
                BadRemoteResultMode::Unknown => "unknown-event",
            },
            first_event.team_id,
            first_event.properties,
        )?;
        let mut results = vec![first_result];

        if matches!(self.mode, BadRemoteResultMode::Duplicate) {
            let duplicate_event: InputEvent = serde_json::from_slice(&first.payload)
                .map_err(|error| Status::invalid_argument(error.to_string()))?;
            results.push(resolved_stage_item(
                &duplicate_event.event_id,
                duplicate_event.team_id,
                duplicate_event.properties,
            )?);
        }

        Ok(Response::new(StageBatchResult {
            results,
            errors: Vec::new(),
            load: None,
        }))
    }
}

#[tonic::async_trait]
impl CymbalStageRuntime for MixedItemFailureResolutionStageService {
    async fn process_stage(
        &self,
        request: Request<StageBatch>,
    ) -> Result<Response<StageBatchResult>, Status> {
        let mut results = Vec::new();
        let mut errors = Vec::new();
        for item in request.into_inner().items {
            match item.item_id.as_str() {
                "retry-item" => errors.push(StageItemError {
                    item_id: item.item_id,
                    code: "retryable_stage_error".to_string(),
                    message: "retry this event".to_string(),
                    retryable: true,
                }),
                "error-item" => errors.push(StageItemError {
                    item_id: item.item_id,
                    code: "non_retryable_stage_error".to_string(),
                    message: "do not retry this event".to_string(),
                    retryable: false,
                }),
                _ => results.push(resolution_result_for_item(item)?),
            }
        }

        Ok(Response::new(StageBatchResult {
            results,
            errors,
            load: None,
        }))
    }
}

#[tonic::async_trait]
impl CymbalStageRuntime for CountingResolutionStageService {
    async fn process_stage(
        &self,
        request: Request<StageBatch>,
    ) -> Result<Response<StageBatchResult>, Status> {
        let results = request
            .into_inner()
            .items
            .into_iter()
            .map(|item| {
                self.seen_event_ids
                    .lock()
                    .unwrap()
                    .push(item.item_id.clone());
                let event: InputEvent = serde_json::from_slice(&item.payload)
                    .map_err(|error| Status::invalid_argument(error.to_string()))?;
                let resolved_event = ResolvedEvent {
                    event_id: event.event_id,
                    team_id: event.team_id,
                    properties: event.properties,
                    metadata: Metadata::new(),
                };
                let payload = serde_json::to_vec(&resolved_event)
                    .map_err(|error| Status::internal(error.to_string()))?;

                Ok(StageItemResult {
                    item_id: resolved_event.event_id,
                    r#type: ResolvedEvent::TYPE.to_string(),
                    payload,
                })
            })
            .collect::<Result<Vec<_>, Status>>()?;

        Ok(Response::new(StageBatchResult {
            results,
            errors: Vec::new(),
            load: None,
        }))
    }
}

#[tonic::async_trait]
impl CymbalStageRuntime for RecordingResolutionStageService {
    async fn process_stage(
        &self,
        request: Request<StageBatch>,
    ) -> Result<Response<StageBatchResult>, Status> {
        let mut items = request.into_inner().items;
        if self.reverse_results {
            items.reverse();
        }

        let results = items
            .into_iter()
            .map(|item| {
                self.seen_event_ids
                    .lock()
                    .unwrap()
                    .push(item.item_id.clone());
                resolution_result_for_item(item)
            })
            .collect::<Result<Vec<_>, Status>>()?;

        Ok(Response::new(StageBatchResult {
            results,
            errors: Vec::new(),
            load: None,
        }))
    }
}

#[tonic::async_trait]
impl CymbalStageRuntime for OverloadedStageService {
    async fn process_stage(
        &self,
        _request: Request<StageBatch>,
    ) -> Result<Response<StageBatchResult>, Status> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Err(Status::resource_exhausted("stage pod overloaded"))
    }
}

#[tonic::async_trait]
impl CymbalStageRuntime for SlowStageService {
    async fn process_stage(
        &self,
        _request: Request<StageBatch>,
    ) -> Result<Response<StageBatchResult>, Status> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        tokio::time::sleep(self.delay).await;
        Ok(Response::new(StageBatchResult {
            results: Vec::new(),
            errors: Vec::new(),
            load: None,
        }))
    }
}

#[tonic::async_trait]
impl CymbalStageRuntime for TerminalOrSlowResolutionStageService {
    async fn process_stage(
        &self,
        request: Request<StageBatch>,
    ) -> Result<Response<StageBatchResult>, Status> {
        let items = request.into_inner().items;
        if items.iter().any(|item| item.item_id.starts_with("slow")) {
            tokio::time::sleep(self.delay).await;
        }

        let mut results = Vec::new();
        let mut errors = Vec::new();
        for item in items {
            if item.item_id.starts_with("terminal") {
                errors.push(StageItemError {
                    item_id: item.item_id,
                    code: "test_terminal".to_string(),
                    message: "terminal resolution failure".to_string(),
                    retryable: true,
                });
            } else {
                results.push(resolution_result_for_item(item)?);
            }
        }

        Ok(Response::new(StageBatchResult {
            results,
            errors,
            load: None,
        }))
    }
}

async fn create_client(server: &TestServer) -> CymbalIngestionClient<Channel> {
    CymbalIngestionClient::connect(format!("http://{}", server.addr))
        .await
        .unwrap()
}

fn batch_request(events: Vec<ExceptionEvent>) -> ProcessExceptionBatchRequest {
    ProcessExceptionBatchRequest {
        context: Some(BatchContext {
            batch_id: "batch-1".to_string(),
            metadata: Default::default(),
        }),
        events,
        options: None,
    }
}

fn exception_event(event_id: &str, properties_json: Vec<u8>) -> ExceptionEvent {
    exception_event_for_team(event_id, 1, properties_json)
}

fn exception_event_for_team(
    event_id: &str,
    team_id: i64,
    properties_json: Vec<u8>,
) -> ExceptionEvent {
    ExceptionEvent {
        event_id: event_id.to_string(),
        team_id,
        distinct_id: format!("distinct-{event_id}"),
        timestamp: None,
        properties_json,
    }
}

fn numbered_exception_events(prefix: &str, start: usize, count: usize) -> Vec<ExceptionEvent> {
    (start..start + count)
        .map(|index| {
            exception_event(
                &format!("{prefix}-{index}"),
                format!(r#"{{"event":"$exception","index":{index}}}"#).into_bytes(),
            )
        })
        .collect()
}

fn resolution_result_for_item(item: StageItem) -> Result<StageItemResult, Status> {
    let event: InputEvent = serde_json::from_slice(&item.payload)
        .map_err(|error| Status::invalid_argument(error.to_string()))?;
    resolved_stage_item(&event.event_id, event.team_id, event.properties)
}

fn resolved_stage_item(
    event_id: &str,
    team_id: i64,
    properties: ExceptionProperties,
) -> Result<StageItemResult, Status> {
    let resolved_event = ResolvedEvent {
        event_id: event_id.to_string(),
        team_id,
        properties,
        metadata: Metadata::new(),
    };
    let payload =
        serde_json::to_vec(&resolved_event).map_err(|error| Status::internal(error.to_string()))?;

    Ok(StageItemResult {
        item_id: resolved_event.event_id,
        r#type: ResolvedEvent::TYPE.to_string(),
        payload,
    })
}

async fn process_batch(
    client: &mut CymbalIngestionClient<Channel>,
    request: ProcessExceptionBatchRequest,
) -> Vec<ProcessExceptionBatchResult> {
    client
        .process_exception_batch(request)
        .await
        .unwrap()
        .into_inner()
        .try_collect()
        .await
        .unwrap()
}

async fn process_batch_stream_error(
    client: &mut CymbalIngestionClient<Channel>,
    request: ProcessExceptionBatchRequest,
) -> Status {
    let response = client.process_exception_batch(request).await.unwrap();
    response
        .into_inner()
        .try_collect::<Vec<_>>()
        .await
        .unwrap_err()
}

fn remote_connection_options_with_timeout(
    stage_timeout: std::time::Duration,
) -> RemoteStageConnectionOptions {
    RemoteStageConnectionOptions {
        stage_timeout: Some(stage_timeout),
        ..RemoteStageConnectionOptions::default()
    }
}

async fn assert_timeout_uses_single_remote_stage_attempt(
    stage_id: &str,
    input: TerminalStageInput,
) {
    let first_calls = Arc::new(AtomicUsize::new(0));
    let second_calls = Arc::new(AtomicUsize::new(0));
    let delay = std::time::Duration::from_millis(250);
    let first_stage = start_cymbal_stage_server(SlowStageService {
        calls: first_calls.clone(),
        delay,
    })
    .await;
    let second_stage = start_cymbal_stage_server(SlowStageService {
        calls: second_calls.clone(),
        delay,
    })
    .await;
    let target_name = match input {
        TerminalStageInput::Linking => "linking-timeout-stage",
        TerminalStageInput::Alerting => "alerting-timeout-stage",
    };
    let remote_connections = RemoteStageConnectionManager::with_options_and_routing(
        remote_connection_options_with_timeout(std::time::Duration::from_millis(25)),
        default_remote_routing_config(),
    );
    refresh_two_pod_target(
        &remote_connections,
        target_name,
        &first_stage,
        &second_stage,
    )
    .await;
    let mut registry = StageRegistry::local_default();
    registry.set_remote_stage(stage_id, target_name).unwrap();
    let service = CymbalPipelineService::with_registry(registry)
        .with_remote_connections(remote_connections.clone());
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;

    let results = process_batch(
        &mut client,
        batch_request(vec![exception_event_for_team(
            "timeout-1",
            11,
            br#"{"event":"$exception","index":1}"#.to_vec(),
        )]),
    )
    .await;

    assert_eq!(results.len(), 1);
    assert_retry_result(&results[0]);
    let total_calls = first_calls.load(Ordering::SeqCst) + second_calls.load(Ordering::SeqCst);
    assert_eq!(
        total_calls, 1,
        "expected timeout for {stage_id} to use one remote endpoint without fallback"
    );
}

async fn refresh_two_pod_target(
    remote_connections: &RemoteStageConnectionManager,
    target_name: &str,
    first: &TestServer,
    second: &TestServer,
) {
    remote_connections
        .refresh_targets(&[
            RemoteStageTarget::new(target_name, "127.0.0.1", first.addr.port()),
            RemoteStageTarget::new(target_name, "127.0.0.1", second.addr.port()),
        ])
        .await
        .unwrap();
}

async fn team_id_for_primary_endpoint(
    remote_connections: &RemoteStageConnectionManager,
    target_name: &str,
    stage_id: &str,
    primary: std::net::SocketAddr,
) -> i64 {
    for team_id in 1..2_000 {
        let candidates = remote_connections
            .candidate_endpoints_for_stage(target_name, stage_id, &RoutingKey::team_id(team_id))
            .await
            .unwrap();
        if candidates.first() == Some(&primary) {
            return team_id;
        }
    }

    panic!("could not find routing key for primary endpoint {primary}");
}

fn assert_retry_result(result: &ProcessExceptionBatchResult) {
    assert!(matches!(
        result.outcome,
        Some(process_exception_batch_result::Outcome::Retry(_))
    ));
}

#[tokio::test]
async fn process_exception_batch_streams_next_result_for_each_event() {
    let server = start_test_server().await;
    let mut client = create_client(&server).await;
    let request = batch_request(vec![
        exception_event("event-1", br#"{"event":"$exception","index":1}"#.to_vec()),
        exception_event("event-2", br#"{"event":"$exception","index":2}"#.to_vec()),
    ]);

    let results = process_batch(&mut client, request).await;

    assert_eq!(results.len(), 2);
    assert_eq!(results[0].event_id, "event-1");
    assert!(matches!(
        results[0].outcome,
        Some(process_exception_batch_result::Outcome::Next(_))
    ));
    assert_eq!(results[1].event_id, "event-2");
    assert!(matches!(
        results[1].outcome,
        Some(process_exception_batch_result::Outcome::Next(_))
    ));
}

#[tokio::test]
async fn process_exception_batch_streams_ordered_prefix_before_later_slow_events() {
    let resolution_server = start_cymbal_stage_server(TerminalOrSlowResolutionStageService {
        delay: std::time::Duration::from_millis(250),
    })
    .await;
    let remote_connections = RemoteStageConnectionManager::new();
    remote_connections
        .refresh_target(&RemoteStageTarget::new(
            "resolution-stage",
            "127.0.0.1",
            resolution_server.addr.port(),
        ))
        .await
        .unwrap();
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage(RESOLUTION_STAGE_ID, "resolution-stage")
        .unwrap();
    let service =
        CymbalPipelineService::with_registry(registry).with_remote_connections(remote_connections);
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;
    let mut events = vec![exception_event(
        "terminal-0",
        br#"{"event":"$exception","index":0}"#.to_vec(),
    )];
    events.extend(numbered_exception_events("fast", 1, 63));
    events.push(exception_event(
        "slow-64",
        br#"{"event":"$exception","index":64}"#.to_vec(),
    ));

    let mut stream = client
        .process_exception_batch(batch_request(events))
        .await
        .unwrap()
        .into_inner();

    let first = tokio::time::timeout(std::time::Duration::from_millis(150), stream.message())
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(first.event_id, "terminal-0");
    assert_retry_result(&first);

    let remaining = stream.try_collect::<Vec<_>>().await.unwrap();
    assert_eq!(remaining.len(), 64);
    assert_eq!(remaining.last().unwrap().event_id, "slow-64");
}

#[tokio::test]
async fn process_exception_batch_buffers_later_fast_results_to_preserve_input_order() {
    let resolution_server = start_cymbal_stage_server(TerminalOrSlowResolutionStageService {
        delay: std::time::Duration::from_millis(200),
    })
    .await;
    let remote_connections = RemoteStageConnectionManager::new();
    remote_connections
        .refresh_target(&RemoteStageTarget::new(
            "resolution-stage",
            "127.0.0.1",
            resolution_server.addr.port(),
        ))
        .await
        .unwrap();
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage(RESOLUTION_STAGE_ID, "resolution-stage")
        .unwrap();
    let service =
        CymbalPipelineService::with_registry(registry).with_remote_connections(remote_connections);
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;
    let mut events = numbered_exception_events("slow", 0, 64);
    events.push(exception_event(
        "terminal-64",
        br#"{"event":"$exception","index":64}"#.to_vec(),
    ));

    let mut stream = client
        .process_exception_batch(batch_request(events))
        .await
        .unwrap()
        .into_inner();

    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(75), stream.message())
            .await
            .is_err()
    );

    let results = stream.try_collect::<Vec<_>>().await.unwrap();
    assert_eq!(results.len(), 65);
    assert_eq!(results.first().unwrap().event_id, "slow-0");
    assert_eq!(results.last().unwrap().event_id, "terminal-64");
    assert_retry_result(results.last().unwrap());
}

#[tokio::test]
async fn process_exception_batch_releases_in_flight_guard_after_stream_cancellation() {
    let resolution_server = start_cymbal_stage_server(TerminalOrSlowResolutionStageService {
        delay: std::time::Duration::from_millis(100),
    })
    .await;
    let remote_connections = RemoteStageConnectionManager::new();
    remote_connections
        .refresh_target(&RemoteStageTarget::new(
            "resolution-stage",
            "127.0.0.1",
            resolution_server.addr.port(),
        ))
        .await
        .unwrap();
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage(RESOLUTION_STAGE_ID, "resolution-stage")
        .unwrap();
    let service = CymbalPipelineService::with_registry(registry)
        .with_remote_connections(remote_connections)
        .with_in_flight_tracker(cymbal_server::observability::InFlightBatchTracker::standalone(1));
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;
    let mut events = vec![exception_event(
        "terminal-0",
        br#"{"event":"$exception","index":0}"#.to_vec(),
    )];
    events.extend(numbered_exception_events("fast", 1, 63));
    events.push(exception_event(
        "slow-64",
        br#"{"event":"$exception","index":64}"#.to_vec(),
    ));

    let mut stream = client
        .process_exception_batch(batch_request(events))
        .await
        .unwrap()
        .into_inner();
    let _first = stream.message().await.unwrap().unwrap();
    drop(stream);

    tokio::time::sleep(std::time::Duration::from_millis(150)).await;
    let results = process_batch(
        &mut client,
        batch_request(vec![exception_event(
            "after-cancel",
            br#"{"event":"$exception","index":1}"#.to_vec(),
        )]),
    )
    .await;

    assert_eq!(results.len(), 1);
    assert_eq!(results[0].event_id, "after-cancel");
}

#[tokio::test]
async fn process_exception_batch_preserves_event_properties_in_next_result() {
    let server = start_test_server().await;
    let mut client = create_client(&server).await;
    let properties_json = br#"{"event":"$exception","message":"boom"}"#.to_vec();
    let request = batch_request(vec![exception_event("event-1", properties_json.clone())]);

    let results = process_batch(&mut client, request).await;

    assert_eq!(results.len(), 1);
    let Some(process_exception_batch_result::Outcome::Next(next)) = &results[0].outcome else {
        panic!("expected Next result");
    };
    assert_eq!(next.properties_json, properties_json);
    assert!(next.metadata.is_empty());
}

#[tokio::test]
async fn process_exception_batch_with_empty_batch_streams_no_results() {
    let server = start_test_server().await;
    let mut client = create_client(&server).await;
    let request = batch_request(Vec::new());

    let results = process_batch(&mut client, request).await;

    assert!(results.is_empty());
}

#[tokio::test]
async fn process_exception_batch_rejects_batches_over_limit() {
    let service = CymbalPipelineService::new().with_limits(PipelineLimits {
        max_batch_events: 1,
    });
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;
    let request = batch_request(vec![
        exception_event("event-1", br#"{}"#.to_vec()),
        exception_event("event-2", br#"{}"#.to_vec()),
    ]);

    let error = client.process_exception_batch(request).await.unwrap_err();

    assert_eq!(error.code(), Code::ResourceExhausted);
}

#[tokio::test]
async fn process_exception_batch_returns_retry_for_remote_item_errors() {
    let stage_server = start_cymbal_stage_server(PartialFailureResolutionStageService).await;
    let remote_connections = RemoteStageConnectionManager::new();
    remote_connections
        .refresh_target(&RemoteStageTarget::new(
            "resolution-stage",
            "127.0.0.1",
            stage_server.addr.port(),
        ))
        .await
        .unwrap();
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage("resolution:v1", "resolution-stage")
        .unwrap();
    let service =
        CymbalPipelineService::with_registry(registry).with_remote_connections(remote_connections);
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;
    let request = batch_request(vec![
        exception_event("event-1", br#"{"event":"$exception","index":1}"#.to_vec()),
        exception_event("event-2", br#"{"event":"$exception","index":2}"#.to_vec()),
    ]);

    let results = process_batch(&mut client, request).await;

    assert_eq!(results.len(), 2);
    assert!(results.iter().any(|result| {
        result.event_id == "event-1"
            && matches!(
                result.outcome,
                Some(process_exception_batch_result::Outcome::Next(_))
            )
    }));
    assert!(results.iter().any(|result| {
        result.event_id == "event-2"
            && matches!(
                result.outcome,
                Some(process_exception_batch_result::Outcome::Retry(_))
            )
    }));
}

#[tokio::test]
async fn process_exception_batch_preserves_order_across_boundary_and_stage_terminal_results() {
    let stage_server = start_cymbal_stage_server(PartialFailureResolutionStageService).await;
    let remote_connections = RemoteStageConnectionManager::new();
    remote_connections
        .refresh_target(&RemoteStageTarget::new(
            "resolution-stage",
            "127.0.0.1",
            stage_server.addr.port(),
        ))
        .await
        .unwrap();
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage(RESOLUTION_STAGE_ID, "resolution-stage")
        .unwrap();
    let service =
        CymbalPipelineService::with_registry(registry).with_remote_connections(remote_connections);
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;
    let request = batch_request(vec![
        exception_event("invalid-json", br#"{"#.to_vec()),
        exception_event("event-1", br#"{"event":"$exception","index":1}"#.to_vec()),
        exception_event_for_team(
            "missing-team",
            0,
            br#"{"event":"$exception","index":2}"#.to_vec(),
        ),
        exception_event("event-2", br#"{"event":"$exception","index":3}"#.to_vec()),
    ]);

    let results = process_batch(&mut client, request).await;

    assert_eq!(
        results
            .iter()
            .map(|result| result.event_id.as_str())
            .collect::<Vec<_>>(),
        vec!["invalid-json", "event-1", "missing-team", "event-2"]
    );
    assert!(matches!(
        results[0].outcome,
        Some(process_exception_batch_result::Outcome::Error(_))
    ));
    assert!(matches!(
        results[1].outcome,
        Some(process_exception_batch_result::Outcome::Next(_))
    ));
    assert!(matches!(
        results[2].outcome,
        Some(process_exception_batch_result::Outcome::Drop(_))
    ));
    assert!(matches!(
        results[3].outcome,
        Some(process_exception_batch_result::Outcome::Retry(_))
    ));
}

#[tokio::test]
async fn process_exception_batch_maps_remote_retryable_and_terminal_item_failures() {
    let stage_server = start_cymbal_stage_server(MixedItemFailureResolutionStageService).await;
    let remote_connections = RemoteStageConnectionManager::new();
    remote_connections
        .refresh_target(&RemoteStageTarget::new(
            "resolution-stage",
            "127.0.0.1",
            stage_server.addr.port(),
        ))
        .await
        .unwrap();
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage(RESOLUTION_STAGE_ID, "resolution-stage")
        .unwrap();
    let service =
        CymbalPipelineService::with_registry(registry).with_remote_connections(remote_connections);
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;
    let request = batch_request(vec![
        exception_event(
            "success-item",
            br#"{"event":"$exception","index":1}"#.to_vec(),
        ),
        exception_event(
            "retry-item",
            br#"{"event":"$exception","index":2}"#.to_vec(),
        ),
        exception_event(
            "error-item",
            br#"{"event":"$exception","index":3}"#.to_vec(),
        ),
    ]);

    let results = process_batch(&mut client, request).await;

    assert_eq!(
        results
            .iter()
            .map(|result| result.event_id.as_str())
            .collect::<Vec<_>>(),
        vec!["success-item", "retry-item", "error-item"]
    );
    assert!(matches!(
        results[0].outcome,
        Some(process_exception_batch_result::Outcome::Next(_))
    ));
    let Some(process_exception_batch_result::Outcome::Retry(retry)) = &results[1].outcome else {
        panic!("expected retry outcome");
    };
    assert_eq!(retry.reason, "retry this event");
    let Some(process_exception_batch_result::Outcome::Error(error)) = &results[2].outcome else {
        panic!("expected error outcome");
    };
    assert_eq!(error.message, "do not retry this event");
    assert_eq!(error.code, "remote_stage_item_failed");
    assert!(!error.retryable);
}

#[tokio::test]
async fn process_exception_batch_surfaces_duplicate_and_unknown_remote_results_as_stream_errors() {
    for (mode, expected_message) in [
        (BadRemoteResultMode::Duplicate, "duplicate item id"),
        (BadRemoteResultMode::Unknown, "unknown id"),
    ] {
        let stage_server =
            start_cymbal_stage_server(BadRemoteResultResolutionStageService { mode }).await;
        let remote_connections = RemoteStageConnectionManager::new();
        remote_connections
            .refresh_target(&RemoteStageTarget::new(
                "resolution-stage",
                "127.0.0.1",
                stage_server.addr.port(),
            ))
            .await
            .unwrap();
        let mut registry = StageRegistry::local_default();
        registry
            .set_remote_stage(RESOLUTION_STAGE_ID, "resolution-stage")
            .unwrap();
        let service = CymbalPipelineService::with_registry(registry)
            .with_remote_connections(remote_connections);
        let server = start_pipeline_server(service).await;
        let mut client = create_client(&server).await;
        let request = batch_request(vec![exception_event(
            "event-1",
            br#"{"event":"$exception","index":1}"#.to_vec(),
        )]);

        let status = process_batch_stream_error(&mut client, request).await;

        assert_eq!(status.code(), Code::Internal);
        assert!(
            status.message().contains(expected_message),
            "expected {expected_message:?} in {status}"
        );
    }
}

#[tokio::test]
async fn process_exception_batch_local_and_remote_results_match_for_representative_batch() {
    let request = batch_request(vec![
        exception_event(
            "parity-1",
            br#"{"event":"$exception","message":"first"}"#.to_vec(),
        ),
        exception_event(
            "parity-2",
            br#"{"event":"$exception","message":"second"}"#.to_vec(),
        ),
    ]);
    let local_server = start_test_server().await;
    let mut local_client = create_client(&local_server).await;
    let local_results = process_batch(&mut local_client, request.clone()).await;

    let stage_server = start_stage_server().await;
    let remote_connections = RemoteStageConnectionManager::new();
    remote_connections
        .refresh_target(&RemoteStageTarget::new(
            "stage-server",
            "127.0.0.1",
            stage_server.addr.port(),
        ))
        .await
        .unwrap();
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage(RESOLUTION_STAGE_ID, "stage-server")
        .unwrap();
    registry
        .set_remote_stage("grouping:v1", "stage-server")
        .unwrap();
    registry
        .set_remote_stage(LINKING_STAGE_ID, "stage-server")
        .unwrap();
    registry
        .set_remote_stage(ALERTING_STAGE_ID, "stage-server")
        .unwrap();
    let remote_server = start_pipeline_server(
        CymbalPipelineService::with_registry(registry).with_remote_connections(remote_connections),
    )
    .await;
    let mut remote_client = create_client(&remote_server).await;
    let remote_results = process_batch(&mut remote_client, request).await;

    assert_eq!(remote_results, local_results);
}

#[tokio::test]
async fn grpc_integration_remote_resolution_affinity_keeps_same_primary_while_healthy() {
    let first_seen = Arc::new(Mutex::new(Vec::new()));
    let second_seen = Arc::new(Mutex::new(Vec::new()));
    let first_stage = start_cymbal_stage_server(RecordingResolutionStageService {
        seen_event_ids: first_seen.clone(),
        reverse_results: false,
    })
    .await;
    let second_stage = start_cymbal_stage_server(RecordingResolutionStageService {
        seen_event_ids: second_seen.clone(),
        reverse_results: false,
    })
    .await;
    let remote_connections = RemoteStageConnectionManager::with_options_and_routing(
        RemoteStageConnectionOptions::default(),
        default_remote_routing_config(),
    );
    refresh_two_pod_target(
        &remote_connections,
        "resolution-stage",
        &first_stage,
        &second_stage,
    )
    .await;
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage(RESOLUTION_STAGE_ID, "resolution-stage")
        .unwrap();
    let service = CymbalPipelineService::with_registry(registry)
        .with_remote_connections(remote_connections.clone());
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;

    let first_results = process_batch(
        &mut client,
        batch_request(vec![exception_event_for_team(
            "affinity-1",
            7,
            br#"{"event":"$exception","index":1}"#.to_vec(),
        )]),
    )
    .await;
    let second_results = process_batch(
        &mut client,
        batch_request(vec![exception_event_for_team(
            "affinity-2",
            7,
            br#"{"event":"$exception","index":2}"#.to_vec(),
        )]),
    )
    .await;

    assert!(matches!(
        first_results[0].outcome,
        Some(process_exception_batch_result::Outcome::Next(_))
    ));
    assert!(matches!(
        second_results[0].outcome,
        Some(process_exception_batch_result::Outcome::Next(_))
    ));
    let first_seen = first_seen.lock().unwrap().clone();
    let second_seen = second_seen.lock().unwrap().clone();
    assert!(
        first_seen == ["affinity-1", "affinity-2"] || second_seen == ["affinity-1", "affinity-2"],
        "expected same affinity primary, first_seen={first_seen:?}, second_seen={second_seen:?}"
    );
}

#[tokio::test]
async fn grpc_integration_remote_resolution_overload_falls_back_and_preserves_output_order() {
    let overloaded_calls = Arc::new(AtomicUsize::new(0));
    let fallback_seen = Arc::new(Mutex::new(Vec::new()));
    let overloaded_stage = start_cymbal_stage_server(OverloadedStageService {
        calls: overloaded_calls.clone(),
    })
    .await;
    let fallback_stage = start_cymbal_stage_server(RecordingResolutionStageService {
        seen_event_ids: fallback_seen.clone(),
        reverse_results: true,
    })
    .await;
    let remote_connections = RemoteStageConnectionManager::with_options_and_routing(
        RemoteStageConnectionOptions::default(),
        default_remote_routing_config(),
    );
    refresh_two_pod_target(
        &remote_connections,
        "resolution-stage",
        &overloaded_stage,
        &fallback_stage,
    )
    .await;
    let team_id = team_id_for_primary_endpoint(
        &remote_connections,
        "resolution-stage",
        RESOLUTION_STAGE_ID,
        overloaded_stage.addr,
    )
    .await;
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage(RESOLUTION_STAGE_ID, "resolution-stage")
        .unwrap();
    let service = CymbalPipelineService::with_registry(registry)
        .with_remote_connections(remote_connections.clone());
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;

    let results = process_batch(
        &mut client,
        batch_request(vec![
            exception_event_for_team(
                "fallback-1",
                team_id,
                br#"{"event":"$exception","index":1}"#.to_vec(),
            ),
            exception_event_for_team(
                "fallback-2",
                team_id,
                br#"{"event":"$exception","index":2}"#.to_vec(),
            ),
            exception_event_for_team(
                "fallback-3",
                team_id,
                br#"{"event":"$exception","index":3}"#.to_vec(),
            ),
        ]),
    )
    .await;

    assert_eq!(overloaded_calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        fallback_seen.lock().unwrap().as_slice(),
        ["fallback-3", "fallback-2", "fallback-1"]
    );
    assert_eq!(
        results
            .iter()
            .map(|result| result.event_id.as_str())
            .collect::<Vec<_>>(),
        vec!["fallback-1", "fallback-2", "fallback-3"]
    );
    assert!(results.iter().all(|result| matches!(
        result.outcome,
        Some(process_exception_batch_result::Outcome::Next(_))
    )));
}

#[tokio::test]
async fn grpc_integration_remote_resolution_all_candidates_overloaded_returns_retry_results() {
    let first_calls = Arc::new(AtomicUsize::new(0));
    let second_calls = Arc::new(AtomicUsize::new(0));
    let first_stage = start_cymbal_stage_server(OverloadedStageService {
        calls: first_calls.clone(),
    })
    .await;
    let second_stage = start_cymbal_stage_server(OverloadedStageService {
        calls: second_calls.clone(),
    })
    .await;
    let remote_connections = RemoteStageConnectionManager::with_options_and_routing(
        RemoteStageConnectionOptions::default(),
        default_remote_routing_config(),
    );
    refresh_two_pod_target(
        &remote_connections,
        "resolution-stage",
        &first_stage,
        &second_stage,
    )
    .await;
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage(RESOLUTION_STAGE_ID, "resolution-stage")
        .unwrap();
    let service = CymbalPipelineService::with_registry(registry)
        .with_remote_connections(remote_connections.clone());
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;

    let results = process_batch(
        &mut client,
        batch_request(vec![
            exception_event(
                "overloaded-1",
                br#"{"event":"$exception","index":1}"#.to_vec(),
            ),
            exception_event(
                "overloaded-2",
                br#"{"event":"$exception","index":2}"#.to_vec(),
            ),
        ]),
    )
    .await;

    assert_eq!(first_calls.load(Ordering::SeqCst), 1);
    assert_eq!(second_calls.load(Ordering::SeqCst), 1);
    assert_eq!(results.len(), 2);
    assert_retry_result(&results[0]);
    assert_retry_result(&results[1]);
}

#[tokio::test]
async fn grpc_integration_linking_and_alerting_timeouts_do_not_fallback_by_default() {
    assert_timeout_uses_single_remote_stage_attempt(LINKING_STAGE_ID, TerminalStageInput::Linking)
        .await;
    assert_timeout_uses_single_remote_stage_attempt(
        ALERTING_STAGE_ID,
        TerminalStageInput::Alerting,
    )
    .await;
}

#[tokio::test]
async fn process_exception_batch_can_run_stages_remotely() {
    let stage_server = start_stage_server().await;
    let remote_connections = RemoteStageConnectionManager::new();
    remote_connections
        .refresh_target(&RemoteStageTarget::new(
            "stage-server",
            "127.0.0.1",
            stage_server.addr.port(),
        ))
        .await
        .unwrap();
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage("resolution:v1", "stage-server")
        .unwrap();
    registry
        .set_remote_stage("grouping:v1", "stage-server")
        .unwrap();
    registry
        .set_remote_stage("linking:v1", "stage-server")
        .unwrap();
    registry
        .set_remote_stage("alerting:v1", "stage-server")
        .unwrap();
    let service =
        CymbalPipelineService::with_registry(registry).with_remote_connections(remote_connections);
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;
    let properties_json = br#"{"event":"$exception","message":"boom"}"#.to_vec();
    let request = batch_request(vec![exception_event("event-1", properties_json.clone())]);

    let results = process_batch(&mut client, request).await;

    assert_eq!(results.len(), 1);
    let Some(process_exception_batch_result::Outcome::Next(next)) = &results[0].outcome else {
        panic!("expected Next result");
    };
    assert_eq!(next.properties_json, properties_json);
}

#[tokio::test]
async fn process_exception_batch_can_run_alerting_remotely() {
    let alerting_server = start_cymbal_stage_server(MetadataAlertingStageService).await;
    let remote_connections = RemoteStageConnectionManager::new();
    remote_connections
        .refresh_target(&RemoteStageTarget::new(
            "alerting-stage",
            "127.0.0.1",
            alerting_server.addr.port(),
        ))
        .await
        .unwrap();
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage("alerting:v1", "alerting-stage")
        .unwrap();
    let service =
        CymbalPipelineService::with_registry(registry).with_remote_connections(remote_connections);
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;
    let request = batch_request(vec![exception_event(
        "event-1",
        br#"{"event":"$exception","message":"boom"}"#.to_vec(),
    )]);

    let results = process_batch(&mut client, request).await;

    assert_eq!(results.len(), 1);
    let Some(process_exception_batch_result::Outcome::Next(next)) = &results[0].outcome else {
        panic!("expected Next result");
    };
    assert_eq!(
        next.metadata.get("remote_alerting"),
        Some(&"ran".to_string())
    );
}

#[tokio::test]
async fn grpc_integration_rate_limit_can_run_remotely_and_skips_dropped_events_downstream() {
    let limiter = FakeLimiter::new(vec![
        EvalResult::Allowed,
        EvalResult::Limited(limited_response("team_id:1")),
        EvalResult::Allowed,
    ]);
    let limiter_server = start_cymbal_stage_server(
        CymbalStageService::new(StageRegistry::local_default())
            .with_runtime_stages(runtime_stages(rate_limit_stage(limiter.clone()))),
    )
    .await;
    let seen_by_resolution = Arc::new(Mutex::new(Vec::new()));
    let resolution_server = start_cymbal_stage_server(CountingResolutionStageService {
        seen_event_ids: seen_by_resolution.clone(),
    })
    .await;
    let remote_connections = RemoteStageConnectionManager::new();
    remote_connections
        .refresh_targets(&[
            RemoteStageTarget::new("rate-limiter", "127.0.0.1", limiter_server.addr.port()),
            RemoteStageTarget::new(
                "resolution-stage",
                "127.0.0.1",
                resolution_server.addr.port(),
            ),
        ])
        .await
        .unwrap();
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage("rate-limiting:v1", "rate-limiter")
        .unwrap();
    registry
        .set_remote_stage("resolution:v1", "resolution-stage")
        .unwrap();
    let service =
        CymbalPipelineService::with_registry(registry).with_remote_connections(remote_connections);
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;
    let request = batch_request(vec![
        exception_event("event-1", br#"{"event":"$exception","index":1}"#.to_vec()),
        exception_event("event-2", br#"{"event":"$exception","index":2}"#.to_vec()),
        exception_event("event-3", br#"{"event":"$exception","index":3}"#.to_vec()),
    ]);

    let results = process_batch(&mut client, request).await;

    assert_eq!(
        results
            .iter()
            .map(|result| result.event_id.as_str())
            .collect::<Vec<_>>(),
        vec!["event-1", "event-2", "event-3"]
    );
    assert_eq!(limiter.keys(), vec!["team_id:1", "team_id:1", "team_id:1"]);
    assert!(matches!(
        results[0].outcome,
        Some(process_exception_batch_result::Outcome::Next(_))
    ));
    let Some(process_exception_batch_result::Outcome::Drop(drop)) = &results[1].outcome else {
        panic!("expected dropped rate-limited event");
    };
    assert_eq!(drop.reason, "rate_limited:team_id");
    assert!(matches!(
        results[2].outcome,
        Some(process_exception_batch_result::Outcome::Next(_))
    ));
    assert_eq!(
        seen_by_resolution.lock().unwrap().as_slice(),
        ["event-1", "event-3"]
    );
}

#[tokio::test]
async fn grpc_integration_rate_limit_remote_failures_fail_open_per_event() {
    let limiter_server = start_cymbal_stage_server(FailingStageService).await;
    let remote_connections = RemoteStageConnectionManager::new();
    remote_connections
        .refresh_target(&RemoteStageTarget::new(
            "rate-limiter",
            "127.0.0.1",
            limiter_server.addr.port(),
        ))
        .await
        .unwrap();
    let mut registry = StageRegistry::local_default();
    registry
        .set_remote_stage("rate-limiting:v1", "rate-limiter")
        .unwrap();
    let service =
        CymbalPipelineService::with_registry(registry).with_remote_connections(remote_connections);
    let server = start_pipeline_server(service).await;
    let mut client = create_client(&server).await;
    let request = batch_request(vec![
        exception_event("event-1", br#"{"event":"$exception","index":1}"#.to_vec()),
        exception_event("event-2", br#"{"event":"$exception","index":2}"#.to_vec()),
    ]);

    let results = process_batch(&mut client, request).await;

    assert_eq!(results.len(), 2);
    assert!(results.iter().all(|result| matches!(
        result.outcome,
        Some(process_exception_batch_result::Outcome::Next(_))
    )));
}
