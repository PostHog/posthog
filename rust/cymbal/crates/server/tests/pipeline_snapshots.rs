use cymbal_api::cymbal::v1::cymbal_ingestion_client::CymbalIngestionClient;
use cymbal_api::cymbal::v1::cymbal_ingestion_server::CymbalIngestionServer;
use cymbal_api::cymbal::v1::cymbal_stage_runtime_server::CymbalStageRuntimeServer;
use cymbal_api::cymbal::v1::{
    process_exception_batch_result, BatchContext, ExceptionEvent, ProcessExceptionBatchRequest,
    ProcessExceptionBatchResult,
};
use cymbal_server::pipeline::CymbalPipelineService;
use cymbal_server::registry::StageRegistry;
use cymbal_server::remote::{RemoteStageConnectionManager, RemoteStageTarget};
use cymbal_server::stage::CymbalStageService;
use futures::TryStreamExt;
use serde_json::{json, Value};
use tokio::net::TcpListener;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::TcpListenerStream;
use tonic::transport::{Channel, Server};

struct TestServer {
    addr: std::net::SocketAddr,
    handle: JoinHandle<()>,
}

impl Drop for TestServer {
    fn drop(&mut self) {
        self.handle.abort();
    }
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
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let service = CymbalStageService::new(StageRegistry::local_default());

    let handle = tokio::spawn(async move {
        Server::builder()
            .add_service(CymbalStageRuntimeServer::new(service))
            .serve_with_incoming(TcpListenerStream::new(listener))
            .await
            .unwrap();
    });

    TestServer { addr, handle }
}

async fn create_client(server: &TestServer) -> CymbalIngestionClient<Channel> {
    CymbalIngestionClient::connect(format!("http://{}", server.addr))
        .await
        .unwrap()
}

async fn process_exception_batch(
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

fn batch_request(batch_id: &str, events: Vec<ExceptionEvent>) -> ProcessExceptionBatchRequest {
    ProcessExceptionBatchRequest {
        context: Some(BatchContext {
            batch_id: batch_id.to_string(),
            metadata: [("source".to_string(), "snapshot-test".to_string())].into(),
        }),
        events,
        options: None,
    }
}

fn input_event(event_id: &str, message: &str) -> ExceptionEvent {
    input_event_for_team(event_id, 1, exception_properties_json(message))
}

fn input_event_for_team(event_id: &str, team_id: i64, properties_json: Vec<u8>) -> ExceptionEvent {
    ExceptionEvent {
        event_id: event_id.to_string(),
        team_id,
        distinct_id: format!("distinct-{event_id}"),
        timestamp: None,
        properties_json,
    }
}

fn exception_properties_json(message: &str) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "$exception_message": message,
        "$exception_type": "Error",
        "$exception_list": [{
            "type": "Error",
            "value": message,
            "stacktrace": {
                "frames": [{
                    "filename": "app.js",
                    "function": "runExample",
                    "lineno": 10,
                    "colno": 5,
                }]
            }
        }],
    }))
    .unwrap()
}

fn snapshot_payload(
    request: &ProcessExceptionBatchRequest,
    results: &[ProcessExceptionBatchResult],
) -> Value {
    json!({
        "request": request_to_json(request),
        "results": results_to_json(results),
    })
}

fn request_to_json(request: &ProcessExceptionBatchRequest) -> Value {
    json!({
        "context": request.context.as_ref().map(|context| json!({
            "batch_id": context.batch_id,
            "metadata": context.metadata,
        })),
        "events": request.events.iter().map(input_event_to_json).collect::<Vec<_>>(),
        "options": request.options.as_ref().map(|options| json!({
            "skip_alerting": options.skip_alerting,
            "emit_internal_events": options.emit_internal_events,
            "emit_signals": options.emit_signals,
        })),
    })
}

fn input_event_to_json(event: &ExceptionEvent) -> Value {
    json!({
        "event_id": event.event_id,
        "team_id": event.team_id,
        "distinct_id": event.distinct_id,
        "properties_json": parse_json_bytes(&event.properties_json),
    })
}

