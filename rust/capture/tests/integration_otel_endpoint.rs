#[path = "common/integration_utils.rs"]
mod integration_utils;

use async_trait::async_trait;
use axum_test_helper::TestClient;
use capture::ai_s3::MockBlobStorage;
use capture::config::CaptureMode;
use capture::event_restrictions::{
    EventRestrictionService, Pipeline, Restriction, RestrictionFilters, RestrictionManager,
    RestrictionScope, RestrictionType,
};
use capture::outputs::PrepSpec;
use capture::outputs::{Output, OutputTable};
use capture::quota_limiters::{is_llm_event, CaptureQuotaLimiter, EventInfo};
use capture::router::router;
use capture::sinks::sink::{PreparedPayload, Sink, SinkResult};
use capture::time::TimeSource;
use chrono::{DateTime, Utc};
use common_redis::MockRedisClient;
use integration_utils::{test_lifecycle_handlers, DEFAULT_TEST_TIME};
use limiters::overflow::OverflowLimiter;
use limiters::redis::{QuotaResource, QUOTA_LIMITER_CACHE_KEY};
use limiters::token_dropper::TokenDropper;
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use opentelemetry_proto::tonic::common::v1::{any_value, AnyValue, KeyValue};
use opentelemetry_proto::tonic::resource::v1::Resource;
use opentelemetry_proto::tonic::trace::v1::{ResourceSpans, ScopeSpans, Span};
use prost::Message;
use serde_json::json;
use std::collections::HashSet;
use std::num::NonZeroU32;
use std::sync::Arc;
use std::time::Duration;

use integration_utils::DEFAULT_CONFIG;

struct FixedTime {
    pub time: DateTime<Utc>,
}

impl TimeSource for FixedTime {
    fn current_time(&self) -> DateTime<Utc> {
        self.time
    }
}

#[derive(Clone)]
struct CapturingSink {
    events: Arc<tokio::sync::Mutex<Vec<PreparedPayload>>>,
}

impl CapturingSink {
    fn new() -> Self {
        Self {
            events: Arc::new(tokio::sync::Mutex::new(Vec::new())),
        }
    }

    async fn get_events(&self) -> Vec<PreparedPayload> {
        self.events.lock().await.clone()
    }
}

#[async_trait]
impl Sink for CapturingSink {
    async fn publish(&self, prepared: Vec<PreparedPayload>) -> Vec<SinkResult> {
        let results = prepared.iter().map(|p| SinkResult::ok(p.uuid)).collect();
        self.events.lock().await.extend(prepared);
        results
    }
}

const TOKEN: &str = "phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3";

fn make_kv(key: &str, value: any_value::Value) -> KeyValue {
    KeyValue {
        key: key.to_string(),
        value: Some(AnyValue { value: Some(value) }),
    }
}

fn make_span(
    trace_id: Vec<u8>,
    span_id: Vec<u8>,
    parent_span_id: Vec<u8>,
    start_time_nanos: u64,
    attributes: Vec<KeyValue>,
) -> Span {
    Span {
        trace_id,
        span_id,
        parent_span_id,
        start_time_unix_nano: start_time_nanos,
        attributes,
        ..Default::default()
    }
}

fn make_irrelevant_http_span(trace_id: Vec<u8>, span_id: Vec<u8>) -> Span {
    make_span(
        trace_id,
        span_id,
        vec![],
        1_704_067_200_000_000_000,
        vec![
            make_kv(
                "http.request.method",
                any_value::Value::StringValue("POST".to_string()),
            ),
            make_kv(
                "url.full",
                any_value::Value::StringValue("https://example.com/api".to_string()),
            ),
        ],
    )
}

#[derive(Default)]
struct TestClientOptions {
    redis: Option<Arc<MockRedisClient>>,
    event_restriction_service: Option<EventRestrictionService>,
    quota_limiter: Option<CaptureQuotaLimiter>,
    // Opt-in OverflowLimiter wiring. `None` (default) matches production
    // configs without `OVERFLOW_ENABLED=true` and exercises the no-op branch
    // of `stamp_overflow_reason`.
    overflow_limiter: Option<Arc<OverflowLimiter>>,
}

fn make_test_client(sink: &CapturingSink) -> TestClient {
    make_test_client_with_options(sink, TestClientOptions::default())
}

