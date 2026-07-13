use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Arc,
};
use std::time::Duration;

use async_trait::async_trait;
use cymbal::error::{ResolveError, UnhandledError};
use cymbal::frames::{Frame, RawFrame};
use cymbal::langs::native::DebugImage;
use cymbal::modes::resolution::load_monitor::LoadMonitor;
use cymbal::modes::resolution::service::{CymbalResolutionService, ServiceConfig};
use cymbal::symbolication::symbol::SymbolResolver;
use cymbal::symbolication::symbol_store::{chunk_id::OrChunkId, proguard::ProguardRef};
use cymbal::types::operator::TeamId;
use cymbal::types::{Exception, Stacktrace};
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_client::CymbalResolutionClient;
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolution;
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolutionServer;
use cymbal_proto::cymbal::resolution::v1::{
    resolve_outcome, ErrorKind, ResolveItem, ResolveOutcome, SubscribeRequest,
};
use futures::StreamExt;
use tokio::sync::Semaphore;
use tonic::transport::{Channel, Server};
use tonic::Request;

#[derive(Default)]
struct FakeResolver {
    fail_unhandled: bool,
    resolved_frames: Vec<Frame>,
}

#[async_trait]
impl SymbolResolver for FakeResolver {
    async fn resolve_raw_frame(
        &self,
        _team_id: TeamId,
        _frame: &RawFrame,
        _debug_images: &[DebugImage],
    ) -> Result<Vec<Frame>, UnhandledError> {
        if self.fail_unhandled {
            return Err(UnhandledError::Other("forced resolver failure".to_string()));
        }
        Ok(self.resolved_frames.clone())
    }

    async fn resolve_java_class(
        &self,
        _team_id: TeamId,
        _symbolset_ref: OrChunkId<ProguardRef>,
        _class: String,
    ) -> Result<String, ResolveError> {
        unreachable!("fake resolver does not need java class resolution for these tests")
    }

    async fn resolve_dart_minified_name(
        &self,
        _team_id: TeamId,
        _symbolset_ref: String,
        _minified_name: &str,
    ) -> Result<String, ResolveError> {
        unreachable!("fake resolver does not need dart name resolution for these tests")
    }
}

struct SlowResolver {
    delay: Duration,
    first_call_delay: Option<Duration>,
    active: Arc<AtomicUsize>,
    max_active: Arc<AtomicUsize>,
    started: Arc<AtomicUsize>,
}

#[async_trait]
impl SymbolResolver for SlowResolver {
    async fn resolve_raw_frame(
        &self,
        _team_id: TeamId,
        _frame: &RawFrame,
        _debug_images: &[DebugImage],
    ) -> Result<Vec<Frame>, UnhandledError> {
        let call_index = self.started.fetch_add(1, Ordering::AcqRel);
        let active = self.active.fetch_add(1, Ordering::AcqRel) + 1;
        update_max(&self.max_active, active);

        let delay = if call_index == 0 {
            self.first_call_delay.unwrap_or(self.delay)
        } else {
            self.delay
        };
        tokio::time::sleep(delay).await;
        self.active.fetch_sub(1, Ordering::AcqRel);
        Ok(Vec::new())
    }

    async fn resolve_java_class(
        &self,
        _team_id: TeamId,
        _symbolset_ref: OrChunkId<ProguardRef>,
        _class: String,
    ) -> Result<String, ResolveError> {
        unreachable!("slow resolver does not need java class resolution for these tests")
    }

    async fn resolve_dart_minified_name(
        &self,
        _team_id: TeamId,
        _symbolset_ref: String,
        _minified_name: &str,
    ) -> Result<String, ResolveError> {
        unreachable!("slow resolver does not need dart name resolution for these tests")
    }
}

fn update_max(max_active: &AtomicUsize, candidate: usize) {
    let mut current = max_active.load(Ordering::Acquire);
    while candidate > current {
        match max_active.compare_exchange(current, candidate, Ordering::AcqRel, Ordering::Acquire) {
            Ok(_) => return,
            Err(actual) => current = actual,
        }
    }
}

