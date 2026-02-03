#[path = "common/integration_utils.rs"]
mod integration_utils;

use async_trait::async_trait;
use axum_test_helper::TestClient;
use capture::ai_s3::MockBlobStorage;
use capture::api::CaptureError;
use capture::config::CaptureMode;
use capture::quota_limiters::CaptureQuotaLimiter;
use capture::router::router;
use capture::sinks::Event;
use capture::time::TimeSource;
use capture::v0_request::{DataType, ProcessedEvent};
use chrono::{DateTime, Utc};
use common_redis::MockRedisClient;
use health::HealthRegistry;
use integration_utils::DEFAULT_TEST_TIME;
use limiters::token_dropper::TokenDropper;
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use opentelemetry_proto::tonic::common::v1::{any_value, AnyValue, KeyValue};
use opentelemetry_proto::tonic::resource::v1::Resource;
use opentelemetry_proto::tonic::trace::v1::{ResourceSpans, ScopeSpans, Span};
use prost::Message;
use std::sync::Arc;
use std::time::Duration;

#[path = "common/utils.rs"]
mod test_utils;
use test_utils::DEFAULT_CONFIG;

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
    events: Arc<tokio::sync::Mutex<Vec<ProcessedEvent>>>,
}

impl CapturingSink {
    fn new() -> Self {
        Self {
            events: Arc::new(tokio::sync::Mutex::new(Vec::new())),
        }
    }

    async fn get_events(&self) -> Vec<ProcessedEvent> {
        self.events.lock().await.clone()
    }
}

#[async_trait]
impl Event for CapturingSink {
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.events.lock().await.push(event);
        Ok(())
    }

    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        self.events.lock().await.extend(events);
        Ok(())
    }
}

const TOKEN: &str = "phc_VXRzc3poSG9GZm1JenRianJ6TTJFZGh4OWY2QXzx9f3";

fn make_kv(key: &str, value: any_value::Value) -> KeyValue {
    KeyValue {
        key: key.to_string(),
        value: Some(AnyValue {
            value: Some(value),
        }),
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

async fn send_request(sink: &CapturingSink, request: &ExportTraceServiceRequest) -> u16 {
    let liveness = HealthRegistry::new("otel_test");
    let timesource = FixedTime {
        time: DateTime::parse_from_rfc3339(DEFAULT_TEST_TIME)
            .expect("Invalid fixed time format")
            .with_timezone(&Utc),
    };
    let redis = Arc::new(MockRedisClient::new());

    let mut cfg = DEFAULT_CONFIG.clone();
    cfg.capture_mode = CaptureMode::Events;

    let quota_limiter =
        CaptureQuotaLimiter::new(&cfg, redis.clone(), Duration::from_secs(60 * 60 * 24 * 7));

    let app = router(
        timesource,
        liveness,
        sink.clone(),
        redis,
        None,
        quota_limiter,
        TokenDropper::default(),
        None,
        false,
        CaptureMode::Events,
        String::from("capture-otel-test"),
        None,
        25 * 1024 * 1024,
        false,
        1_i64,
        false,
        0.0_f32,
        26_214_400,
        Some(Arc::new(MockBlobStorage::new(
            "test-bucket".to_string(),
            "llma/".to_string(),
        ))),
        Some(10),
        None,
        256,
    );

    let client = TestClient::new(app);
    let body = request.encode_to_vec();

    let resp = client
        .post("/i/v0/llma_otel")
        .header("Content-Type", "application/x-protobuf")
        .header("Authorization", format!("Bearer {}", TOKEN))
        .body(body)
        .send()
        .await;

    resp.status().as_u16()
}

fn parse_event_data(event: &ProcessedEvent) -> serde_json::Value {
    serde_json::from_str(&event.event.data).expect("event data is valid JSON")
}

#[tokio::test]
async fn test_single_span_produces_one_event() {
    let sink = CapturingSink::new();
    let request = ExportTraceServiceRequest {
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
    };

    let status = send_request(&sink, &request).await;
    assert_eq!(status, 200);

    let events = sink.get_events().await;
    assert_eq!(events.len(), 1);

    let event = &events[0];
    assert_eq!(event.event.token, TOKEN);
    assert_eq!(event.event.event, "$ai_generation");
    assert_eq!(event.event.distinct_id, "user-1");
    assert_eq!(event.metadata.data_type, DataType::AnalyticsMain);
    assert_eq!(event.metadata.event_name, "$ai_generation");

    let data = parse_event_data(event);
    assert_eq!(data["properties"]["$ai_trace_id"], "0102030405060708090a0b0c0d0e0f10");
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

    assert_eq!(events[0].event.event, "$ai_generation");
    assert_eq!(events[1].event.event, "$ai_embedding");
    assert_eq!(events[2].event.event, "$ai_span");

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
                        make_kv(
                            "gen_ai.usage.input_tokens",
                            any_value::Value::IntValue(100),
                        ),
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
    assert_eq!(props["gen_ai.usage.input_tokens"], "100");
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
                    spans: vec![make_span(vec![1; 16], vec![1; 8], vec![], 0, vec![])],
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
                    spans: vec![make_span(vec![2; 16], vec![2; 8], vec![], 0, vec![])],
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