fn make_test_client_with_options(sink: &CapturingSink, options: TestClientOptions) -> TestClient {
    let (readiness, liveness, _monitor) = test_lifecycle_handlers();

    let timesource = FixedTime {
        time: DateTime::parse_from_rfc3339(DEFAULT_TEST_TIME)
            .expect("Invalid fixed time format")
            .with_timezone(&Utc),
    };
    let redis = options
        .redis
        .unwrap_or_else(|| Arc::new(MockRedisClient::new()));

    let mut cfg = DEFAULT_CONFIG.clone();
    cfg.capture_mode = CaptureMode::Events;

    let quota_limiter = options.quota_limiter.unwrap_or_else(|| {
        CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60 * 60 * 24 * 7))
            .add_scoped_limiter(QuotaResource::LLMEvents, is_llm_event)
    });

    let app = router(
        timesource,
        readiness,
        liveness,
        Arc::new(OutputTable::new(Output::single(
            Arc::new(sink.clone()),
            PrepSpec::from(&DEFAULT_CONFIG.kafka),
        ))),
        redis,
        None, // global_rate_limiter_token_distinctid
        quota_limiter,
        TokenDropper::default(),
        options.event_restriction_service,
        false, // metrics
        CaptureMode::Events,
        String::from("capture-otel-test"),
        None,             // concurrency_limit
        25 * 1024 * 1024, // event_payload_size_limit
        false,            // enable_historical_rerouting
        1_i64,            // historical_rerouting_threshold_days
        false,            // is_mirror_deploy
        0.0_f32,          // verbose_sample_percent
        26_214_400,       // ai_max_sum_of_parts_bytes
        Some(Arc::new(MockBlobStorage::new(
            "test-bucket".to_string(),
            "llma/".to_string(),
        ))), // ai_blob_storage
        None,             // body_chunk_read_timeout_ms
        256,              // body_read_chunk_size_kb
        10 * 1024 * 1024, // capture_v1_max_compressed_body_bytes
        50 * 1024 * 1024, // capture_v1_max_decompressed_body_bytes
        options.overflow_limiter, // overflow_limiter
        None,             // replay_overflow_limiter
        None,             // v1_sink_router
        8,                // capture_v1_scatter_gather_min_batch
        None,             // ai_gateway_signing_secret
        None,             // ingestion_warning_emitter
    );

    TestClient::new(app)
}

const ENDPOINT: &str = "/i/v0/ai/otel";

async fn send_request(sink: &CapturingSink, request: &ExportTraceServiceRequest) -> u16 {
    let client = make_test_client(sink);
    let body = request.encode_to_vec();

    let resp = client
        .post(ENDPOINT)
        .header("Content-Type", "application/x-protobuf")
        .header("Authorization", format!("Bearer {}", TOKEN))
        .body(body)
        .send()
        .await;

    resp.status().as_u16()
}

async fn send_request_with_client(client: &TestClient, request: &ExportTraceServiceRequest) -> u16 {
    let body = request.encode_to_vec();

    let resp = client
        .post(ENDPOINT)
        .header("Content-Type", "application/x-protobuf")
        .header("Authorization", format!("Bearer {}", TOKEN))
        .body(body)
        .send()
        .await;

    resp.status().as_u16()
}

fn captured(p: &PreparedPayload) -> common_types::CapturedEvent {
    serde_json::from_slice(&p.record.payload).expect("payload must deserialize")
}

fn topic(output: &capture::outputs::registry::Outputs) -> String {
    capture::outputs::registry::OutputRegistry::from(&DEFAULT_CONFIG.kafka)
        .topic_for(output)
        .to_string()
}

fn parse_event_data(event: &PreparedPayload) -> serde_json::Value {
    serde_json::from_str(&captured(event).data).expect("event data is valid JSON")
}

fn make_single_span_request() -> ExportTraceServiceRequest {
    ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: Some(Resource {
                attributes: vec![make_kv(
                    "posthog.distinct_id",
                    any_value::Value::StringValue("user-1".to_string()),
                )],
                dropped_attributes_count: 0,
            }),
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans: vec![make_span(
                    vec![1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16],
                    vec![1, 2, 3, 4, 5, 6, 7, 8],
                    vec![],
                    1_704_067_200_000_000_000,
                    vec![make_kv(
                        "gen_ai.operation.name",
                        any_value::Value::StringValue("chat".to_string()),
                    )],
                )],
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    }
}