fn fast_service_config() -> ServiceConfig {
    ServiceConfig {
        default_tick_interval: Duration::from_millis(20),
        min_tick_interval: Duration::from_millis(1),
        max_tick_interval: Duration::from_secs(1),
    }
}

fn make_service(resolver: FakeResolver) -> CymbalResolutionService {
    make_service_with_config(
        Arc::new(resolver),
        Arc::new(Semaphore::new(4)),
        4,
        fast_service_config(),
    )
}

fn make_service_with_config(
    resolver: Arc<dyn SymbolResolver>,
    symbol_resolution_limiter: Arc<Semaphore>,
    max_in_flight: u32,
    service_config: ServiceConfig,
) -> CymbalResolutionService {
    CymbalResolutionService::new(
        resolver,
        symbol_resolution_limiter,
        LoadMonitor::new(max_in_flight),
        "test-instance",
        service_config,
        Arc::new(AtomicBool::new(false)),
    )
}

async fn spawn_test_channel(service: CymbalResolutionService) -> Channel {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind test server");
    let addr = listener.local_addr().expect("test server local addr");
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

    Channel::from_shared(format!("http://{addr}"))
        .expect("valid test endpoint")
        .connect()
        .await
        .expect("connect to test server")
}

async fn resolve_items(
    service: CymbalResolutionService,
    items: Vec<ResolveItem>,
) -> Vec<ResolveOutcome> {
    resolve_items_with_accepted(service, items)
        .await
        .into_iter()
        .filter(|outcome| {
            !matches!(
                outcome_result(outcome),
                resolve_outcome::Result::Accepted(_)
            )
        })
        .collect()
}

async fn resolve_items_with_accepted(
    service: CymbalResolutionService,
    items: Vec<ResolveItem>,
) -> Vec<ResolveOutcome> {
    let channel = spawn_test_channel(service).await;
    let mut client = CymbalResolutionClient::new(channel);
    let response = client
        .resolve(Request::new(futures::stream::iter(items)))
        .await
        .expect("resolve returns response");
    let mut stream = response.into_inner();
    let mut outcomes = Vec::new();
    while let Some(outcome) = stream.next().await {
        outcomes.push(outcome.expect("outcome must not be status error"));
    }
    outcomes
}

fn raw_exception(exception_type: &str) -> Exception {
    Exception {
        exception_id: None,
        exception_type: exception_type.to_string(),
        exception_message: "boom".to_string(),
        mechanism: None,
        module: None,
        thread_id: None,
        stack: Some(Stacktrace::Raw { frames: vec![] }),
    }
}

fn make_item(id: u64, exc: &Exception) -> ResolveItem {
    ResolveItem {
        id,
        team_id: 7,
        exception_json: serde_json::to_vec(exc).expect("serialize exception"),
        metadata: Vec::new(),
        deadline_ms: 1_000,
    }
}

fn make_item_with_metadata(id: u64, exc: &Exception, metadata: Vec<u8>) -> ResolveItem {
    ResolveItem {
        id,
        metadata,
        ..make_item(id, exc)
    }
}

fn outcome_result(outcome: &ResolveOutcome) -> &resolve_outcome::Result {
    outcome.result.as_ref().expect("outcome result present")
}

fn error_kind(outcome: &ResolveOutcome) -> ErrorKind {
    let resolve_outcome::Result::Error(error) = outcome_result(outcome) else {
        panic!("expected error outcome, got {outcome:?}");
    };
    ErrorKind::try_from(error.kind).expect("known error kind")
}

fn assert_no_retry(outcomes: &[ResolveOutcome]) {
    assert!(
        outcomes
            .iter()
            .all(|outcome| !matches!(outcome_result(outcome), resolve_outcome::Result::Retry(_))),
        "server overload must be an ErrorKind, not a Retry outcome: {outcomes:?}",
    );
}

