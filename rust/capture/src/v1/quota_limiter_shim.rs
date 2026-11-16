use common_types::HasEventName;
use limiters::redis::QuotaResource;
use metrics::counter;

use crate::quota_limiters::CaptureQuotaLimiter;
use crate::quota_limiters::{is_exception_event, is_llm_event, is_survey_event, EventInfo};
use crate::v1::analytics::constants::CAPTURE_V1_EVENTS_QUOTA_LIMITED;
use crate::v1::analytics::types::{EventResult, WrappedEvent};
use crate::v1::Error;

type ScopedCheck = (QuotaResource, fn(EventInfo) -> bool);

const SCOPED_CHECKS: &[ScopedCheck] = &[
    (QuotaResource::Exceptions, is_exception_event),
    (QuotaResource::Surveys, is_survey_event),
    (QuotaResource::LLMEvents, is_llm_event),
];

/// Apply billing quota limits to a batch of events in-place.
///
/// As in legacy `check_and_filter`, scoped events answer only to their own quota.
/// Returns `Error::BillingLimitExceeded` when no event is left `Ok`.
/// Expects at least one `Ok` event — all-dropped batches should
/// short-circuit in `process_batch` before reaching here.
pub async fn apply_quota_limits(
    limiter: &CaptureQuotaLimiter,
    token: &str,
    events: &mut [WrappedEvent],
) -> Result<(), Error> {
    if events.is_empty() {
        return Ok(());
    }

    let events_limited = limiter
        .is_quota_limited_v1(token, &QuotaResource::Events)
        .await;
    let mut scoped_limited = [false; SCOPED_CHECKS.len()];
    for (limited, (resource, _)) in scoped_limited.iter_mut().zip(SCOPED_CHECKS) {
        *limited = limiter.is_quota_limited_v1(token, resource).await;
    }
    if !events_limited && !scoped_limited.contains(&true) {
        return Ok(());
    }

    let mut dropped: [u64; SCOPED_CHECKS.len() + 1] = [0; SCOPED_CHECKS.len() + 1];
    for ev in events.iter_mut() {
        if ev.result != EventResult::Ok {
            continue;
        }
        let Some(slot) = quota_drop_slot(ev, events_limited, &scoped_limited) else {
            continue;
        };
        ev.result = EventResult::Drop;
        ev.details = Some(over_quota_details(slot_resource(slot)));
        dropped[slot] += 1;
    }

    for (slot, count) in dropped.iter().enumerate() {
        if *count > 0 {
            counter!(CAPTURE_V1_EVENTS_QUOTA_LIMITED, "resource" => slot_resource(slot).as_str())
                .increment(*count);
        }
    }

    if events.iter().all(|ev| ev.result != EventResult::Ok) {
        return Err(Error::BillingLimitExceeded);
    }

    Ok(())
}

const EVENTS_SLOT: usize = SCOPED_CHECKS.len();

fn slot_resource(slot: usize) -> &'static QuotaResource {
    const EVENTS: &QuotaResource = &QuotaResource::Events;
    SCOPED_CHECKS
        .get(slot)
        .map_or(EVENTS, |(resource, _)| resource)
}

fn quota_drop_slot(
    ev: &WrappedEvent,
    events_limited: bool,
    scoped_limited: &[bool; SCOPED_CHECKS.len()],
) -> Option<usize> {
    let info = EventInfo {
        name: ev.event_name(),
        has_product_tour_id: ev.has_property("product_tour_id"),
    };
    let Some(slot) = SCOPED_CHECKS
        .iter()
        .position(|(_, predicate)| predicate(info))
    else {
        return events_limited.then_some(EVENTS_SLOT);
    };
    // Wallet-billed: skip llm_events but not the events quota, like the legacy AI and OTel paths.
    if SCOPED_CHECKS[slot].0 == QuotaResource::LLMEvents && ev.is_gateway_verified {
        return events_limited.then_some(EVENTS_SLOT);
    }
    scoped_limited[slot].then_some(slot)
}