fn make_two_span_request() -> ExportTraceServiceRequest {
    ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: Some(Resource {
                attributes: vec![make_kv(
                    "posthog.distinct_id",
                    any_value::Value::StringValue("user-1".to_string()),
                )],
                dropped_attributes_count: 0,
            }),
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans: vec![
                    make_span(
                        vec![1; 16],
                        vec![1; 8],
                        vec![],
                        1_704_067_200_000_000_000,
                        vec![make_kv(
                            "gen_ai.operation.name",
                            any_value::Value::StringValue("chat".to_string()),
                        )],
                    ),
                    make_span(
                        vec![1; 16],
                        vec![2; 8],
                        vec![1; 8],
                        1_704_067_200_000_000_000,
                        vec![make_kv(
                            "gen_ai.operation.name",
                            any_value::Value::StringValue("embeddings".to_string()),
                        )],
                    ),
                ],
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    }
}

async fn make_restriction_service(restrictions: Vec<Restriction>) -> EventRestrictionService {
    // OTel runs in the AI capture deployment, so restrictions must be indexed
    // under Pipeline::Ai — that's the pipeline `otel/filtering.rs` looks up
    // with for every span.
    let service = EventRestrictionService::new(vec![Pipeline::Ai], Duration::from_secs(300));
    let mut manager = RestrictionManager::new();
    manager.insert_restrictions(Pipeline::Ai, TOKEN, restrictions);
    service.update(manager).await;
    service
}

#[tokio::test]
async fn test_single_span_produces_one_event() {
    let sink = CapturingSink::new();
    let request = make_single_span_request();

    let status = send_request(&sink, &request).await;
    assert_eq!(status, 200);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    let cap = captured(event);
    assert_eq!(cap.token, TOKEN);
    assert_eq!(cap.event, "$ai_generation");
    assert_eq!(cap.distinct_id, "user-1");
    assert_eq!(
        event.record.topic,
        topic(&capture::outputs::registry::Outputs::Main)
    );

    let data = parse_event_data(event);
    assert_eq!(
        data["properties"]["$ai_trace_id"],
        "0102030405060708090a0b0c0d0e0f10"
    );
    assert_eq!(data["properties"]["$ai_span_id"], "0102030405060708");
    assert_eq!(data["properties"]["$ai_ingestion_source"], "otel");
}

#[tokio::test]
async fn test_multiple_spans_produce_multiple_events() {
    let sink = CapturingSink::new();
    let request = ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: Some(Resource {
                attributes: vec![make_kv(
                    "posthog.distinct_id",
                    any_value::Value::StringValue("user-2".to_string()),
                )],
                dropped_attributes_count: 0,
            }),
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans: vec![
                    make_span(
                        vec![1; 16],
                        vec![1; 8],
                        vec![],
                        0,
                        vec![make_kv(
                            "gen_ai.operation.name",
                            any_value::Value::StringValue("chat".to_string()),
                        )],
                    ),
                    make_span(
                        vec![1; 16],
                        vec![2; 8],
                        vec![1; 8],
                        0,
                        vec![make_kv(
                            "gen_ai.operation.name",
                            any_value::Value::StringValue("embeddings".to_string()),
                        )],
                    ),
                    make_span(
                        vec![1; 16],
                        vec![3; 8],
                        vec![],
                        0,
                        vec![make_kv(
                            "gen_ai.operation.name",
                            any_value::Value::StringValue("unknown_op".to_string()),
                        )],
                    ),
                ],
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    };

    let status = send_request(&sink, &request).await;
    assert_eq!(status, 200);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 3);

    assert_eq!(captured(&events[0]).event, "$ai_generation");
    assert_eq!(captured(&events[1]).event, "$ai_embedding");
    assert_eq!(captured(&events[2]).event, "$ai_span");

    let data1 = parse_event_data(&events[1]);
    assert_eq!(data1["properties"]["$ai_parent_id"], "0101010101010101");
}