#[tokio::test]
async fn bidi_resolve_stream_resolves_multiple_items_and_echoes_ids() {
    let service = make_service(FakeResolver::default());
    let exc = raw_exception("RuntimeError");

    let outcomes = resolve_items(service, vec![make_item(41, &exc), make_item(42, &exc)]).await;

    assert_eq!(outcomes.len(), 2);
    assert_eq!(
        outcomes
            .iter()
            .map(|outcome| outcome.id)
            .collect::<Vec<_>>(),
        vec![41, 42]
    );
    for outcome in outcomes {
        let resolve_outcome::Result::Done(done) = outcome_result(&outcome) else {
            panic!("expected Done outcome, got {outcome:?}");
        };
        let resolved: Exception = serde_json::from_slice(&done.resolved_exception_json)
            .expect("valid resolved exception");
        assert_eq!(resolved.exception_type, "RuntimeError");
        assert!(matches!(resolved.stack, Some(Stacktrace::Resolved { .. })));
    }
}

#[tokio::test]
async fn admitted_items_emit_accepted_before_terminal_outcome() {
    let service = make_service(FakeResolver::default());
    let exc = raw_exception("RuntimeError");

    let outcomes = resolve_items_with_accepted(service, vec![make_item(41, &exc)]).await;

    assert_eq!(outcomes.len(), 2);
    assert_eq!(outcomes[0].id, 41);
    assert!(matches!(
        outcome_result(&outcomes[0]),
        resolve_outcome::Result::Accepted(_)
    ));
    assert_eq!(outcomes[1].id, 41);
    assert!(matches!(
        outcome_result(&outcomes[1]),
        resolve_outcome::Result::Done(_)
    ));
}

#[tokio::test]
async fn raw_frames_are_resolved_into_done_payload() {
    let raw_frame = sample_raw_frame();
    let mut resolver_frame = sample_resolved_frame(&raw_frame);
    resolver_frame.frame_id = raw_frame.frame_id(123, 99, &[]);
    let service = make_service(FakeResolver {
        fail_unhandled: false,
        resolved_frames: vec![resolver_frame],
    });
    let mut exc = raw_exception("RuntimeError");
    exc.stack = Some(Stacktrace::Raw {
        frames: vec![raw_frame.clone()],
    });

    let outcomes = resolve_items(service, vec![make_item(1, &exc)]).await;
    assert_eq!(outcomes.len(), 1);
    let resolve_outcome::Result::Done(done) = outcome_result(&outcomes[0]) else {
        panic!("expected Done outcome, got {:?}", outcomes[0]);
    };
    let resolved: Exception =
        serde_json::from_slice(&done.resolved_exception_json).expect("valid resolved exception");

    let Some(Stacktrace::Resolved { frames }) = resolved.stack else {
        panic!("raw stack must be replaced with resolved frames");
    };
    let expected_wire_frame: Frame = serde_json::from_value(
        serde_json::to_value(sample_resolved_frame(&raw_frame)).expect("serialize expected frame"),
    )
    .expect("deserialize expected wire frame");
    assert_eq!(frames, vec![expected_wire_frame]);
}

#[tokio::test]
async fn bidi_resolve_stream_emits_outcomes_as_items_complete_out_of_order() {
    let active = Arc::new(AtomicUsize::new(0));
    let max_active = Arc::new(AtomicUsize::new(0));
    let started = Arc::new(AtomicUsize::new(0));
    let service = make_service_with_config(
        Arc::new(SlowResolver {
            delay: Duration::from_millis(5),
            first_call_delay: Some(Duration::from_millis(80)),
            active,
            max_active: max_active.clone(),
            started: started.clone(),
        }),
        Arc::new(Semaphore::new(8)),
        8,
        fast_service_config(),
    );
    let mut exc = raw_exception("RuntimeError");
    exc.stack = Some(Stacktrace::Raw {
        frames: vec![sample_raw_frame()],
    });
    let items = (1..=4).map(|id| make_item(id, &exc)).collect();

    let outcomes = resolve_items(service, items).await;

    assert_eq!(started.load(Ordering::Acquire), 4);
    assert!(
        max_active.load(Ordering::Acquire) > 1,
        "items should be processed concurrently",
    );
    assert_eq!(outcomes.len(), 4);
    assert_ne!(
        outcomes[0].id, 1,
        "a faster later item should complete before the slower first item",
    );
    assert!(outcomes
        .iter()
        .all(|outcome| matches!(outcome_result(outcome), resolve_outcome::Result::Done(_))));
}