fn over_quota_details(resource: &QuotaResource) -> &'static str {
    match resource {
        QuotaResource::Exceptions => "exceptions_over_quota",
        QuotaResource::Surveys => "survey_responses_over_quota",
        QuotaResource::LLMEvents => "llm_events_over_quota",
        QuotaResource::Events => "events_over_quota",
        _ => "over_quota",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::v1::types::Destination;
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

    use crate::config::EnvelopeCompression;

    use crate::config::{CaptureMode, Config, OutputsConfig};
    use crate::producers::ProducerName;
    use crate::v1::analytics::types::{Event, Options, RawOptions};

    fn test_config() -> Config {
        Config {
            print_sink: false,
            noop_sink: false,
            address: "127.0.0.1:0".parse().unwrap(),
            redis_url: "redis://localhost:6379/".to_string(),
            redis_response_timeout_ms: 100,
            redis_connection_timeout_ms: 5000,
            global_rate_limit_enabled: false,
            global_rate_limit_dry_run: false,
            global_rate_limit_window_interval_secs: 60,
            global_rate_limit_sync_interval_secs: 15,
            global_rate_limit_tick_interval_ms: 1000,
            global_rate_limit_token_distinctid_threshold: 10_000,
            global_rate_limit_token_distinctid_overrides_csv: None,
            global_rate_limit_token_distinctid_local_cache_max_entries: 300_000,
            global_rate_limit_min_sync_floor: 0,
            global_rate_limit_max_sync_keys_per_tick: 20_000,
            global_rate_limit_max_keys_per_command: 2_000,
            global_rate_limit_max_concurrent_commands: 4,
            global_rate_limit_max_write_batch_entries: 200_000,
            global_rate_limit_max_pending_sync_entries: 200_000,
            global_rate_limit_local_cache_ttl_secs: 600,
            global_rate_limit_local_cache_idle_timeout_secs: 300,
            global_rate_limit_read_timeout_ms: 250,
            global_rate_limit_write_timeout_ms: 250,
            global_rate_limit_token_threshold: 300_000,
            global_rate_limit_token_overrides_csv: None,
            global_rate_limit_token_local_cache_max_entries: 300_000,
            global_rate_limit_redis_url: None,
            global_rate_limit_redis_shards: 1,
            global_rate_limit_redis_shard_1_url: None,
            global_rate_limit_redis_shard_1_reader_url: None,
            global_rate_limit_redis_reader_url: None,
            global_rate_limit_max_read_outage_secs: None,
            global_rate_limit_redis_response_timeout_ms: None,
            global_rate_limit_redis_connection_timeout_ms: None,
            global_rate_limit_custom_threshold_key: None,
            global_rate_limit_custom_threshold_refresh_secs: 60,
            event_restrictions_enabled: false,
            event_restrictions_redis_url: None,
            event_restrictions_refresh_interval_secs: 30,
            event_restrictions_fail_open_after_secs: 300,
            overflow_enabled: false,
            ai_events_overflow_enabled: false,
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
            outputs: OutputsConfig {
                analytics_main_topic: "events_plugin_ingestion".to_string(),
                analytics_main_producer: ProducerName::Ingestion,
                analytics_overflow_topic: "events_plugin_ingestion_overflow".to_string(),
                analytics_overflow_producer: ProducerName::Ingestion,
                analytics_historical_topic: "events_plugin_ingestion_historical".to_string(),
                analytics_historical_producer: ProducerName::Ingestion,
                session_replay_main_topic: "events_plugin_ingestion".to_string(),
                session_replay_main_producer: ProducerName::Ingestion,
                session_replay_overflow_topic: "session_recording_snapshot_item_overflow"
                    .to_string(),
                session_replay_overflow_producer: ProducerName::Ingestion,
                heatmaps_topic: "events_plugin_ingestion".to_string(),
                heatmaps_producer: ProducerName::Ingestion,
                client_warnings_topic: "events_plugin_ingestion".to_string(),
                client_warnings_producer: ProducerName::Ingestion,
                error_tracking_topic: "error_tracking_events".to_string(),
                error_tracking_producer: ProducerName::Ingestion,
                dlq_topic: "events_plugin_ingestion_dlq".to_string(),
                dlq_producer: ProducerName::Ingestion,
                ai_main_topic: "events_plugin_ingestion_ai".to_string(),
                ai_main_producer: ProducerName::Ingestion,
                ai_overflow_topic: "events_plugin_ingestion_ai_overflow".to_string(),
                ai_overflow_producer: ProducerName::Ingestion,
                custom_producer: ProducerName::Ingestion,
            },
            replay_envelope_compression: EnvelopeCompression::None,
            outputs_completeness_check_enabled: true,
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
            ai_max_event_bytes: 8_388_608,
            ai_gateway_signing_secret: None,
            http1_header_read_timeout_ms: Some(5000),
            body_chunk_read_timeout_ms: None,
            body_read_chunk_size_kb: 256,
            continuous_profiling: ContinuousProfilingConfig::default(),
            capture_v1_max_compressed_body_bytes: None,
            capture_v1_max_decompressed_body_bytes: None,
            capture_v1_scatter_gather_min_batch: 8,
            capture_v1_legacy_property_splice: true,
            capture_ingestion_warnings_enabled: false,
            capture_ingestion_warnings_kafka_queue_mib: 16,
            capture_ingestion_warnings_kafka_message_max_bytes: 1048576,
            capture_ingestion_warnings_kafka_topic: String::new(),
            capture_ingestion_warnings_kafka_hosts: String::new(),
            capture_ingestion_warnings_kafka_tls: false,
            ai_byte_limit_per_second: 0,
            ai_byte_limit_overrides_csv: None,
            ai_byte_limit_dry_run: false,
            ai_byte_limit_window_interval_secs: None,
            ai_byte_limit_local_cache_max_entries: 300_000,
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
        let uuid = Uuid::now_v7();
        WrappedEvent {
            event: Event {
                event: name.to_string(),
                uuid: uuid.to_string(),
                distinct_id: "test_user".to_string(),
                timestamp: "2026-03-26T12:00:00.000Z".to_string(),
                session_id: None,
                window_id: None,
                options: match product_tour_id {
                    Some(id) => RawOptions(serde_json::json!({"product_tour_id": id})),
                    None => RawOptions::default(),
                },
                properties: RawValue::from_string("{}".to_owned()).unwrap(),
            },
            uuid,
            options: Options {
                cookieless_mode: None,
                disable_skew_correction: None,
                product_tour_id: product_tour_id.map(String::from),
                process_person_profile: None,
            },
            adjusted_timestamp: Some(
                DateTime::parse_from_rfc3339("2026-03-26T12:00:00Z")
                    .unwrap()
                    .with_timezone(&Utc),
            ),
            result: EventResult::Ok,
            details: None,
            destination: Destination::AnalyticsMain,
            force_disable_person_processing: false,
            spread_partitions: false,
            is_gateway_verified: false,
        }
    }

    fn make_verified_event(name: &str) -> WrappedEvent {
        let mut ev = make_event(name, None);
        ev.is_gateway_verified = true;
        ev
    }

    fn ok_event_names(events: &[WrappedEvent]) -> Vec<&str> {
        let mut names: Vec<&str> = events
            .iter()
            .filter(|e| e.result == EventResult::Ok)
            .map(|e| e.event.event.as_str())
            .collect();
        names.sort();
        names
    }

    fn quota_dropped_event_names(events: &[WrappedEvent]) -> Vec<&str> {
        let mut names: Vec<&str> = events
            .iter()
            .filter(|e| e.result == EventResult::Drop)
            .map(|e| e.event.event.as_str())
            .collect();
        names.sort();
        names
    }

    /// Panics on zero or multiple matches — callers rely on uniqueness.
    fn find_unique_by_name<'a>(events: &'a [WrappedEvent], name: &str) -> &'a WrappedEvent {
        let matches: Vec<&WrappedEvent> = events.iter().filter(|e| e.event.event == name).collect();
        assert_eq!(
            matches.len(),
            1,
            "expected exactly one event named {name:?}, found {}",
            matches.len()
        );
        matches[0]
    }

    // -----------------------------------------------------------------------
    // No limits
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn no_limits_all_events_pass() {
        let limiter = build_limiter("tok", false, &[]).await;
        let mut events = vec![
            make_event("$pageview", None),
            make_event("$exception", None),
            make_event("survey sent", None),
            make_event("$ai_generation", None),
        ];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());
        assert_eq!(ok_event_names(&events).len(), 4);
        assert!(quota_dropped_event_names(&events).is_empty());
    }

    // -----------------------------------------------------------------------
    // Global limit
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn global_limit_keeps_scoped_events_and_drops_the_rest() {
        let limiter = build_limiter("tok", true, &[]).await;
        let mut events = vec![
            make_event("$pageview", None),
            make_event("$exception", None),
            make_event("survey sent", None),
            make_event("$ai_generation", None),
        ];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        assert_eq!(
            ok_event_names(&events),
            vec!["$ai_generation", "$exception", "survey sent"]
        );
        let pv = find_unique_by_name(&events, "$pageview");
        assert_eq!(pv.result, EventResult::Drop);
        assert_eq!(pv.details, Some("events_over_quota"));
    }

    #[tokio::test]
    async fn global_limit_returns_error_when_no_event_remains() {
        let limiter = build_limiter("tok", true, &[]).await;
        let bad = make_event("bad_event", None);
        let bad_uuid = bad.uuid;
        let mut events = vec![make_event("$pageview", None), bad];
        // Pre-mark one event as Drop (e.g. from validation)
        let bad_ev = events.iter_mut().find(|e| e.uuid == bad_uuid).unwrap();
        bad_ev.result = EventResult::Drop;
        bad_ev.details = Some("invalid_event_name");

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(matches!(result, Err(Error::BillingLimitExceeded)));

        assert_eq!(
            find_unique_by_name(&events, "$pageview").details,
            Some("events_over_quota")
        );
        let bad_ev = events.iter().find(|e| e.uuid == bad_uuid).unwrap();
        assert_eq!(bad_ev.result, EventResult::Drop);
        assert_eq!(bad_ev.details, Some("invalid_event_name"));
    }

    #[tokio::test]
    async fn global_limit_different_token_not_affected() {
        let limiter = build_limiter("limited_tok", true, &[]).await;
        let mut events = vec![
            make_event("$pageview", None),
            make_event("$exception", None),
        ];

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
        let mut events = vec![
            make_event("$pageview", None),
            make_event("$exception", None),
            make_event("survey sent", None),
            make_event("$exception", None),
        ];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        let mut ok = ok_event_names(&events);
        ok.sort();
        assert_eq!(ok, vec!["$pageview", "survey sent"]);
        assert_eq!(
            quota_dropped_event_names(&events),
            vec!["$exception", "$exception"]
        );
        for ev in events.iter().filter(|e| e.result == EventResult::Drop) {
            assert_eq!(ev.details, Some("exceptions_over_quota"));
        }
    }

    #[tokio::test]
    async fn exception_limit_all_exceptions_returns_error() {
        let limiter = build_limiter("tok", false, &[QuotaResource::Exceptions]).await;
        let mut events = vec![
            make_event("$exception", None),
            make_event("$exception", None),
        ];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_err());
        assert_eq!(quota_dropped_event_names(&events).len(), 2);
    }

    // -----------------------------------------------------------------------
    // Survey scoped limit
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn survey_limit_marks_only_survey_events() {
        let limiter = build_limiter("tok", false, &[QuotaResource::Surveys]).await;
        let mut events = vec![
            make_event("$pageview", None),
            make_event("survey sent", None),
            make_event("survey shown", None),
            make_event("survey dismissed", None),
            make_event("$exception", None),
        ];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        let mut ok = ok_event_names(&events);
        ok.sort();
        assert_eq!(ok, vec!["$exception", "$pageview"]);
        assert_eq!(quota_dropped_event_names(&events).len(), 3);
        for ev in events.iter().filter(|e| e.result == EventResult::Drop) {
            assert_eq!(ev.details, Some("survey_responses_over_quota"));
        }
    }

    #[tokio::test]
    async fn survey_limit_excludes_product_tour_events() {
        let limiter = build_limiter("tok", false, &[QuotaResource::Surveys]).await;
        let tour_ev = make_event("survey sent", Some("tour-123"));
        let tour_uuid = tour_ev.uuid;
        let mut events = vec![make_event("survey sent", None), tour_ev];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        // Product tour survey → Ok, regular survey → Drop (quota exceeded)
        assert_eq!(
            events.iter().find(|e| e.uuid == tour_uuid).unwrap().result,
            EventResult::Ok
        );
        assert_eq!(quota_dropped_event_names(&events).len(), 1);
    }

    // -----------------------------------------------------------------------
    // LLM scoped limit
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn llm_limit_marks_only_ai_events() {
        let limiter = build_limiter("tok", false, &[QuotaResource::LLMEvents]).await;
        let mut events = vec![
            make_event("$ai_generation", None),
            make_event("$ai_span", None),
            make_event("$pageview", None),
            make_event("$ai_trace", None),
        ];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        assert_eq!(ok_event_names(&events), vec!["$pageview"]);
        assert_eq!(quota_dropped_event_names(&events).len(), 3);
        for ev in events.iter().filter(|e| e.result == EventResult::Drop) {
            assert_eq!(ev.details, Some("llm_events_over_quota"));
        }
    }

    #[tokio::test]
    async fn llm_limit_ignores_non_ai_prefix() {
        let limiter = build_limiter("tok", false, &[QuotaResource::LLMEvents]).await;
        let mut events = vec![
            make_event("$ai_generation", None),
            make_event("$ainotcounted", None), // no underscore
            make_event("ai_generation", None), // no $ prefix
        ];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        let mut ok = ok_event_names(&events);
        ok.sort();
        assert_eq!(ok, vec!["$ainotcounted", "ai_generation"]);
        assert_eq!(quota_dropped_event_names(&events), vec!["$ai_generation"]);
    }

    #[tokio::test]
    async fn llm_limit_exempts_gateway_verified_events() {
        let limiter = build_limiter("tok", false, &[QuotaResource::LLMEvents]).await;
        let verified = make_verified_event("$ai_generation");
        let verified_uuid = verified.uuid;
        let mut events = vec![verified, make_event("$ai_generation", None)];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        // Gateway-verified event survives (wallet-billed); the plain $ai_ one drops.
        let verified = events.iter().find(|e| e.uuid == verified_uuid).unwrap();
        assert_eq!(verified.result, EventResult::Ok);
        assert_eq!(verified.details, None);
        assert_eq!(quota_dropped_event_names(&events), vec!["$ai_generation"]);
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
        let mut events = vec![
            make_event("$exception", None),
            make_event("survey sent", None),
            make_event("$ai_generation", None),
            make_event("$pageview", None),
        ];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        assert_eq!(ok_event_names(&events), vec!["$pageview"]);
        assert_eq!(quota_dropped_event_names(&events).len(), 3);
        assert_eq!(
            find_unique_by_name(&events, "$exception").details,
            Some("exceptions_over_quota")
        );
        assert_eq!(
            find_unique_by_name(&events, "survey sent").details,
            Some("survey_responses_over_quota")
        );
        assert_eq!(
            find_unique_by_name(&events, "$ai_generation").details,
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
        let mut events = vec![
            make_event("$exception", None),
            make_event("survey sent", None),
            make_event("$ai_generation", None),
        ];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_err());
        assert!(ok_event_names(&events).is_empty());
    }

    // -----------------------------------------------------------------------
    // Global + scoped limits interaction
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn global_and_scoped_limits_drop_everything_and_return_error() {
        let limiter = build_limiter("tok", true, &[QuotaResource::Exceptions]).await;
        let mut events = vec![
            make_event("$pageview", None),
            make_event("$exception", None),
        ];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(matches!(result, Err(Error::BillingLimitExceeded)));

        assert_eq!(
            find_unique_by_name(&events, "$pageview").details,
            Some("events_over_quota")
        );
        assert_eq!(
            find_unique_by_name(&events, "$exception").details,
            Some("exceptions_over_quota")
        );
    }

    #[tokio::test]
    async fn global_limit_applies_each_scoped_quota_on_its_own() {
        let limiter = build_limiter("tok", true, &[QuotaResource::LLMEvents]).await;
        let mut events = vec![
            make_event("$pageview", None),
            make_event("$ai_generation", None),
            make_event("survey sent", None),
            make_event("$exception", None),
        ];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        assert_eq!(ok_event_names(&events), vec!["$exception", "survey sent"]);
        assert_eq!(
            find_unique_by_name(&events, "$pageview").details,
            Some("events_over_quota")
        );
        assert_eq!(
            find_unique_by_name(&events, "$ai_generation").details,
            Some("llm_events_over_quota")
        );
    }

    #[tokio::test]
    async fn global_limit_drops_product_tour_survey_events() {
        // Product tours are not survey responses, so only the events quota applies.
        let limiter = build_limiter("tok", true, &[]).await;
        let tour = make_event("survey sent", Some("tour-123"));
        let tour_uuid = tour.uuid;
        let mut events = vec![make_event("survey sent", None), tour];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        let tour = events.iter().find(|e| e.uuid == tour_uuid).unwrap();
        assert_eq!(tour.result, EventResult::Drop);
        assert_eq!(tour.details, Some("events_over_quota"));
        assert_eq!(ok_event_names(&events), vec!["survey sent"]);
    }

    #[tokio::test]
    async fn global_limit_drops_gateway_verified_events() {
        let limiter = build_limiter("tok", true, &[]).await;
        let verified = make_verified_event("$ai_generation");
        let verified_uuid = verified.uuid;
        let mut events = vec![verified, make_event("$ai_generation", None)];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());

        let verified = events.iter().find(|e| e.uuid == verified_uuid).unwrap();
        assert_eq!(verified.result, EventResult::Drop);
        assert_eq!(verified.details, Some("events_over_quota"));
        assert_eq!(ok_event_names(&events), vec!["$ai_generation"]);
    }

    #[tokio::test]
    async fn global_and_llm_limits_drop_verified_and_plain_ai_events() {
        let limiter = build_limiter("tok", true, &[QuotaResource::LLMEvents]).await;
        let verified = make_verified_event("$ai_generation");
        let verified_uuid = verified.uuid;
        let mut events = vec![verified, make_event("$ai_span", None)];

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(matches!(result, Err(Error::BillingLimitExceeded)));

        let verified = events.iter().find(|e| e.uuid == verified_uuid).unwrap();
        assert_eq!(verified.details, Some("events_over_quota"));
        assert_eq!(
            find_unique_by_name(&events, "$ai_span").details,
            Some("llm_events_over_quota")
        );
    }

    #[tokio::test]
    async fn quota_counter_counts_only_events_each_quota_dropped() {
        use metrics_util::debugging::{DebugValue, DebuggingRecorder};

        let limiter = build_limiter("tok", true, &[QuotaResource::Exceptions]).await;
        let pre_dropped = make_event("bad_event", None);
        let pre_dropped_uuid = pre_dropped.uuid;
        let mut events = vec![
            make_event("$pageview", None),
            make_event("click", None),
            make_event("$exception", None),
            make_event("survey sent", None),
            pre_dropped,
        ];
        events
            .iter_mut()
            .find(|e| e.uuid == pre_dropped_uuid)
            .unwrap()
            .result = EventResult::Drop;

        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let result = {
            let _guard = metrics::set_default_local_recorder(&recorder);
            apply_quota_limits(&limiter, "tok", &mut events).await
        };
        assert!(result.is_ok());

        let counts: std::collections::HashMap<String, u64> = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter(|(key, _, _, _)| key.key().name() == CAPTURE_V1_EVENTS_QUOTA_LIMITED)
            .filter_map(|(key, _, _, value)| {
                let resource = key
                    .key()
                    .labels()
                    .find(|l| l.key() == "resource")?
                    .value()
                    .to_string();
                match value {
                    DebugValue::Counter(v) => Some((resource, v)),
                    _ => None,
                }
            })
            .collect();
        // The pre-dropped event and the kept survey are not counted.
        assert_eq!(
            counts,
            std::collections::HashMap::from([
                ("events".to_string(), 2),
                ("exceptions".to_string(), 1),
            ])
        );
    }

    // -----------------------------------------------------------------------
    // Pre-existing non-Ok events + post-check
    // -----------------------------------------------------------------------

    #[tokio::test]
    async fn pre_existing_drop_events_counted_in_post_check() {
        // No global limit, but exceptions limited
        let limiter = build_limiter("tok", false, &[QuotaResource::Exceptions]).await;
        let pv = make_event("$pageview", None);
        let pv_uuid = pv.uuid;
        let mut events = vec![make_event("$exception", None), pv];
        // Pre-mark pageview as Drop from a prior validation step
        let pv_ev = events.iter_mut().find(|e| e.uuid == pv_uuid).unwrap();
        pv_ev.result = EventResult::Drop;

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        // $exception → Drop (quota), $pageview → already Drop → all non-Ok → error
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn mixed_pre_existing_and_scoped_still_ok_if_some_remain() {
        let limiter = build_limiter("tok", false, &[QuotaResource::Exceptions]).await;
        let pv = make_event("$pageview", None);
        let pv_uuid = pv.uuid;
        let mut events = vec![
            make_event("$exception", None),
            pv,
            make_event("click", None),
        ];
        events
            .iter_mut()
            .find(|e| e.uuid == pv_uuid)
            .unwrap()
            .result = EventResult::Drop;

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
        let mut events: Vec<WrappedEvent> = Vec::new();

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn empty_batch_returns_ok_when_not_limited() {
        let limiter = build_limiter("tok", false, &[]).await;
        let mut events: Vec<WrappedEvent> = Vec::new();

        let result = apply_quota_limits(&limiter, "tok", &mut events).await;
        assert!(result.is_ok());
    }
}