#[tokio::test]
async fn test_span_attributes_and_resource_attributes_passthrough() {
    let sink = CapturingSink::new();
    let request = ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: Some(Resource {
                attributes: vec![
                    make_kv(
                        "posthog.distinct_id",
                        any_value::Value::StringValue("user-3".to_string()),
                    ),
                    make_kv(
                        "service.name",
                        any_value::Value::StringValue("my-service".to_string()),
                    ),
                ],
                dropped_attributes_count: 0,
            }),
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans: vec![make_span(
                    vec![0xAB; 16],
                    vec![0xCD; 8],
                    vec![],
                    0,
                    vec![
                        make_kv(
                            "gen_ai.request.model",
                            any_value::Value::StringValue("gpt-4".to_string()),
                        ),
                        make_kv("gen_ai.usage.input_tokens", any_value::Value::IntValue(100)),
                        make_kv(
                            "custom.attr",
                            any_value::Value::StringValue("custom-val".to_string()),
                        ),
                    ],
                )],
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    };

    let status = send_request(&sink, &request).await;
    assert_eq!(status, 200);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let data = parse_event_data(&events[0]);
    let props = &data["properties"];

    assert_eq!(props["gen_ai.request.model"], "gpt-4");
    assert_eq!(props["gen_ai.usage.input_tokens"], 100);
    assert_eq!(props["custom.attr"], "custom-val");
    assert_eq!(props["service.name"], "my-service");
    assert_eq!(props["$ai_ingestion_source"], "otel");
}

#[tokio::test]
async fn test_multiple_resource_spans() {
    let sink = CapturingSink::new();
    let request = ExportTraceServiceRequest {
        resource_spans: vec![
            ResourceSpans {
                resource: Some(Resource {
                    attributes: vec![
                        make_kv(
                            "posthog.distinct_id",
                            any_value::Value::StringValue("user-4".to_string()),
                        ),
                        make_kv(
                            "service.name",
                            any_value::Value::StringValue("svc-a".to_string()),
                        ),
                    ],
                    dropped_attributes_count: 0,
                }),
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![make_span(
                        vec![1; 16],
                        vec![1; 8],
                        vec![],
                        0,
                        vec![make_kv(
                            "gen_ai.request.model",
                            any_value::Value::StringValue("gpt-4o-mini".to_string()),
                        )],
                    )],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            },
            ResourceSpans {
                resource: Some(Resource {
                    attributes: vec![
                        make_kv(
                            "posthog.distinct_id",
                            any_value::Value::StringValue("user-4".to_string()),
                        ),
                        make_kv(
                            "service.name",
                            any_value::Value::StringValue("svc-b".to_string()),
                        ),
                    ],
                    dropped_attributes_count: 0,
                }),
                scope_spans: vec![ScopeSpans {
                    scope: None,
                    spans: vec![make_span(
                        vec![2; 16],
                        vec![2; 8],
                        vec![],
                        0,
                        vec![make_kv(
                            "gen_ai.request.model",
                            any_value::Value::StringValue("claude-3-5-sonnet".to_string()),
                        )],
                    )],
                    schema_url: String::new(),
                }],
                schema_url: String::new(),
            },
        ],
    };

    let status = send_request(&sink, &request).await;
    assert_eq!(status, 200);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 2);

    let data0 = parse_event_data(&events[0]);
    let data1 = parse_event_data(&events[1]);
    assert_eq!(data0["properties"]["service.name"], "svc-a");
    assert_eq!(data1["properties"]["service.name"], "svc-b");
}

#[tokio::test]
async fn test_irrelevant_http_spans_are_ignored() {
    let sink = CapturingSink::new();
    let request = ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: Some(Resource {
                attributes: vec![make_kv(
                    "posthog.distinct_id",
                    any_value::Value::StringValue("user-http".to_string()),
                )],
                dropped_attributes_count: 0,
            }),
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans: vec![make_irrelevant_http_span(vec![9; 16], vec![8; 8])],
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    };

    let status = send_request(&sink, &request).await;
    assert_eq!(status, 200);

    let events = sink.get_events().await;
    assert!(events.is_empty());
}

#[tokio::test]
async fn test_mixed_requests_only_emit_relevant_ai_spans() {
    let sink = CapturingSink::new();
    let request = ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: Some(Resource {
                attributes: vec![make_kv(
                    "posthog.distinct_id",
                    any_value::Value::StringValue("user-mixed".to_string()),
                )],
                dropped_attributes_count: 0,
            }),
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans: vec![
                    make_irrelevant_http_span(vec![3; 16], vec![1; 8]),
                    make_span(
                        vec![3; 16],
                        vec![2; 8],
                        vec![],
                        1_704_067_200_000_000_000,
                        vec![make_kv(
                            "gen_ai.operation.name",
                            any_value::Value::StringValue("chat".to_string()),
                        )],
                    ),
                ],
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    };

    let status = send_request(&sink, &request).await;
    assert_eq!(status, 200);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);
    assert_eq!(captured(&events[0]).event, "$ai_generation");
}