fn results_to_json(results: &[ProcessExceptionBatchResult]) -> Value {
    json!(results.iter().map(event_result_to_json).collect::<Vec<_>>())
}

fn event_result_to_json(result: &ProcessExceptionBatchResult) -> Value {
    match &result.outcome {
        Some(process_exception_batch_result::Outcome::Next(next)) => json!({
            "event_id": result.event_id,
            "outcome": "Next",
            "properties_json": parse_json_bytes(&next.properties_json),
            "metadata": next.metadata,
        }),
        Some(process_exception_batch_result::Outcome::Drop(drop)) => json!({
            "event_id": result.event_id,
            "outcome": "Drop",
            "reason": drop.reason,
        }),
        Some(process_exception_batch_result::Outcome::Retry(retry)) => json!({
            "event_id": result.event_id,
            "outcome": "Retry",
            "reason": retry.reason,
            "retry_after_ms": retry.retry_after_ms,
        }),
        Some(process_exception_batch_result::Outcome::Error(error)) => json!({
            "event_id": result.event_id,
            "outcome": "Error",
            "message": error.message,
            "code": error.code,
            "retryable": error.retryable,
        }),
        None => json!({
            "event_id": result.event_id,
            "outcome": null,
        }),
    }
}

fn parse_json_bytes(payload: &[u8]) -> Value {
    serde_json::from_slice(payload).unwrap_or_else(|_| json!(String::from_utf8_lossy(payload)))
}

#[tokio::test]
async fn local_pipeline_event_format_matches_snapshot() {
    let server = start_pipeline_server(CymbalPipelineService::new()).await;
    let mut client = create_client(&server).await;
    let request = batch_request(
        "local-pipeline-snapshot",
        vec![input_event("event-1", "local pipeline example")],
    );

    let results = process_exception_batch(&mut client, request.clone()).await;

    insta::assert_json_snapshot!(snapshot_payload(&request, &results));
}

#[tokio::test]
async fn empty_batch_format_matches_snapshot() {
    let server = start_pipeline_server(CymbalPipelineService::new()).await;
    let mut client = create_client(&server).await;
    let request = batch_request("empty-batch-snapshot", Vec::new());

    let results = process_exception_batch(&mut client, request.clone()).await;

    insta::assert_json_snapshot!(snapshot_payload(&request, &results));
}

#[tokio::test]
async fn invalid_properties_format_matches_snapshot() {
    let server = start_pipeline_server(CymbalPipelineService::new()).await;
    let mut client = create_client(&server).await;
    let request = batch_request(
        "invalid-properties-snapshot",
        vec![input_event_for_team(
            "invalid-properties",
            1,
            br#"["not", "an", "object"]"#.to_vec(),
        )],
    );

    let results = process_exception_batch(&mut client, request.clone()).await;

    insta::assert_json_snapshot!(snapshot_payload(&request, &results));
}

#[tokio::test]
async fn mixed_drop_error_next_format_matches_snapshot() {
    let server = start_pipeline_server(CymbalPipelineService::new()).await;
    let mut client = create_client(&server).await;
    let request = batch_request(
        "mixed-outcomes-snapshot",
        vec![
            input_event("next-event", "mixed outcome next"),
            input_event_for_team("drop-event", 0, exception_properties_json("missing team")),
            input_event_for_team("error-event", 1, br#"{"#.to_vec()),
        ],
    );

    let results = process_exception_batch(&mut client, request.clone()).await;

    insta::assert_json_snapshot!(snapshot_payload(&request, &results));
}

#[tokio::test]
async fn remote_pipeline_event_format_matches_snapshot() {
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
    let server = start_pipeline_server(
        CymbalPipelineService::with_registry(registry).with_remote_connections(remote_connections),
    )
    .await;
    let mut client = create_client(&server).await;
    let request = batch_request(
        "remote-pipeline-snapshot",
        vec![
            input_event("event-1", "remote pipeline first event"),
            input_event("event-2", "remote pipeline second event"),
        ],
    );

    let results = process_exception_batch(&mut client, request.clone()).await;

    insta::assert_json_snapshot!(snapshot_payload(&request, &results));
}