#[tokio::test]
async fn invalid_payload_and_metadata_formats_are_invalid_payload_errors() {
    let service = make_service(FakeResolver::default());
    let exc = raw_exception("RuntimeError");
    let outcomes = resolve_items(
        service,
        vec![
            ResolveItem {
                id: 1,
                team_id: 7,
                exception_json: b"not-json".to_vec(),
                metadata: Vec::new(),
                deadline_ms: 1_000,
            },
            make_item_with_metadata(2, &exc, b"not-json".to_vec()),
            make_item_with_metadata(3, &exc, br#"{"debug_images_json":"not-a-list"}"#.to_vec()),
        ],
    )
    .await;

    assert_eq!(outcomes.len(), 3);
    for outcome in outcomes {
        assert_eq!(error_kind(&outcome), ErrorKind::InvalidPayload);
    }
}

#[tokio::test]
async fn unhandled_resolver_failure_classifies_as_unhandled_error() {
    let service = make_service(FakeResolver {
        fail_unhandled: true,
        ..Default::default()
    });
    let mut exc = raw_exception("RuntimeError");
    exc.stack = Some(Stacktrace::Raw {
        frames: vec![sample_raw_frame()],
    });

    let outcomes = resolve_items(service, vec![make_item(1, &exc)]).await;

    assert_eq!(outcomes.len(), 1);
    assert_eq!(outcomes[0].id, 1);
    assert_eq!(error_kind(&outcomes[0]), ErrorKind::Unhandled);
}

#[tokio::test]
async fn load_monitor_overload_is_an_overloaded_error_outcome_only() {
    let active = Arc::new(AtomicUsize::new(0));
    let max_active = Arc::new(AtomicUsize::new(0));
    let started = Arc::new(AtomicUsize::new(0));
    let service = make_service_with_config(
        Arc::new(SlowResolver {
            delay: Duration::from_millis(80),
            first_call_delay: None,
            active,
            max_active,
            started,
        }),
        Arc::new(Semaphore::new(8)),
        1,
        fast_service_config(),
    );
    let mut exc = raw_exception("RuntimeError");
    exc.stack = Some(Stacktrace::Raw {
        frames: vec![sample_raw_frame()],
    });

    let outcomes = resolve_items(service, vec![make_item(1, &exc), make_item(2, &exc)]).await;

    assert_no_retry(&outcomes);
    let overloaded = outcomes
        .iter()
        .find(|outcome| outcome.id == 2)
        .expect("second item should be rejected by max_in_flight");
    assert_eq!(error_kind(overloaded), ErrorKind::Overloaded);
    let completed = outcomes
        .iter()
        .find(|outcome| outcome.id == 1)
        .expect("first admitted item should complete");
    assert!(matches!(
        outcome_result(completed),
        resolve_outcome::Result::Done(_)
    ));
}

#[tokio::test]
async fn symbol_limiter_overload_is_an_overloaded_error_outcome_only() {
    let limiter = Arc::new(Semaphore::new(1));
    let _permit = limiter.clone().acquire_owned().await.unwrap();
    limiter.close();
    let service = make_service_with_config(
        Arc::new(FakeResolver::default()),
        limiter,
        4,
        fast_service_config(),
    );

    let outcomes = resolve_items(service, vec![make_item(1, &java_exception_for_overload())]).await;

    assert_eq!(outcomes.len(), 1);
    assert_no_retry(&outcomes);
    assert_eq!(error_kind(&outcomes[0]), ErrorKind::Overloaded);
}

fn java_exception_for_overload() -> Exception {
    let frame_json = serde_json::json!({
        "platform": "java",
        "module": "com.example",
        "filename": "A.java",
        "function": "f",
        "in_app": true,
    });
    let frame: RawFrame = serde_json::from_value(frame_json).expect("valid java frame");
    Exception {
        exception_id: None,
        exception_type: "Boom".to_string(),
        exception_message: "msg".to_string(),
        mechanism: None,
        module: Some("com.example".to_string()),
        thread_id: None,
        stack: Some(Stacktrace::Raw {
            frames: vec![frame],
        }),
    }
}

fn sample_raw_frame() -> RawFrame {
    let json = serde_json::json!({
        "platform": "web:javascript",
        "filename": "a.js",
        "function": "f",
        "in_app": true,
        "lineno": 1,
        "colno": 1,
    });
    serde_json::from_value(json).expect("valid raw frame")
}

fn sample_resolved_frame(raw_frame: &RawFrame) -> Frame {
    Frame {
        frame_id: raw_frame.frame_id(7, 0, &[]),
        mangled_name: "f".to_string(),
        line: Some(42),
        column: Some(7),
        source: Some("src/app.ts".to_string()),
        module: Some("app".to_string()),
        in_app: true,
        resolved_name: Some("renderCheckout".to_string()),
        lang: "javascript".to_string(),
        resolved: true,
        resolve_failure: None,
        synthetic: false,
        suspicious: false,
        junk_drawer: None,
        code_variables: None,
        context: None,
        release: None,
    }
}

#[tokio::test]
async fn subscribe_emits_periodic_load_events_with_monotonic_sequence() {
    let service = make_service(FakeResolver::default());
    let response = service
        .subscribe(Request::new(SubscribeRequest {
            subscriber_id: "test-subscriber".to_string(),
            tick_hint_ms: 0,
        }))
        .await
        .expect("subscribe returns response");
    let mut stream = response.into_inner();

    let mut events = Vec::new();
    for _ in 0..3 {
        let event = stream
            .next()
            .await
            .expect("stream open")
            .expect("event without status error");
        events.push(event);
    }
    drop(stream);

    assert_eq!(events.len(), 3);
    assert_eq!(events[0].sequence, 1);
    assert_eq!(events[1].sequence, 2);
    assert_eq!(events[2].sequence, 3);
    assert!(!events[0].draining);
    assert_eq!(events[0].in_flight, 0);
    assert_eq!(events[0].max_in_flight, 4);
    assert_eq!(events[0].service_instance_id, "test-instance");
}

#[tokio::test]
async fn subscribe_reflects_draining_state() {
    let draining = Arc::new(AtomicBool::new(true));
    let service = CymbalResolutionService::new(
        Arc::new(FakeResolver::default()),
        Arc::new(Semaphore::new(4)),
        LoadMonitor::new(4),
        "draining-test",
        fast_service_config(),
        draining,
    );
    let response = service
        .subscribe(Request::new(SubscribeRequest {
            subscriber_id: "draining-watcher".to_string(),
            tick_hint_ms: 0,
        }))
        .await
        .expect("subscribe returns response");
    let mut stream = response.into_inner();

    let event = stream.next().await.expect("stream open").expect("event ok");
    assert!(event.draining);
    assert_eq!(event.service_instance_id, "draining-test");
}

#[tokio::test]
async fn subscribe_clamps_caller_hint_to_server_bounds() {
    let service = make_service(FakeResolver::default());
    let response = service
        .subscribe(Request::new(SubscribeRequest {
            subscriber_id: "fast-caller".to_string(),
            tick_hint_ms: 0,
        }))
        .await
        .expect("subscribe accepts default hints");
    let mut stream = response.into_inner();
    let event = stream.next().await.expect("at least one event").unwrap();
    assert_eq!(event.sequence, 1);
}

#[tokio::test]
async fn subscribe_terminates_when_caller_drops_stream() {
    let service = make_service(FakeResolver::default());
    let response = service
        .subscribe(Request::new(SubscribeRequest::default()))
        .await
        .unwrap();
    let mut stream = response.into_inner();
    let _first = stream.next().await.unwrap();
    drop(stream);

    tokio::time::sleep(Duration::from_millis(30)).await;

    let response = service
        .subscribe(Request::new(SubscribeRequest::default()))
        .await
        .unwrap();
    let mut stream2 = response.into_inner();
    let event = stream2.next().await.unwrap().unwrap();
    assert_eq!(event.sequence, 1, "new subscription restarts sequence at 1");
}