#[tokio::test]
async fn test_empty_body_returns_400() {
    let sink = CapturingSink::new();
    let client = make_test_client(&sink);

    let resp = client
        .post(ENDPOINT)
        .header("Content-Type", "application/x-protobuf")
        .header("Authorization", format!("Bearer {}", TOKEN))
        .body(vec![])
        .send()
        .await;

    assert_eq!(resp.status().as_u16(), 400);
}

#[tokio::test]
async fn test_missing_auth_returns_401() {
    let sink = CapturingSink::new();
    let client = make_test_client(&sink);

    let request = ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: None,
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans: vec![make_span(vec![0; 16], vec![0; 8], vec![], 0, vec![])],
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    };

    let resp = client
        .post(ENDPOINT)
        .header("Content-Type", "application/x-protobuf")
        .body(request.encode_to_vec())
        .send()
        .await;

    assert_eq!(resp.status().as_u16(), 401);
}

#[tokio::test]
async fn test_invalid_token_returns_401() {
    let sink = CapturingSink::new();
    let client = make_test_client(&sink);

    let request = ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: None,
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans: vec![make_span(vec![0; 16], vec![0; 8], vec![], 0, vec![])],
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    };

    let resp = client
        .post(ENDPOINT)
        .header("Content-Type", "application/x-protobuf")
        .header("Authorization", "Bearer phx_personal_api_key_not_allowed")
        .body(request.encode_to_vec())
        .send()
        .await;

    assert_eq!(resp.status().as_u16(), 401);
}

#[tokio::test]
async fn test_unsupported_content_encoding_returns_400() {
    let sink = CapturingSink::new();
    let client = make_test_client(&sink);

    let request = ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: None,
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans: vec![make_span(vec![0; 16], vec![0; 8], vec![], 0, vec![])],
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    };

    let resp = client
        .post(ENDPOINT)
        .header("Content-Type", "application/x-protobuf")
        .header("Content-Encoding", "deflate")
        .header("Authorization", format!("Bearer {}", TOKEN))
        .body(request.encode_to_vec())
        .send()
        .await;

    assert_eq!(resp.status().as_u16(), 400);
}

#[tokio::test]
async fn test_too_many_spans_returns_400() {
    let sink = CapturingSink::new();
    let client = make_test_client(&sink);

    let spans: Vec<Span> = (0..101)
        .map(|i| {
            make_span(
                vec![0; 16],
                vec![i as u8; 8],
                vec![],
                0,
                vec![make_kv(
                    "gen_ai.operation.name",
                    any_value::Value::StringValue("chat".to_string()),
                )],
            )
        })
        .collect();

    let request = ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: Some(Resource {
                attributes: vec![make_kv(
                    "posthog.distinct_id",
                    any_value::Value::StringValue("user-limit".to_string()),
                )],
                dropped_attributes_count: 0,
            }),
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans,
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    };

    let resp = client
        .post(ENDPOINT)
        .header("Content-Type", "application/x-protobuf")
        .header("Authorization", format!("Bearer {}", TOKEN))
        .body(request.encode_to_vec())
        .send()
        .await;

    assert_eq!(resp.status().as_u16(), 400);
}

#[tokio::test]
async fn test_too_many_raw_spans_returns_400() {
    let sink = CapturingSink::new();
    let client = make_test_client(&sink);

    // 1001 non-AI spans exceeds the MAX_RAW_SPANS_PER_REQUEST limit of 1000.
    let spans: Vec<Span> = (0..1001u16)
        .map(|i| {
            let id_bytes: Vec<u8> = i.to_be_bytes().iter().chain(&[0u8; 6]).copied().collect();
            make_span(
                vec![0; 16],
                id_bytes,
                vec![],
                0,
                vec![make_kv(
                    "http.request.method",
                    any_value::Value::StringValue("GET".to_string()),
                )],
            )
        })
        .collect();

    let request = ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: Some(Resource {
                attributes: vec![make_kv(
                    "posthog.distinct_id",
                    any_value::Value::StringValue("user-raw-limit".to_string()),
                )],
                dropped_attributes_count: 0,
            }),
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans,
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    };

    let resp = client
        .post(ENDPOINT)
        .header("Content-Type", "application/x-protobuf")
        .header("Authorization", format!("Bearer {}", TOKEN))
        .body(request.encode_to_vec())
        .send()
        .await;

    assert_eq!(resp.status().as_u16(), 400);
}

