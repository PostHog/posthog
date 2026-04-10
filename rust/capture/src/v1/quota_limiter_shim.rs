use std::collections::HashMap;

use common_types::HasEventName;
use limiters::redis::QuotaResource;
use metrics::counter;
use uuid::Uuid;

use crate::quota_limiters::CaptureQuotaLimiter;
use crate::quota_limiters::{is_exception_event, is_llm_event, is_survey_event, EventInfo};
use crate::v1::analytics::constants::CAPTURE_V1_EVENTS_QUOTA_LIMITED;
use crate::v1::analytics::types::{EventResult, WrappedEvent};
use crate::v1::sinks::Destination;
use crate::v1::Error;

type ScopedCheck = (QuotaResource, fn(EventInfo) -> bool);

const SCOPED_CHECKS: &[ScopedCheck] = &[
    (QuotaResource::Exceptions, is_exception_event),
    (QuotaResource::Surveys, is_survey_event),
    (QuotaResource::LLMEvents, is_llm_event),
];

/// Apply billing quota limits to a batch of events in-place.
///
/// Checks the global limiter first (short-circuit on full batch drop), then
/// iterates scoped limiters, marking matching events as `Limited` / `Drop`.
/// Returns `Error::BillingLimitExceeded` when the entire batch is limited.
pub async fn apply_quota_limits(
    limiter: &CaptureQuotaLimiter,
    token: &str,
    events: &mut HashMap<Uuid, WrappedEvent>,
) -> Result<(), Error> {
    if events.is_empty() {
        return Ok(());
    }

    // --- Global check — short-circuit ---
    if limiter
        .is_quota_limited_v1(token, &QuotaResource::Events)
        .await
    {
        counter!(CAPTURE_V1_EVENTS_QUOTA_LIMITED, "resource" => "events")
            .increment(events.len() as u64);
        return Err(Error::BillingLimitExceeded);
    }

    // --- Scoped checks ---
    let mut all_non_ok = true;
    for (resource, predicate) in SCOPED_CHECKS {
        if !limiter.is_quota_limited_v1(token, resource).await {
            continue;
        }

        let resource_tag = resource.as_str();
        let mut count: u64 = 0;
        for ev in events.values_mut() {
            if ev.result != EventResult::Ok {
                continue;
            }
            let info = EventInfo {
                name: ev.event_name(),
                has_product_tour_id: ev.has_property("product_tour_id"),
            };
            if predicate(info) {
                ev.result = EventResult::Limited;
                ev.destination = Destination::Drop;
                ev.details = Some(match resource {
                    QuotaResource::Exceptions => "exceptions_over_quota",
                    QuotaResource::Surveys => "survey_responses_over_quota",
                    QuotaResource::LLMEvents => "llm_events_over_quota",
                    _ => "over_quota",
                });
                count += 1;
            }
        }
        if count > 0 {
            counter!(CAPTURE_V1_EVENTS_QUOTA_LIMITED, "resource" => resource_tag).increment(count);
        }
    }

    // If every event is now non-Ok, the whole batch is limited
    for ev in events.values() {
        if ev.result == EventResult::Ok {
            all_non_ok = false;
            break;
        }
    }
    if all_non_ok {
        return Err(Error::BillingLimitExceeded);
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::num::NonZeroU32;
    use std::sync::Arc;
    use std::time::Duration;

    use chrono::{DateTime, Utc};
    use common_continuous_profiling::ContinuousProfilingConfig;
    use common_redis::MockRedisClient;
    use limiters::redis::QUOTA_LIMITER_CACHE_KEY;
    use serde_json::value::RawValue;
    use tracing::Level;
    use uuid::Uuid;

    use crate::config::{CaptureMode, Config, KafkaConfig};
    use crate::v1::analytics::types::{Event, Options};
    use crate::v1::test_utils::events_map;

    fn test_config() -> Config {
        Config {
            print_sink: false,
            noop_sink: false,
            address: "127.0.0.1:0".parse().unwrap(),
            redis_url: "redis://localhost:6379/".to_string(),
            redis_response_timeout_ms: 100,
            redis_connection_timeout_ms: 5000,
            global_rate_limit_enabled: false,
            global_rate_limit_window_interval_secs: 60,
            global_rate_limit_sync_interval_secs: 15,
            global_rate_limit_tick_interval_ms: 1000,
            global_rate_limit_token_distinctid_threshold: 10_000,
            global_rate_limit_token_distinctid_overrides_csv: None,
            global_rate_limit_token_distinctid_local_cache_max_entries: 300_000,
            global_rate_limit_token_threshold: 300_000,
            global_rate_limit_token_overrides_csv: None,
            global_rate_limit_token_local_cache_max_entries: 300_000,
            global_rate_limit_redis_url: None,
            global_rate_limit_redis_reader_url: None,
            global_rate_limit_redis_response_timeout_ms: None,
            global_rate_limit_redis_connection_timeout_ms: None,
            event_restrictions_enabled: false,
            event_restrictions_redis_url: None,
            event_restrictions_refresh_interval_secs: 30,
            event_restrictions_fail_open_after_secs: 300,
            overflow_enabled: false,
            overflow_preserve_partition_locality: false,
            overflow_burst_limit: NonZeroU32::new(5).unwrap(),
            overflow_per_second_limit: NonZeroU32::new(10).unwrap(),
            ingestion_force_overflow_by_token_distinct_id: None,
            drop_events_by_token_distinct_id: None,
            enable_historical_rerouting: false,
            historical_rerouting_threshold_days: 1,
            is_mirror_deploy: false,
            log_level: Level::INFO,
            verbose_sample_percent: 0.0,
            kafka: KafkaConfig {
                kafka_producer_linger_ms: 0,
                kafka_producer_queue_mib: 10,
                kafka_message_timeout_ms: 10000,
                kafka_producer_message_max_bytes: 1000000,
                kafka_topic_metadata_refresh_interval_ms: 10000,
                kafka_compression_codec: "none".to_string(),
                kafka_hosts: "kafka:9092".to_string(),
                kafka_topic: "events_plugin_ingestion".to_string(),
                kafka_overflow_topic: "events_plugin_ingestion_overflow".to_string(),
                kafka_historical_topic: "events_plugin_ingestion_historical".to_string(),
                kafka_client_ingestion_warning_topic: "events_plugin_ingestion".to_string(),
                kafka_exceptions_topic: "events_plugin_ingestion".to_string(),
                kafka_error_tracking_topic: "error_tracking_events".to_string(),
                kafka_heatmaps_topic: "events_plugin_ingestion".to_string(),
                kafka_replay_overflow_topic: "session_recording_snapshot_item_overflow".to_string(),
                kafka_dlq_topic: "events_plugin_ingestion_dlq".to_string(),
                kafka_traces_topic: "ingestion_traces".to_string(),
                kafka_tls: false,
                kafka_client_id: String::new(),
                kafka_metadata_max_age_ms: 60000,
                kafka_producer_max_retries: 2,
                kafka_producer_acks: "all".to_string(),
                kafka_socket_timeout_ms: 60000,
                kafka_producer_batch_num_messages: 10000,
                kafka_producer_batch_size: 1000000,
                kafka_producer_max_in_flight_requests: 1000000,
                kafka_producer_sticky_partitioning_linger_ms: 10,
                kafka_producer_enable_idempotence: false,
            },
            otel_url: None,
            otel_sampling_rate: 0.0,
            otel_service_name: "capture-testing".to_string(),
            export_prometheus: false,
            redis_key_prefix: None,
            capture_mode: CaptureMode::Events,
            concurrency_limit: None,
            s3_fallback_enabled: false,
            s3_fallback_bucket: None,
            s3_fallback_endpoint: None,
            s3_fallback_prefix: String::new(),
            ai_max_sum_of_parts_bytes: 26_214_400,
            ai_s3_bucket: None,
            ai_s3_prefix: "llma/".to_string(),
            ai_s3_endpoint: None,
            ai_s3_region: "us-east-1".to_string(),
            ai_s3_access_key_id: None,
            ai_s3_secret_access_key: None,
            request_timeout_seconds: Some(10),
            http1_header_read_timeout_ms: Some(5000),
            body_chunk_read_timeout_ms: None,
            body_read_chunk_size_kb: 256,
            error_tracking_node_rollout_enabled: false,
            error_tracking_node_rollout_rate: 0.0,
            continuous_profiling: ContinuousProfilingConfig {
                continuous_profiling_enabled: false,
                pyroscope_server_address: String::new(),
                pyroscope_application_name: String::new(),
                pyroscope_sample_rate: 100,
            },
            capture_v1_sinks: String::new(),
        }
    }

    async fn build_limiter(
        token: &str,
        set_global_limit: bool,
        resources_to_limit: &[QuotaResource],
    ) -> CaptureQuotaLimiter {
        let cfg = test_config();
        let global_resource = CaptureQuotaLimiter::get_resource_for_mode(cfg.capture_mode);
        let global_key = format!("{}{}", QUOTA_LIMITER_CACHE_KEY, global_resource.as_str());

        let mut redis = if set_global_limit {
            MockRedisClient::new().zrangebyscore_ret(&global_key, vec![token.to_string()])
        } else {
            MockRedisClient::new().zrangebyscore_ret(&global_key, vec![])
        };

        for resource in &[
            QuotaResource::Exceptions,
            QuotaResource::Surveys,
            QuotaResource::LLMEvents,
        ] {
            let key = format!("{}{}", QUOTA_LIMITER_CACHE_KEY, resource.as_str());
            let limited_tokens = if resources_to_limit.contains(resource) {
                vec![token.to_string()]
            } else {
                vec![]
            };
            redis = redis.zrangebyscore_ret(&key, limited_tokens);
        }

        let limiter = CaptureQuotaLimiter::new(&cfg, Arc::new(redis), Duration::from_secs(60))
            .add_scoped_limiter(QuotaResource::Exceptions, is_exception_event)
            .add_scoped_limiter(QuotaResource::Surveys, is_survey_event)
            .add_scoped_limiter(QuotaResource::LLMEvents, is_llm_event);

        // Allow background tasks to populate the DashMap caches from MockRedisClient
        tokio::time::sleep(Duration::from_millis(50)).await;

        limiter
    }

    fn make_event(name: &str, product_tour_id: Option<&str>) -> WrappedEvent {
        WrappedEvent {
            event: Event {
                event: name.to_string(),
                uuid: Uuid::now_v7().to_string(),
                distinct_id: "test_user".to_string(),
                timestamp: "2026-03-26T12:00:00.000Z".to_string(),
                session_id: None,
                window_id: None,
                options: Options {
                    cookieless_mode: None,
                    disable_skew_adjustment: None,
                    product_tour_id: product_tour_id.map(String::from),
                    process_person_profile: None,
                },
                properties: RawValue::from_string("{}".to_owned()).unwrap(),
            },
            adjusted_timestamp: Some(
                DateTime::parse_from_rfc3339("2026-03-26T12:00:00Z")
                    .unwrap()
                    .with_timezone(&Utc),
            ),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            skip_person_processing: false,
        }
    }

    fn ok_event_names(events: &HashMap<Uuid, WrappedEvent>) -> Vec<&str> {
        let mut names: Vec<&str> = events
            .values()
            .filter(|e| e.result == EventResult::Ok)
            .map(|e| e.event.event.as_str())
            .collect();
        names.sort();
        names
    }

    fn limited_event_names(events: &HashMap<Uuid, WrappedEvent>) -> Vec<&str> {
        let mut names: Vec<&str> = events
            .values()
            .filter(|e| e.result == EventResult::Limited)
            .map(|e| e.event.event.as_str())
            .collect();
        names.sort();
        names
    }

    fn find_by_name<'a>(events: &'a HashMap<Uuid, WrappedEvent>, name: &str) -> &'a WrappedEvent {
        events.values().find(|e| e.event.event == name).unwrap()
    }

    // -----------------------------------------------------------------------
    // No limits
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn no_limits_all_events_pass() {
        let limiter = build_limiter("tok", false, &[]).await;
        let mut events = events_map(vec![
            make_event("$pageview", None),
            make_event("$exception", None),
            make_event("survey sent", None),
            make_event("$ai_generation", None),
        ]);

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());
        assert_eq!(ok_event_names(&events).len(), 4);
        assert!(limited_event_names(&events).is_empty());
    }

    // -----------------------------------------------------------------------
    // Global limit
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn global_limit_returns_error_without_marking_events() {
        let limiter = build_limiter("tok", true, &[]).await;
        let mut events = events_map(vec![
            make_event("$pageview", None),
            make_event("$exception", None),
            make_event("survey sent", None),
            make_event("$ai_generation", None),
        ]);

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_err());

        // Global limit short-circuits without mutating events
        assert_eq!(ok_event_names(&events).len(), 4);
        assert!(limited_event_names(&events).is_empty());
    }

    #[tokio::test]
    async fn global_limit_preserves_all_event_states() {
        let limiter = build_limiter("tok", true, &[]).await;
        let bad = make_event("bad_event", None);
        let bad_uuid = Uuid::parse_str(&bad.event.uuid).unwrap();
        let mut events = events_map(vec![make_event("$pageview", None), bad]);
        // Pre-mark one event as Drop (e.g. from validation)
        let bad_ev = events.get_mut(&bad_uuid).unwrap();
        bad_ev.result = EventResult::Drop;
        bad_ev.destination = Destination::Drop;
        bad_ev.details = Some("invalid_event_name");

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_err());

        // Global limit short-circuits — no events are mutated
        let pv = find_by_name(&events, "$pageview");
        assert_eq!(pv.result, EventResult::Ok);
        assert_eq!(pv.details, None);

        // Pre-existing Drop event also untouched
        let bad_ev = events.get(&bad_uuid).unwrap();
        assert_eq!(bad_ev.result, EventResult::Drop);
        assert_eq!(bad_ev.details, Some("invalid_event_name"));
    }

    #[tokio::test]
    async fn global_limit_different_token_not_affected() {
        let limiter = build_limiter("limited_tok", true, &[]).await;
        let mut events = events_map(vec![
            make_event("$pageview", None),
            make_event("$exception", None),
        ]);

        let result = apply_quota_limits(&limiter, "other_tok", &mut events).await;
        assert!(result.is_ok());
        assert_eq!(ok_event_names(&events).len(), 2);
    }

    // -----------------------------------------------------------------------
    // Exception scoped limit
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn exception_limit_marks_only_exceptions() {
        let limiter = build_limiter("tok", false, &[QuotaResource::Exceptions]).await;
        let mut events = events_map(vec![
            make_event("$pageview", None),
            make_event("$exception", None),
            make_event("survey sent", None),
            make_event("$exception", None),
        ]);

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        let mut ok = ok_event_names(&events);
        ok.sort();
        assert_eq!(ok, vec!["$pageview", "survey sent"]);
        assert_eq!(
            limited_event_names(&events),
            vec!["$exception", "$exception"]
        );
        for ev in events.values().filter(|e| e.result == EventResult::Limited) {
            assert_eq!(ev.details, Some("exceptions_over_quota"));
        }
    }

    #[tokio::test]
    async fn exception_limit_all_exceptions_returns_error() {
        let limiter = build_limiter("tok", false, &[QuotaResource::Exceptions]).await;
        let mut events = events_map(vec![
            make_event("$exception", None),
            make_event("$exception", None),
        ]);

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_err());
        assert_eq!(limited_event_names(&events).len(), 2);
    }

    // -----------------------------------------------------------------------
    // Survey scoped limit
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn survey_limit_marks_only_survey_events() {
        let limiter = build_limiter("tok", false, &[QuotaResource::Surveys]).await;
        let mut events = events_map(vec![
            make_event("$pageview", None),
            make_event("survey sent", None),
            make_event("survey shown", None),
            make_event("survey dismissed", None),
            make_event("$exception", None),
        ]);

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        let mut ok = ok_event_names(&events);
        ok.sort();
        assert_eq!(ok, vec!["$exception", "$pageview"]);
        assert_eq!(limited_event_names(&events).len(), 3);
        for ev in events.values().filter(|e| e.result == EventResult::Limited) {
            assert_eq!(ev.details, Some("survey_responses_over_quota"));
        }
    }

    #[tokio::test]
    async fn survey_limit_excludes_product_tour_events() {
        let limiter = build_limiter("tok", false, &[QuotaResource::Surveys]).await;
        let tour_ev = make_event("survey sent", Some("tour-123"));
        let tour_uuid = Uuid::parse_str(&tour_ev.event.uuid).unwrap();
        let mut events = events_map(vec![make_event("survey sent", None), tour_ev]);

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        // Product tour survey → Ok, regular survey → Limited
        assert_eq!(events.get(&tour_uuid).unwrap().result, EventResult::Ok);
        assert_eq!(limited_event_names(&events).len(), 1);
    }

    // -----------------------------------------------------------------------
    // LLM scoped limit
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn llm_limit_marks_only_ai_events() {
        let limiter = build_limiter("tok", false, &[QuotaResource::LLMEvents]).await;
        let mut events = events_map(vec![
            make_event("$ai_generation", None),
            make_event("$ai_span", None),
            make_event("$pageview", None),
            make_event("$ai_trace", None),
        ]);

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        assert_eq!(ok_event_names(&events), vec!["$pageview"]);
        assert_eq!(limited_event_names(&events).len(), 3);
        for ev in events.values().filter(|e| e.result == EventResult::Limited) {
            assert_eq!(ev.details, Some("llm_events_over_quota"));
        }
    }

    #[tokio::test]
    async fn llm_limit_ignores_non_ai_prefix() {
        let limiter = build_limiter("tok", false, &[QuotaResource::LLMEvents]).await;
        let mut events = events_map(vec![
            make_event("$ai_generation", None),
            make_event("$ainotcounted", None), // no underscore
            make_event("ai_generation", None), // no $ prefix
        ]);

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        let mut ok = ok_event_names(&events);
        ok.sort();
        assert_eq!(ok, vec!["$ainotcounted", "ai_generation"]);
        assert_eq!(limited_event_names(&events), vec!["$ai_generation"]);
    }

    // -----------------------------------------------------------------------
    // Multiple scoped limits
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn multiple_scoped_limits_applied_independently() {
        let limiter = build_limiter(
            "tok",
            false,
            &[
                QuotaResource::Exceptions,
                QuotaResource::Surveys,
                QuotaResource::LLMEvents,
            ],
        )
        .await;
        let mut events = events_map(vec![
            make_event("$exception", None),
            make_event("survey sent", None),
            make_event("$ai_generation", None),
            make_event("$pageview", None),
        ]);

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        assert_eq!(ok_event_names(&events), vec!["$pageview"]);
        assert_eq!(limited_event_names(&events).len(), 3);
        assert_eq!(
            find_by_name(&events, "$exception").details,
            Some("exceptions_over_quota")
        );
        assert_eq!(
            find_by_name(&events, "survey sent").details,
            Some("survey_responses_over_quota")
        );
        assert_eq!(
            find_by_name(&events, "$ai_generation").details,
            Some("llm_events_over_quota")
        );
    }

    #[tokio::test]
    async fn all_scoped_limited_returns_error() {
        let limiter = build_limiter(
            "tok",
            false,
            &[
                QuotaResource::Exceptions,
                QuotaResource::Surveys,
                QuotaResource::LLMEvents,
            ],
        )
        .await;
        let mut events = events_map(vec![
            make_event("$exception", None),
            make_event("survey sent", None),
            make_event("$ai_generation", None),
        ]);

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_err());
        assert!(ok_event_names(&events).is_empty());
    }

    // -----------------------------------------------------------------------
    // Global + scoped limits interaction
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn global_limit_short_circuits_before_scoped() {
        // Global limited, plus scoped exception limited
        let limiter = build_limiter("tok", true, &[QuotaResource::Exceptions]).await;
        let mut events = events_map(vec![
            make_event("$pageview", None),
            make_event("$exception", None),
        ]);

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_err());

        // Global short-circuits without marking — scoped limiters never run
        for ev in events.values() {
            assert_eq!(ev.result, EventResult::Ok);
            assert_eq!(ev.details, None);
        }
    }

    // -----------------------------------------------------------------------
    // Pre-existing non-Ok events + post-check
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn pre_existing_drop_events_counted_in_post_check() {
        // No global limit, but exceptions limited
        let limiter = build_limiter("tok", false, &[QuotaResource::Exceptions]).await;
        let pv = make_event("$pageview", None);
        let pv_uuid = Uuid::parse_str(&pv.event.uuid).unwrap();
        let mut events = events_map(vec![make_event("$exception", None), pv]);
        // Pre-mark pageview as Drop from a prior validation step
        let pv_ev = events.get_mut(&pv_uuid).unwrap();
        pv_ev.result = EventResult::Drop;
        pv_ev.destination = Destination::Drop;

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        // $exception → Limited, $pageview → already Drop → all non-Ok → error
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn mixed_pre_existing_and_scoped_still_ok_if_some_remain() {
        let limiter = build_limiter("tok", false, &[QuotaResource::Exceptions]).await;
        let pv = make_event("$pageview", None);
        let pv_uuid = Uuid::parse_str(&pv.event.uuid).unwrap();
        let mut events = events_map(vec![
            make_event("$exception", None),
            pv,
            make_event("click", None),
        ]);
        events.get_mut(&pv_uuid).unwrap().result = EventResult::Drop;

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        // "click" still Ok, so should return Ok
        assert!(result.is_ok());
        assert_eq!(ok_event_names(&events), vec!["click"]);
    }

    // -----------------------------------------------------------------------
    // Empty batch
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn empty_batch_returns_ok_when_global_limited() {
        let limiter = build_limiter("tok", true, &[]).await;
        let mut events: HashMap<Uuid, WrappedEvent> = HashMap::new();

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn empty_batch_returns_ok_when_not_limited() {
        let limiter = build_limiter("tok", false, &[]).await;
        let mut events: HashMap<Uuid, WrappedEvent> = HashMap::new();

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());
    }
}
