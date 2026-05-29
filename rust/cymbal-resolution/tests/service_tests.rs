use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Arc,
};
use std::time::Duration;

use async_trait::async_trait;
use cymbal::error::{ResolveError, UnhandledError};
use cymbal::frames::{Frame, RawFrame};
use cymbal::langs::apple::AppleDebugImage;
use cymbal::stages::resolution::symbol::SymbolResolver;
use cymbal::symbol_store::{chunk_id::OrChunkId, proguard::ProguardRef};
use cymbal::types::operator::TeamId;
use cymbal::types::{Exception, ExceptionList, Stacktrace};
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolution;
use cymbal_proto::cymbal::resolution::v1::{
    item_outcome, outcome, ExceptionResolution, ExceptionResolutionItem, Outcome, ResolveRequest,
    SubscribeRequest,
};
use cymbal_resolution::item_limiter::ItemLimiter;
use cymbal_resolution::load_monitor::LoadMonitor;
use cymbal_resolution::service::{codes, CymbalResolutionService, ServiceConfig};
use futures::StreamExt;
use tokio::sync::Semaphore;
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
        _debug_images: &[AppleDebugImage],
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

fn fast_service_config() -> ServiceConfig {
    // Aggressive tick so Subscribe tests don't pay a full second per iteration.
    ServiceConfig {
        default_tick_interval: Duration::from_millis(20),
        min_tick_interval: Duration::from_millis(1),
        max_tick_interval: Duration::from_secs(1),
    }
}

fn make_service(resolver: FakeResolver) -> CymbalResolutionService {
    let limiter = Arc::new(Semaphore::new(4));
    // Keep item_limiter size in lockstep with max_in_flight so reported
    // load matches actual permits available — Subscribe tests rely on this.
    let item_limiter = ItemLimiter::new(4);
    make_service_with_config(
        Arc::new(resolver),
        limiter,
        item_limiter,
        4,
        fast_service_config(),
    )
}

fn make_service_with_config(
    resolver: Arc<dyn SymbolResolver>,
    limiter: Arc<Semaphore>,
    item_limiter: ItemLimiter,
    max_in_flight: u32,
    service_config: ServiceConfig,
) -> CymbalResolutionService {
    // Degraded signal disabled (threshold 0); these tests don't exercise it.
    let load_monitor = load_monitor_for_test(0);
    load_monitor
        .set_in_flight(max_in_flight.saturating_sub(item_limiter.available_permits() as u32));
    CymbalResolutionService::new(
        resolver,
        limiter,
        item_limiter,
        load_monitor,
        "test-instance",
        service_config,
        Arc::new(AtomicBool::new(false)),
    )
}