// ----------------------------------------------------------------------------
// Quota Limiter Tests
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_quota_limit_exceeded_returns_400_with_no_events() {
    let llm_key = format!(
        "{}{}",
        QUOTA_LIMITER_CACHE_KEY,
        QuotaResource::LLMEvents.as_str()
    );
    let redis =
        Arc::new(MockRedisClient::new().zrangebyscore_ret(&llm_key, vec![TOKEN.to_string()]));

    let sink = CapturingSink::new();
    let client = make_test_client_with_options(
        &sink,
        TestClientOptions {
            redis: Some(redis),
            ..Default::default()
        },
    );

    let request = make_single_span_request();
    let status = send_request_with_client(&client, &request).await;
    assert_eq!(status, 400);

    let events = sink.get_events().await;
    assert!(events.is_empty());
}

#[tokio::test]
async fn test_global_quota_exceeded_retains_scoped_llm_events() {
    // When the global quota is exceeded but the scoped LLM limiter is not, the
    // CaptureQuotaLimiter retains LLM events. Since all OTel spans are $ai_*
    // events, they all get retained — no partial drop occurs and the batch
    // goes through normally.
    let global_key = format!(
        "{}{}",
        QUOTA_LIMITER_CACHE_KEY,
        QuotaResource::Events.as_str()
    );
    let redis =
        Arc::new(MockRedisClient::new().zrangebyscore_ret(&global_key, vec![TOKEN.to_string()]));

    let sink = CapturingSink::new();
    let client = make_test_client_with_options(
        &sink,
        TestClientOptions {
            redis: Some(redis),
            ..Default::default()
        },
    );

    let request = make_single_span_request();
    let status = send_request_with_client(&client, &request).await;
    assert_eq!(status, 200);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);
}

#[tokio::test]
async fn test_both_global_and_scoped_quota_exceeded_returns_400() {
    let llm_key = format!(
        "{}{}",
        QUOTA_LIMITER_CACHE_KEY,
        QuotaResource::LLMEvents.as_str()
    );
    let global_key = format!(
        "{}{}",
        QUOTA_LIMITER_CACHE_KEY,
        QuotaResource::Events.as_str()
    );
    let redis = Arc::new(
        MockRedisClient::new()
            .zrangebyscore_ret(&llm_key, vec![TOKEN.to_string()])
            .zrangebyscore_ret(&global_key, vec![TOKEN.to_string()]),
    );

    let sink = CapturingSink::new();
    let client = make_test_client_with_options(
        &sink,
        TestClientOptions {
            redis: Some(redis),
            ..Default::default()
        },
    );

    let request = make_single_span_request();
    let status = send_request_with_client(&client, &request).await;
    assert_eq!(status, 400);

    let events = sink.get_events().await;
    assert!(events.is_empty());
}

#[tokio::test]
async fn test_partial_quota_drop_rejects_entire_batch() {
    // Use a custom scoped limiter that only matches $ai_generation (not $ai_embedding).
    // When this limiter is exceeded, $ai_generation spans are dropped but $ai_embedding
    // spans are retained → partial drop → all-or-nothing rejection returns 400.
    let exceptions_key = format!(
        "{}{}",
        QUOTA_LIMITER_CACHE_KEY,
        QuotaResource::Exceptions.as_str()
    );
    let redis = Arc::new(
        MockRedisClient::new().zrangebyscore_ret(&exceptions_key, vec![TOKEN.to_string()]),
    );

    let cfg = DEFAULT_CONFIG.clone();
    let quota_limiter =
        CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60 * 60 * 24 * 7))
            .add_scoped_limiter(QuotaResource::Exceptions, |info: EventInfo| {
                info.name == "$ai_generation"
            });

    let sink = CapturingSink::new();
    let client = make_test_client_with_options(
        &sink,
        TestClientOptions {
            redis: Some(redis),
            quota_limiter: Some(quota_limiter),
            ..Default::default()
        },
    );

    // Send two spans: one $ai_generation, one $ai_embedding
    let request = make_two_span_request();
    let status = send_request_with_client(&client, &request).await;
    assert_eq!(status, 400);

    let events = sink.get_events().await;
    assert!(events.is_empty());
}

// ----------------------------------------------------------------------------
// Event Restriction Tests
// ----------------------------------------------------------------------------

#[tokio::test]
async fn test_restriction_types() {
    struct Case {
        name: &'static str,
        restriction_type: RestrictionType,
        args: Option<serde_json::Value>,
        expected_status: u16,
        check: fn(&[PreparedPayload]) -> bool,
    }

    let cases = [
        Case {
            name: "drop",
            restriction_type: RestrictionType::DropEvent,
            args: None,
            expected_status: 400,
            check: |events| events.is_empty(),
        },
        Case {
            name: "force_overflow",
            restriction_type: RestrictionType::ForceOverflow,
            args: None,
            expected_status: 200,
            check: |events| {
                events.len() == 1
                    && events[0].record.topic
                        == topic(&capture::outputs::registry::Outputs::Overflow)
            },
        },
        Case {
            name: "skip_person_processing",
            restriction_type: RestrictionType::SkipPersonProcessing,
            args: None,
            expected_status: 200,
            check: |events| {
                events.len() == 1
                    && events[0].record.headers.force_disable_person_processing == Some(true)
            },
        },
        Case {
            name: "redirect_to_dlq",
            restriction_type: RestrictionType::RedirectToDlq,
            args: None,
            expected_status: 200,
            check: |events| {
                events.len() == 1
                    && events[0].record.topic == topic(&capture::outputs::registry::Outputs::Dlq)
            },
        },
        Case {
            name: "redirect_to_topic",
            restriction_type: RestrictionType::RedirectToTopic,
            args: Some(json!({"topic": "custom_topic"})),
            expected_status: 200,
            check: |events| events.len() == 1 && events[0].record.topic == "custom_topic",
        },
    ];

    for case in &cases {
        let service = make_restriction_service(vec![Restriction {
            restriction_type: case.restriction_type,
            scope: RestrictionScope::AllEvents,
            args: case.args.clone(),
        }])
        .await;

        let sink = CapturingSink::new();
        let client = make_test_client_with_options(
            &sink,
            TestClientOptions {
                event_restriction_service: Some(service),
                ..Default::default()
            },
        );

        let request = make_single_span_request();
        let status = send_request_with_client(&client, &request).await;
        assert_eq!(status, case.expected_status, "failed for: {}", case.name);

        let events = sink.get_events().await;
        assert!((case.check)(&events), "check failed for: {}", case.name);
    }
}

#[tokio::test]
async fn test_filtered_drop_restriction_rejects_otel_batch() {
    let mut event_names = HashSet::new();
    event_names.insert("$ai_generation".to_string());

    let service = make_restriction_service(vec![Restriction {
        restriction_type: RestrictionType::DropEvent,
        scope: RestrictionScope::Filtered(RestrictionFilters {
            event_names,
            ..Default::default()
        }),
        args: None,
    }])
    .await;

    let sink = CapturingSink::new();
    let client = make_test_client_with_options(
        &sink,
        TestClientOptions {
            event_restriction_service: Some(service),
            ..Default::default()
        },
    );

    let request = make_two_span_request();
    let status = send_request_with_client(&client, &request).await;
    assert_eq!(status, 400);

    // The $ai_generation span matches the filtered drop restriction, so the
    // entire batch is rejected (all-or-nothing semantics).
    let events = sink.get_events().await;
    assert!(events.is_empty());
}

// ============================================================================
// OverflowLimiter coverage for the OTEL endpoint
// ============================================================================
//
// `otel_handler` bypasses `events::analytics::process_events` and produces
// `DataType::AnalyticsMain` spans directly, so the shared
// `stamp_overflow_reason` helper is what preserves OverflowLimiter parity for
// `capture-ai-prod-us`. These tests exercise the helper end-to-end across the
// OTEL batch path.
//
// Note on OTEL batching semantics: `otel::identity::extract_distinct_id`
// returns a single distinct_id for the entire request (derived from
// ResourceSpan attributes), so all spans in one request share the same
// `token:distinct_id` key. The helper still evaluates per-event — the tests
// below reflect the realistic per-request shape.

fn make_three_span_request() -> ExportTraceServiceRequest {
    ExportTraceServiceRequest {
        resource_spans: vec![ResourceSpans {
            resource: Some(Resource {
                attributes: vec![make_kv(
                    "posthog.distinct_id",
                    any_value::Value::StringValue("user-1".to_string()),
                )],
                dropped_attributes_count: 0,
            }),
            scope_spans: vec![ScopeSpans {
                scope: None,
                spans: vec![
                    make_span(
                        vec![1; 16],
                        vec![1; 8],
                        vec![],
                        1_704_067_200_000_000_000,
                        vec![make_kv(
                            "gen_ai.operation.name",
                            any_value::Value::StringValue("chat".to_string()),
                        )],
                    ),
                    make_span(
                        vec![1; 16],
                        vec![2; 8],
                        vec![1; 8],
                        1_704_067_200_000_000_000,
                        vec![make_kv(
                            "gen_ai.operation.name",
                            any_value::Value::StringValue("chat".to_string()),
                        )],
                    ),
                    make_span(
                        vec![1; 16],
                        vec![3; 8],
                        vec![1; 8],
                        1_704_067_200_000_000_000,
                        vec![make_kv(
                            "gen_ai.operation.name",
                            any_value::Value::StringValue("chat".to_string()),
                        )],
                    ),
                ],
                schema_url: String::new(),
            }],
            schema_url: String::new(),
        }],
    }
}