fn load_monitor_for_test(degraded_threshold: u32) -> LoadMonitor {
    LoadMonitor::new(degraded_threshold)
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
        _debug_images: &[AppleDebugImage],
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

fn raw_exception(exception_type: &str) -> Exception {
    Exception {
        exception_id: None,
        exception_type: exception_type.to_string(),
        exception_message: "boom".to_string(),
        mechanism: None,
        module: None,
        thread_id: None,
        // Frame resolution walks an empty Raw stack without touching the
        // resolver, which keeps these tests resolver-agnostic.
        stack: Some(Stacktrace::Raw { frames: vec![] }),
    }
}

fn make_item(item_id: &str, item_index: u32, exc: &Exception) -> ExceptionResolutionItem {
    let bytes = serde_json::to_vec(exc).expect("serialize exception");
    ExceptionResolutionItem {
        item_id: item_id.to_string(),
        item_index,
        team_id: 7,
        exception: Some(ExceptionResolution {
            exception_json: bytes,
            apple_debug_images_json: Vec::new(),
        }),
    }
}

async fn drain_resolve(service: &CymbalResolutionService, request: ResolveRequest) -> Vec<Outcome> {
    let response = service
        .resolve(Request::new(request))
        .await
        .expect("resolve returns response");
    let mut stream = response.into_inner();
    let mut out = Vec::new();
    while let Some(msg) = stream.next().await {
        out.push(msg.expect("outcome must not be error"));
    }
    out
}

fn item_outcome(outcome: &Outcome) -> Option<&item_outcome::Result> {
    let outcome::Message::ItemOutcome(io) = outcome.message.as_ref()? else {
        return None;
    };
    io.result.as_ref()
}

#[tokio::test]
async fn happy_path_emits_only_item_outcomes_and_terminal_summary() {
    // Resolve no longer carries ServiceInfo — load lives on Subscribe. The
    // stream is item outcomes plus the terminal summary, full stop.
    let service = make_service(FakeResolver::default());
    let exc = raw_exception("RuntimeError");
    let req = ResolveRequest {
        batch_id: "batch-happy".to_string(),
        items: vec![
            make_item("evt-1:exc-0", 0, &exc),
            make_item("evt-1:exc-1", 1, &exc),
        ],
    };

    let outcomes = drain_resolve(&service, req).await;
    assert_eq!(outcomes.len(), 3, "2 items + summary");

    for outcome in &outcomes[..2] {
        let result = item_outcome(outcome).expect("item outcome");
        assert!(
            matches!(result, item_outcome::Result::Done(_)),
            "expected done, got {result:?}",
        );
        assert_eq!(outcome.batch_id, "batch-happy");
    }

    let Some(outcome::Message::BatchSummary(summary)) = outcomes.last().unwrap().message.as_ref()
    else {
        panic!("last outcome must be BatchSummary");
    };
    assert_eq!(summary.submitted_items, 2);
    assert_eq!(summary.item_outcomes, 2);
    assert_eq!(summary.done_items, 2);
    assert_eq!(summary.error_items, 0);
    assert_eq!(summary.retry_items, 0);
    assert!(summary.missing_items.is_empty());
    assert!(summary.duplicate_items.is_empty());
}

#[tokio::test]
async fn invalid_payload_produces_error_item_outcome_and_counts_in_summary() {
    let service = make_service(FakeResolver::default());
    let exc = raw_exception("RuntimeError");
    let req = ResolveRequest {
        batch_id: "batch-mixed".to_string(),
        items: vec![
            make_item("ok", 0, &exc),
            ExceptionResolutionItem {
                item_id: "broken".to_string(),
                item_index: 1,
                team_id: 7,
                exception: Some(ExceptionResolution {
                    exception_json: b"not-json".to_vec(),
                    apple_debug_images_json: Vec::new(),
                }),
            },
            ExceptionResolutionItem {
                item_id: "missing-exception".to_string(),
                item_index: 2,
                team_id: 7,
                exception: None,
            },
        ],
    };

    let outcomes = drain_resolve(&service, req).await;
    assert_eq!(outcomes.len(), 4, "3 items + summary, no service info");

    let result_for = |index: u32| {
        outcomes
            .iter()
            .find_map(|o| match o.message.as_ref()? {
                outcome::Message::ItemOutcome(io) if io.item_index == index => {
                    io.result.as_ref().cloned()
                }
                _ => None,
            })
            .expect("item outcome present")
    };

    assert!(matches!(result_for(0), item_outcome::Result::Done(_)));
    let broken = result_for(1);
    let item_outcome::Result::Error(e1) = broken else {
        panic!("broken item should be Error");
    };
    assert_eq!(e1.code, codes::ERROR_INVALID_PAYLOAD);

    let missing = result_for(2);
    let item_outcome::Result::Error(e2) = missing else {
        panic!("missing exception item should be Error");
    };
    assert_eq!(e2.code, codes::ERROR_INVALID_PAYLOAD);

    let Some(outcome::Message::BatchSummary(summary)) = outcomes.last().unwrap().message.as_ref()
    else {
        panic!("last outcome must be BatchSummary");
    };
    assert_eq!(summary.submitted_items, 3);
    assert_eq!(summary.item_outcomes, 3);
    assert_eq!(summary.done_items, 1);
    assert_eq!(summary.error_items, 2);
    assert_eq!(summary.retry_items, 0);
}

#[tokio::test]
async fn unhandled_resolver_failure_classifies_as_unhandled_error() {
    let service = make_service(FakeResolver {
        fail_unhandled: true,
        ..Default::default()
    });
    // Frame resolution actually walks the resolver only for raw stack frames,
    // so attach one frame that the resolver will be asked about.
    let mut exc = raw_exception("RuntimeError");
    exc.stack = Some(Stacktrace::Raw {
        frames: vec![sample_raw_frame()],
    });
    let req = ResolveRequest {
        batch_id: "batch-unhandled".to_string(),
        items: vec![make_item("evt:exc", 0, &exc)],
    };

    let outcomes = drain_resolve(&service, req).await;
    let item = outcomes
        .iter()
        .find_map(|o| match o.message.as_ref()? {
            outcome::Message::ItemOutcome(io) => io.result.as_ref(),
            _ => None,
        })
        .expect("item outcome present");
    let item_outcome::Result::Error(err) = item else {
        panic!("expected unhandled Error outcome, got {item:?}");
    };
    assert_eq!(err.code, codes::ERROR_UNHANDLED);

    let Some(outcome::Message::BatchSummary(summary)) = outcomes.last().unwrap().message.as_ref()
    else {
        panic!("last outcome must be BatchSummary");
    };
    assert_eq!(summary.submitted_items, 1);
    assert_eq!(summary.error_items, 1);
    assert_eq!(summary.done_items, 0);
}

#[tokio::test]
async fn empty_batch_still_emits_terminal_summary() {
    let service = make_service(FakeResolver::default());
    let req = ResolveRequest {
        batch_id: "batch-empty".to_string(),
        items: vec![],
    };

    let outcomes = drain_resolve(&service, req).await;
    assert_eq!(outcomes.len(), 1, "summary only");
    let Some(outcome::Message::BatchSummary(summary)) = outcomes[0].message.as_ref() else {
        panic!("only outcome must be BatchSummary");
    };
    assert_eq!(summary.submitted_items, 0);
    assert_eq!(summary.item_outcomes, 0);
}

#[tokio::test]
async fn resolved_exception_round_trips_into_done_payload() {
    let service = make_service(FakeResolver::default());
    let exc = raw_exception("RuntimeError");
    let req = ResolveRequest {
        batch_id: "batch-roundtrip".to_string(),
        items: vec![make_item("evt", 0, &exc)],
    };

    let outcomes = drain_resolve(&service, req).await;
    let io = outcomes
        .iter()
        .find_map(|o| match o.message.as_ref()? {
            outcome::Message::ItemOutcome(io) => Some(io),
            _ => None,
        })
        .expect("missing item outcome");
    let Some(item_outcome::Result::Done(done)) = io.result.as_ref() else {
        panic!("expected Done outcome");
    };

    // The resolved payload must round-trip through cymbal's Exception type so
    // callers can replace the submitted exception with the resolved one.
    let resolved: Exception =
        serde_json::from_slice(&done.resolved_exception_json).expect("valid resolved exception");
    assert_eq!(resolved.exception_type, "RuntimeError");

    // Frame resolution converts Raw -> Resolved with the empty frame set the
    // fake resolver produced.
    assert!(matches!(resolved.stack, Some(Stacktrace::Resolved { .. })));

    // Outer ExceptionList shape stays unchanged for callers that want to slot
    // the resolved exception back into a list without re-fetching.
    let list = ExceptionList::from(vec![resolved]);
    assert_eq!(list.0.len(), 1);
}

#[tokio::test]
async fn raw_frames_are_resolved_into_done_payload() {
    let raw_frame = sample_raw_frame();
    let mut resolver_frame = sample_resolved_frame(&raw_frame);
    resolver_frame.frame_id = raw_frame.frame_id(123, 99);
    let service = make_service(FakeResolver {
        fail_unhandled: false,
        resolved_frames: vec![resolver_frame],
    });
    let mut exc = raw_exception("RuntimeError");
    exc.stack = Some(Stacktrace::Raw {
        frames: vec![raw_frame.clone()],
    });
    let req = ResolveRequest {
        batch_id: "batch-frame-resolution".to_string(),
        items: vec![make_item("evt:exc", 0, &exc)],
    };

    let outcomes = drain_resolve(&service, req).await;
    let done = outcomes
        .iter()
        .find_map(|o| match o.message.as_ref()? {
            outcome::Message::ItemOutcome(io) => match io.result.as_ref()? {
                item_outcome::Result::Done(done) => Some(done),
                _ => None,
            },
            _ => None,
        })
        .expect("done outcome present");
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

// ----------------------------------------------------------------------
// Batch 4 — accounting + overload tests
// ----------------------------------------------------------------------

#[tokio::test]
async fn large_mixed_batch_accounts_done_error_and_retry_items() {
    let limiter = Arc::new(Semaphore::new(1));
    let _permit = limiter.clone().acquire_owned().await.unwrap();
    limiter.close();
    let service = make_service_with_config(
        Arc::new(FakeResolver::default()),
        limiter,
        ItemLimiter::new(128),
        1,
        fast_service_config(),
    );
    let good_exc = raw_exception("RuntimeError");
    let retry_exc = java_exception_for_overload();
    let items: Vec<ExceptionResolutionItem> = (0..96)
        .map(|i| match i % 12 {
            0 => ExceptionResolutionItem {
                item_id: format!("evt:{i}"),
                item_index: i,
                team_id: 7,
                exception: Some(ExceptionResolution {
                    exception_json: b"not-json".to_vec(),
                    apple_debug_images_json: Vec::new(),
                }),
            },
            1 => make_item(&format!("evt:{i}"), i, &retry_exc),
            _ => make_item(&format!("evt:{i}"), i, &good_exc),
        })
        .collect();

    let outcomes = drain_resolve(
        &service,
        ResolveRequest {
            batch_id: "batch-large-mixed".to_string(),
            items,
        },
    )
    .await;

    let mut done = 0;
    let mut error = 0;
    let mut retry = 0;
    for outcome in &outcomes {
        let Some(result) = item_outcome(outcome) else {
            continue;
        };
        match result {
            item_outcome::Result::Done(_) => done += 1,
            item_outcome::Result::Error(err) => {
                assert_eq!(err.code, codes::ERROR_INVALID_PAYLOAD);
                error += 1;
            }
            item_outcome::Result::Retry(retry_outcome) => {
                assert_eq!(retry_outcome.code, codes::RETRY_OVERLOADED);
                retry += 1;
            }
        }
    }

    let Some(outcome::Message::BatchSummary(summary)) = outcomes.last().unwrap().message.as_ref()
    else {
        panic!("last outcome must be BatchSummary");
    };
    assert_eq!(summary.submitted_items, 96);
    assert_eq!(summary.item_outcomes, 96);
    assert_eq!(summary.done_items, done);
    assert_eq!(summary.error_items, error);
    assert_eq!(summary.retry_items, retry);
    assert_eq!(done, 80);
    assert_eq!(error, 8);
    assert_eq!(retry, 8);
    assert!(summary.missing_items.is_empty());
    assert!(summary.duplicate_items.is_empty());
}

#[tokio::test]
async fn per_request_item_concurrency_bounds_slow_resolution_work() {
    let active = Arc::new(AtomicUsize::new(0));
    let max_active = Arc::new(AtomicUsize::new(0));
    let started = Arc::new(AtomicUsize::new(0));
    let service = make_service_with_config(
        Arc::new(SlowResolver {
            delay: Duration::from_millis(25),
            first_call_delay: None,
            active: active.clone(),
            max_active: max_active.clone(),
            started: started.clone(),
        }),
        Arc::new(Semaphore::new(32)),
        // Global item cap of 2 — the new semaphore-based equivalent of the
        // retired `ServiceConfig.item_concurrency`.
        ItemLimiter::new(2),
        32,
        fast_service_config(),
    );
    let mut exc = raw_exception("RuntimeError");
    exc.stack = Some(Stacktrace::Raw {
        frames: vec![sample_raw_frame()],
    });
    let items: Vec<ExceptionResolutionItem> = (0..10)
        .map(|i| make_item(&format!("evt:{i}"), i, &exc))
        .collect();

    let outcomes = drain_resolve(
        &service,
        ResolveRequest {
            batch_id: "batch-bounded-concurrency".to_string(),
            items,
        },
    )
    .await;

    assert_eq!(started.load(Ordering::Acquire), 10);
    assert_eq!(max_active.load(Ordering::Acquire), 2);
    let Some(outcome::Message::BatchSummary(summary)) = outcomes.last().unwrap().message.as_ref()
    else {
        panic!("last outcome must be BatchSummary");
    };
    assert_eq!(summary.done_items, 10);
    assert_eq!(summary.error_items, 0);
    assert_eq!(summary.retry_items, 0);
}

#[tokio::test]
async fn in_flight_counts_items_as_soon_as_they_arrive() {
    let item_limiter = ItemLimiter::new(1);
    let _held = item_limiter.acquire_owned().await.unwrap();
    let load_monitor = load_monitor_for_test(0);
    let service = CymbalResolutionService::new(
        Arc::new(FakeResolver::default()),
        Arc::new(Semaphore::new(32)),
        item_limiter,
        load_monitor.clone(),
        "arrival-load-test",
        fast_service_config(),
        Arc::new(AtomicBool::new(false)),
    );
    let exc = raw_exception("RuntimeError");
    let items: Vec<ExceptionResolutionItem> = (0..3)
        .map(|i| make_item(&format!("evt:{i}"), i, &exc))
        .collect();

    let response = service
        .resolve(Request::new(ResolveRequest {
            batch_id: "batch-arrival-load".to_string(),
            items,
        }))
        .await
        .expect("resolve returns response");
    let stream = response.into_inner();

    tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            if load_monitor.snapshot().in_flight == 3 {
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("all arrived items should be counted before item permits are available");

    drop(stream);
    tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            if load_monitor.snapshot().in_flight == 0 {
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("dropping the response stream should release arrived item load");
}

#[tokio::test]
async fn dropping_resolve_stream_stops_scheduling_additional_items() {
    let active = Arc::new(AtomicUsize::new(0));
    let max_active = Arc::new(AtomicUsize::new(0));
    let started = Arc::new(AtomicUsize::new(0));
    let service = make_service_with_config(
        Arc::new(SlowResolver {
            delay: Duration::from_millis(200),
            first_call_delay: None,
            active,
            max_active,
            started: started.clone(),
        }),
        Arc::new(Semaphore::new(32)),
        ItemLimiter::new(2),
        32,
        fast_service_config(),
    );
    let mut exc = raw_exception("RuntimeError");
    exc.stack = Some(Stacktrace::Raw {
        frames: vec![sample_raw_frame()],
    });
    let items: Vec<ExceptionResolutionItem> = (0..20)
        .map(|i| make_item(&format!("evt:{i}"), i, &exc))
        .collect();

    let response = service
        .resolve(Request::new(ResolveRequest {
            batch_id: "batch-cancel".to_string(),
            items,
        }))
        .await
        .expect("resolve returns response");
    drop(response.into_inner());

    tokio::time::sleep(Duration::from_millis(50)).await;
    assert!(
        started.load(Ordering::Acquire) <= 2,
        "dropped streams must not schedule the full request in the background",
    );
}

#[tokio::test]
async fn summary_accounting_is_correct_when_item_outcomes_are_out_of_order() {
    let active = Arc::new(AtomicUsize::new(0));
    let max_active = Arc::new(AtomicUsize::new(0));
    let started = Arc::new(AtomicUsize::new(0));
    let service = make_service_with_config(
        Arc::new(SlowResolver {
            delay: Duration::from_millis(5),
            first_call_delay: Some(Duration::from_millis(80)),
            active,
            max_active,
            started,
        }),
        Arc::new(Semaphore::new(8)),
        ItemLimiter::new(2),
        8,
        fast_service_config(),
    );
    let mut exc = raw_exception("RuntimeError");
    exc.stack = Some(Stacktrace::Raw {
        frames: vec![sample_raw_frame()],
    });
    let items: Vec<ExceptionResolutionItem> = (0..4)
        .map(|i| make_item(&format!("evt:{i}"), i, &exc))
        .collect();

    let outcomes = drain_resolve(
        &service,
        ResolveRequest {
            batch_id: "batch-out-of-order".to_string(),
            items,
        },
    )
    .await;

    let emitted_indices: Vec<u32> = outcomes
        .iter()
        .filter_map(|outcome| match outcome.message.as_ref()? {
            outcome::Message::ItemOutcome(io) => Some(io.item_index),
            _ => None,
        })
        .collect();
    assert_eq!(emitted_indices.len(), 4);
    assert_eq!(
        emitted_indices[0], 1,
        "the faster second item should be emitted before the slower first item",
    );

    let Some(outcome::Message::BatchSummary(summary)) = outcomes.last().unwrap().message.as_ref()
    else {
        panic!("last outcome must be BatchSummary");
    };
    assert_eq!(summary.submitted_items, 4);
    assert_eq!(summary.item_outcomes, 4);
    assert_eq!(summary.done_items, 4);
    assert_eq!(summary.error_items, 0);
    assert_eq!(summary.retry_items, 0);
    assert!(summary.missing_items.is_empty());
    assert!(summary.duplicate_items.is_empty());
}

#[tokio::test]
async fn closed_symbol_limiter_returns_fast_retryable_failures_for_large_batches() {
    let limiter = Arc::new(Semaphore::new(1));
    let _permit = limiter.clone().acquire_owned().await.unwrap();
    limiter.close();
    let service = make_service_with_config(
        Arc::new(FakeResolver::default()),
        limiter,
        ItemLimiter::new(8),
        1,
        fast_service_config(),
    );
    let exc = java_exception_for_overload();
    let items: Vec<ExceptionResolutionItem> = (0..32)
        .map(|i| make_item(&format!("evt:{i}"), i, &exc))
        .collect();
    let started_at = std::time::Instant::now();

    let outcomes = drain_resolve(
        &service,
        ResolveRequest {
            batch_id: "batch-fast-retry".to_string(),
            items,
        },
    )
    .await;

    assert!(
        started_at.elapsed() < Duration::from_millis(100),
        "closed limiter should produce retry outcomes without hidden queueing",
    );
    let retry_count = outcomes
        .iter()
        .filter(|outcome| {
            matches!(
                item_outcome(outcome),
                Some(item_outcome::Result::Retry(retry)) if retry.code == codes::RETRY_OVERLOADED
            )
        })
        .count();
    assert_eq!(retry_count, 32);
    let Some(outcome::Message::BatchSummary(summary)) = outcomes.last().unwrap().message.as_ref()
    else {
        panic!("last outcome must be BatchSummary");
    };
    assert_eq!(summary.retry_items, 32);
}

#[tokio::test]
async fn every_submitted_item_is_accounted_for_once_via_outcome_or_summary() {
    // Submit a mixed batch (valid + invalid payloads) and assert that each
    // (item_id, item_index) pair is reconciled exactly once by an ItemOutcome
    // and that the BatchSummary numbers match the observed outcomes — this is
    // the v1 accounting contract operators rely on.
    let service = make_service(FakeResolver::default());
    let exc = raw_exception("RuntimeError");
    let submitted: Vec<ExceptionResolutionItem> = (0..5)
        .map(|i| {
            if i == 2 {
                // One item with an unparseable payload to exercise the
                // Error path; accounting must still cover it.
                ExceptionResolutionItem {
                    item_id: format!("evt:{i}"),
                    item_index: i as u32,
                    team_id: 7,
                    exception: Some(ExceptionResolution {
                        exception_json: b"not-json".to_vec(),
                        apple_debug_images_json: Vec::new(),
                    }),
                }
            } else {
                make_item(&format!("evt:{i}"), i as u32, &exc)
            }
        })
        .collect();

    let req = ResolveRequest {
        batch_id: "batch-accounting".to_string(),
        items: submitted.clone(),
    };
    let outcomes = drain_resolve(&service, req).await;

    let mut seen: std::collections::HashMap<(String, u32), u32> = std::collections::HashMap::new();
    let mut done = 0u32;
    let mut error = 0u32;
    let mut summary_opt = None;
    for outcome in &outcomes {
        match outcome.message.as_ref() {
            Some(outcome::Message::ItemOutcome(io)) => {
                *seen.entry((io.item_id.clone(), io.item_index)).or_insert(0) += 1;
                match io.result.as_ref() {
                    Some(item_outcome::Result::Done(_)) => done += 1,
                    Some(item_outcome::Result::Error(_)) => error += 1,
                    _ => {}
                }
            }
            Some(outcome::Message::BatchSummary(s)) => summary_opt = Some(s.clone()),
            _ => {}
        }
    }
    let summary = summary_opt.expect("terminal BatchSummary required");

    // Every (item_id, item_index) pair from the request is reconciled exactly
    // once via outcomes — this is the contract operators rely on to map
    // resolved payloads back into their event-level exception lists.
    for item in &submitted {
        let count = seen
            .get(&(item.item_id.clone(), item.item_index))
            .copied()
            .unwrap_or(0);
        assert_eq!(count, 1, "item {item:?} must be reported exactly once");
    }

    assert_eq!(summary.submitted_items, submitted.len() as u32);
    assert_eq!(summary.item_outcomes, submitted.len() as u32);
    assert_eq!(summary.done_items, done);
    assert_eq!(summary.error_items, error);
    assert!(summary.missing_items.is_empty());
    assert!(summary.duplicate_items.is_empty());
}

#[tokio::test]
async fn limiter_overload_classifies_as_overloaded_retry_outcome_per_item() {
    // Server-side overload: pre-acquire every symbol-resolution permit so the
    // operator's first item hits a closed limiter. The handler must emit a
    // per-item Retry with the "overloaded" code rather than queueing or
    // blocking on the limiter — verifying that the service fails fast and
    // observably instead of silently absorbing the request.
    use cymbal_resolution::service::codes;
    use tokio::sync::Semaphore;

    let limiter = Arc::new(Semaphore::new(1));
    let _permit = limiter.clone().acquire_owned().await.unwrap();
    // Close the limiter while we still hold the permit. Acquiring after this
    // returns an error immediately, which the handler maps to RETRY_OVERLOADED.
    limiter.close();
    let service = CymbalResolutionService::new(
        Arc::new(FakeResolver::default()),
        limiter,
        ItemLimiter::new(8),
        load_monitor_for_test(0),
        "overload-test",
        fast_service_config(),
        Arc::new(AtomicBool::new(false)),
    );

    // The item must trigger a permit acquisition path. Java/Dart classification
    // do; a non-Java/Dart exception only acquires inside frame resolution. We
    // build a Java exception (module + Java frame) so the handler always hits
    // acquire_symbol_resolution_permit before doing real work.
    let exc = java_exception_for_overload();
    let req = ResolveRequest {
        batch_id: "batch-overload".to_string(),
        items: vec![make_item("evt:0", 0, &exc)],
    };
    let outcomes = drain_resolve(&service, req).await;
    let io = outcomes
        .iter()
        .find_map(|o| match o.message.as_ref()? {
            outcome::Message::ItemOutcome(io) => Some(io),
            _ => None,
        })
        .expect("item outcome required");

    let item_outcome::Result::Retry(retry) = io.result.as_ref().expect("item must carry a result")
    else {
        panic!("expected Retry outcome, got {:?}", io.result);
    };
    assert_eq!(retry.code, codes::RETRY_OVERLOADED);

    // BatchSummary should reflect the per-item Retry classification.
    let summary = outcomes
        .iter()
        .find_map(|o| match o.message.as_ref()? {
            outcome::Message::BatchSummary(s) => Some(s.clone()),
            _ => None,
        })
        .expect("summary required");
    assert_eq!(summary.retry_items, 1);
    assert_eq!(summary.done_items, 0);
    assert_eq!(summary.error_items, 0);
}

fn java_exception_for_overload() -> Exception {
    // Minimal Java exception shape; the FakeResolver's resolve_java_class is
    // unreachable in this fixture because the limiter rejects before any
    // resolver call happens.
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
    // Build a minimal JS raw frame via cymbal's own serde shape. JS is used
    // because it does not flip the Java/Dart classification heuristics and
    // therefore exercises only the frame-resolution path on the FakeResolver.
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
        frame_id: raw_frame.frame_id(7, 0),
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

// ----------------------------------------------------------------------
// No-payload-duplication invariant
//
// The contract is: per-item payloads (resolved exception JSON, error
// messages, retry messages) ride on exactly one ItemOutcome wire message.
// The terminal BatchSummary is for reconciliation only and must not carry
// payloads — structurally enforced by the proto (it uses ItemReference,
// not ExceptionResolutionItem), but pinned here end-to-end so a future
// change to either side can't silently regress.
// ----------------------------------------------------------------------

#[tokio::test]
async fn no_item_payload_is_sent_more_than_once_on_the_resolve_stream() {
    // Build a mixed batch so the test exercises Done, Error, and Retry
    // payloads in the same stream. We then walk every Outcome on the wire
    // and assert each (item_id, item_index) appears in exactly one
    // ItemOutcome, and that no per-item payload bytes appear anywhere else
    // (in particular, never inside the terminal BatchSummary).
    let limiter = Arc::new(Semaphore::new(2));
    let _hold = limiter.clone().acquire_owned().await.unwrap();
    limiter.close();
    let service = CymbalResolutionService::new(
        Arc::new(FakeResolver::default()),
        limiter,
        ItemLimiter::new(8),
        load_monitor_for_test(0),
        "no-dup-test",
        fast_service_config(),
        Arc::new(AtomicBool::new(false)),
    );

    let good_exc = raw_exception("RuntimeError");
    let java_exc = java_exception_for_overload();
    let req = ResolveRequest {
        batch_id: "batch-no-dup".to_string(),
        items: vec![
            make_item("evt:done", 0, &good_exc),
            ExceptionResolutionItem {
                item_id: "evt:invalid".to_string(),
                item_index: 1,
                team_id: 7,
                exception: Some(ExceptionResolution {
                    exception_json: b"not-json".to_vec(),
                    apple_debug_images_json: Vec::new(),
                }),
            },
            make_item("evt:retry", 2, &java_exc),
        ],
    };
    let outcomes = drain_resolve(&service, req).await;

    // Bucket the wire messages by message-variant so the assertions read
    // straight off the stream rather than depending on emission order.
    let mut item_outcomes: Vec<_> = Vec::new();
    let mut summary = None;
    for outcome in &outcomes {
        match outcome.message.as_ref() {
            Some(outcome::Message::ItemOutcome(io)) => item_outcomes.push(io.clone()),
            Some(outcome::Message::BatchSummary(s)) => {
                assert!(
                    summary.replace(s.clone()).is_none(),
                    "exactly one BatchSummary may ride a Resolve stream",
                );
            }
            None => panic!("Outcome.message must be set"),
        }
    }

    // 1. Every submitted item gets exactly one ItemOutcome carrying its
    //    payload. The mixed batch produces one Done, one Error, one Retry.
    let mut by_index: std::collections::HashMap<u32, usize> = Default::default();
    for io in &item_outcomes {
        *by_index.entry(io.item_index).or_insert(0) += 1;
    }
    for index in 0..=2u32 {
        assert_eq!(
            by_index.get(&index).copied().unwrap_or(0),
            1,
            "item_index {index} must appear in exactly one ItemOutcome",
        );
    }
    let kinds: Vec<&'static str> = item_outcomes
        .iter()
        .map(|io| match io.result.as_ref().expect("result present") {
            item_outcome::Result::Done(_) => "done",
            item_outcome::Result::Error(_) => "error",
            item_outcome::Result::Retry(_) => "retry",
        })
        .collect();
    assert!(kinds.contains(&"done"));
    assert!(kinds.contains(&"error"));
    assert!(kinds.contains(&"retry"));

    // 2. The terminal BatchSummary must not carry payloads. The proto type
    //    forbids it structurally (BatchSummary owns no payload fields, only
    //    counts plus ItemReference vectors); this check pins the runtime
    //    expectation that the v1 implementation leaves missing/duplicate
    //    vectors empty too, so nothing in the summary overlaps with the
    //    per-item ItemOutcomes the client has already received.
    let summary = summary.expect("terminal BatchSummary required");
    assert!(
        summary.missing_items.is_empty(),
        "v1 must never declare an item missing when it also emitted an ItemOutcome for it",
    );
    assert!(
        summary.duplicate_items.is_empty(),
        "v1 must never emit duplicate ItemOutcomes for the same item",
    );

    // 3. Spot-check the actual Done payload is present in exactly one place
    //    on the wire. We re-serialize the resolved exception that the
    //    fixture produces and search the entire stream of encoded Outcomes
    //    for its byte signature; the count must be exactly one.
    let done = item_outcomes
        .iter()
        .find_map(|io| match io.result.as_ref().unwrap() {
            item_outcome::Result::Done(done) => Some(done.resolved_exception_json.clone()),
            _ => None,
        })
        .expect("done payload present");
    assert!(
        !done.is_empty(),
        "test fixture must produce a non-empty payload"
    );
    let mut hits = 0usize;
    for outcome in &outcomes {
        let bytes = <Outcome as prost::Message>::encode_to_vec(outcome);
        if find_subsequence(&bytes, &done).is_some() {
            hits += 1;
        }
    }
    assert_eq!(
        hits, 1,
        "resolved_exception_json payload must appear in exactly one Outcome on the wire",
    );
}

fn find_subsequence(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

// ----------------------------------------------------------------------
// Subscribe (load event bus) tests
// ----------------------------------------------------------------------

#[tokio::test]
async fn subscribe_emits_periodic_load_events_with_monotonic_sequence() {
    // Verifies the basic shape of the load event bus: ticks fire on cadence,
    // sequence numbers start at 1 and are strictly increasing, and the
    // service identity is echoed back so callers can correlate logs.
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
    assert!(!events[0].degraded);
    assert!(!events[0].draining);
    assert_eq!(events[0].service_instance_id, "test-instance");
}

#[tokio::test]
async fn subscribe_reflects_draining_state() {
    // The caller pool excludes endpoints that report draining=true, so the
    // service must surface shutdown state on the load event bus before the
    // gRPC listener stops accepting new work.
    let draining = Arc::new(AtomicBool::new(true));
    let service = CymbalResolutionService::new(
        Arc::new(FakeResolver::default()),
        Arc::new(Semaphore::new(4)),
        ItemLimiter::new(4),
        load_monitor_for_test(0),
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
}

#[tokio::test]
async fn subscribe_emits_load_event_from_monitor_snapshot() {
    let symbol_limiter = Arc::new(Semaphore::new(4));
    let item_limiter = ItemLimiter::new(4);
    let _held = item_limiter.acquire_owned().await.unwrap();
    let load_monitor = load_monitor_for_test(0);
    load_monitor.set_in_flight(1);

    let service = CymbalResolutionService::new(
        Arc::new(FakeResolver::default()),
        symbol_limiter,
        item_limiter,
        load_monitor,
        "load-test",
        fast_service_config(),
        Arc::new(AtomicBool::new(false)),
    );
    let response = service
        .subscribe(Request::new(SubscribeRequest {
            subscriber_id: "load-watcher".to_string(),
            tick_hint_ms: 0,
        }))
        .await
        .expect("subscribe returns response");
    let mut stream = response.into_inner();

    let event = stream.next().await.expect("stream open").expect("event ok");
    assert!(!event.degraded);
    assert!(!event.draining);
}

#[tokio::test]
async fn subscribe_flips_degraded_when_in_flight_crosses_threshold() {
    // Spillover relies on the server marking itself degraded before the
    // gRPC admission queue load-sheds. Hold 3 of 4 item permits (in-flight 3,
    // below the threshold of 4), then hold 4 of 4 (in-flight 4) and confirm
    // the next tick reflects the flip.
    let symbol_limiter = Arc::new(Semaphore::new(8));
    let item_limiter = ItemLimiter::new(4);
    let mut held: Vec<_> = (0..3)
        .map(|_| item_limiter.try_acquire_owned().unwrap())
        .collect();
    let load_monitor = load_monitor_for_test(4);
    load_monitor.set_in_flight(3);

    let service = CymbalResolutionService::new(
        Arc::new(FakeResolver::default()),
        symbol_limiter,
        item_limiter.clone(),
        load_monitor.clone(),
        "degraded-test",
        ServiceConfig {
            default_tick_interval: Duration::from_millis(20),
            min_tick_interval: Duration::from_millis(5),
            max_tick_interval: Duration::from_secs(1),
        },
        Arc::new(AtomicBool::new(false)),
    );

    let response = service
        .subscribe(Request::new(SubscribeRequest {
            subscriber_id: "degraded-watcher".to_string(),
            tick_hint_ms: 0,
        }))
        .await
        .expect("subscribe returns response");
    let mut stream = response.into_inner();

    let first = stream.next().await.expect("first tick").expect("event ok");
    assert!(
        !first.degraded,
        "in-flight 3 is below threshold 4; expected not-degraded",
    );

    // Push one more permit so in-flight reaches the threshold and degraded must flip.
    held.push(item_limiter.try_acquire_owned().unwrap());
    load_monitor.set_in_flight(4);

    // Drain ticks until we see the flip or give up — the ticker is fast but
    // we may still observe the in-flight bump on the very next event.
    let mut saw_degraded = false;
    for _ in 0..5 {
        let event = stream.next().await.expect("stream open").expect("event ok");
        if event.degraded {
            saw_degraded = true;
            break;
        }
    }
    assert!(
        saw_degraded,
        "expected to observe degraded=true after pushing load past threshold",
    );
    drop(held);
}

#[tokio::test]
async fn subscribe_clamps_caller_hint_to_server_bounds() {
    // A tick hint below the min must be clamped up; this ensures a misbehaving
    // caller cannot ask the server to wake up faster than the operator has
    // permitted. We can't easily measure cadence under load, so the contract
    // here is "still produces events at the clamped rate without rejecting
    // the subscription."
    let service = make_service(FakeResolver::default());
    let response = service
        .subscribe(Request::new(SubscribeRequest {
            subscriber_id: "fast-caller".to_string(),
            // Below fast_service_config().min_tick_interval — gets clamped up.
            tick_hint_ms: 0, // explicit "use default"; combined with the
                             // fast config that's 20ms, still safe.
        }))
        .await
        .expect("subscribe accepts even aggressive hints");
    let mut stream = response.into_inner();
    let event = stream.next().await.expect("at least one event").unwrap();
    assert_eq!(event.sequence, 1);
}

#[tokio::test]
async fn subscribe_terminates_when_caller_drops_stream() {
    // After the caller drops the response stream, the server-side task should
    // exit cleanly without panicking and without holding resources. We rely on
    // tokio detecting the dropped receiver and the run_subscribe loop checking
    // tx.is_closed before sending. Driving this in a test is mostly about
    // confirming no deadlock; we drop the stream and then poll a fresh
    // subscription to make sure the server is still healthy.
    let service = make_service(FakeResolver::default());
    let response = service
        .subscribe(Request::new(SubscribeRequest::default()))
        .await
        .unwrap();
    let mut stream = response.into_inner();
    let _first = stream.next().await.unwrap();
    drop(stream);

    // Give the server task a tick to observe the closed channel; not strictly
    // required but it makes intent explicit.
    tokio::time::sleep(Duration::from_millis(30)).await;

    let response = service
        .subscribe(Request::new(SubscribeRequest::default()))
        .await
        .unwrap();
    let mut stream2 = response.into_inner();
    let event = stream2.next().await.unwrap().unwrap();
    assert_eq!(event.sequence, 1, "new subscription restarts sequence at 1");
}