#[tokio::test]
async fn test_otel_batch_with_hot_token_stamps_force_limited_on_every_span() {
    // Hot-list the request's `token:distinct_id`. Because OTEL derives one
    // distinct_id per request (see identity::extract_distinct_id), every span
    // in the batch shares the key, so every span is stamped ForceLimited.
    let hot_key = format!("{TOKEN}:user-1");
    let overflow_limiter = Arc::new(OverflowLimiter::new(
        NonZeroU32::new(1_000).unwrap(),
        NonZeroU32::new(1_000).unwrap(),
        Some(hot_key),
        true, // preserve_locality
    ));

    let sink = CapturingSink::new();
    let client = make_test_client_with_options(
        &sink,
        TestClientOptions {
            overflow_limiter: Some(overflow_limiter),
            ..Default::default()
        },
    );

    let request = make_three_span_request();
    let status = send_request_with_client(&client, &request).await;
    assert_eq!(status, 200);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 3);

    for (i, event) in events.iter().enumerate() {
        assert_eq!(
            event.record.topic,
            topic(&capture::outputs::registry::Outputs::Overflow),
            "span[{i}] must be rerouted to overflow (ForceLimited)"
        );
        assert!(
            event.record.key.is_none(),
            "span[{i}] ForceLimited drops the partition key"
        );
        assert_eq!(
            event.record.headers.force_disable_person_processing,
            Some(true),
            "span[{i}] ForceLimited implies person processing disabled"
        );
    }
}

#[tokio::test]
async fn test_otel_batch_rate_limited_key_stamps_overbudget_spans() {
    // burst=1, per_second=1: the first span in the batch fits, subsequent
    // spans exhaust the budget and get RateLimited. This proves the helper
    // runs per-event within the OTEL Vec (not once-per-request) and that the
    // `preserve_locality` flag is mirrored faithfully onto the reason.
    let overflow_limiter = Arc::new(OverflowLimiter::new(
        NonZeroU32::new(1).unwrap(),
        NonZeroU32::new(1).unwrap(),
        None,
        true, // preserve_locality
    ));

    let sink = CapturingSink::new();
    let client = make_test_client_with_options(
        &sink,
        TestClientOptions {
            overflow_limiter: Some(overflow_limiter),
            ..Default::default()
        },
    );

    let request = make_three_span_request();
    let status = send_request_with_client(&client, &request).await;
    assert_eq!(status, 200);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 3);

    assert_eq!(
        events[0].record.topic,
        topic(&capture::outputs::registry::Outputs::Main),
        "first span fits within the burst"
    );
    for (i, event) in events.iter().enumerate().skip(1) {
        assert_eq!(
            event.record.topic,
            topic(&capture::outputs::registry::Outputs::Overflow),
            "span[{i}] must be rerouted to overflow (RateLimited)"
        );
        assert!(
            event.record.key.is_some(),
            "span[{i}] preserve_locality keeps the partition key"
        );
        assert_eq!(
            event.record.headers.force_disable_person_processing, None,
            "span[{i}] RateLimited does NOT disable person processing"
        );
    }
}

#[tokio::test]
async fn test_otel_batch_without_overflow_limiter_leaves_reason_none() {
    // Baseline: no limiter wired (deploy without `OVERFLOW_ENABLED=true`) —
    // overflow_reason must stay None across the batch, matching pre-refactor
    // behavior.
    let sink = CapturingSink::new();
    let request = make_three_span_request();

    let status = send_request(&sink, &request).await;
    assert_eq!(status, 200);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 3);
    for event in &events {
        assert_eq!(
            event.record.topic,
            topic(&capture::outputs::registry::Outputs::Main)
        );
        assert_eq!(event.record.headers.force_disable_person_processing, None);
    }
}
