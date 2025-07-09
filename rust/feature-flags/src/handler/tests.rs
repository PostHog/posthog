#[cfg(test)]
use crate::{
    api::{
        errors::FlagError,
        types::{
            Compression, FlagDetails, FlagDetailsMetadata, FlagEvaluationReason, FlagValue,
            FlagsQueryParams, LegacyFlagsResponse,
        },
    },
    cohorts::cohort_cache_manager::CohortCacheManager,
    config::Config,
    flags::{
        flag_analytics::SURVEY_TARGETING_FLAG_PREFIX,
        flag_models::{FeatureFlag, FeatureFlagList, FlagFilters, FlagPropertyGroup},
        flag_service::FlagService,
    },
    handler::{
        decoding, evaluation::evaluate_feature_flags, flags::fetch_and_filter, properties,
        FeatureFlagEvaluationContext,
    },
    properties::property_models::{OperatorType, PropertyFilter, PropertyType},
    utils::test_utils::{
        insert_flags_for_team_in_redis, insert_new_team_in_pg, insert_person_for_team_in_pg,
        setup_pg_reader_client, setup_pg_writer_client, setup_redis_client,
    },
};
use axum::http::HeaderMap;
use base64::{engine::general_purpose, Engine as _};
use bytes::Bytes;
use common_database::Client;
use common_geoip::GeoIpClient;
use reqwest::header::CONTENT_TYPE;
use serde_json::{json, Value};
use std::net::{Ipv4Addr, Ipv6Addr};
use std::{collections::HashMap, net::IpAddr, sync::Arc};
use uuid::Uuid;

fn create_test_geoip_service() -> GeoIpClient {
    let config = Config::default_test_config();
    GeoIpClient::new(config.get_maxmind_db_path())
        .expect("Failed to create GeoIpService for testing")
}

#[test]
fn test_geoip_enabled_with_person_properties() {
    let geoip_service = create_test_geoip_service();

    let mut person_props = HashMap::new();
    person_props.insert("name".to_string(), Value::String("John".to_string()));

    let result = properties::get_person_property_overrides(
        false,
        Some(person_props),
        &IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)), // Google's public DNS, should be in the US
        &geoip_service,
    );

    assert!(result.is_some());
    let result = result.unwrap();
    assert!(result.len() > 1);
    assert_eq!(result.get("name"), Some(&Value::String("John".to_string())));
    assert!(result.contains_key("$geoip_country_name"));
}

#[test]
fn test_geoip_enabled_without_person_properties() {
    let geoip_service = create_test_geoip_service();

    let result = properties::get_person_property_overrides(
        false,
        None,
        &IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)), // Google's public DNS, should be in the US
        &geoip_service,
    );

    assert!(result.is_some());
    let result = result.unwrap();
    assert!(!result.is_empty());
    assert!(result.contains_key("$geoip_country_name"));
}

#[test]
fn test_geoip_disabled_with_person_properties() {
    let geoip_service = create_test_geoip_service();

    let mut person_props = HashMap::new();
    person_props.insert("name".to_string(), Value::String("John".to_string()));

    let result = properties::get_person_property_overrides(
        true,
        Some(person_props),
        &IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)),
        &geoip_service,
    );

    assert!(result.is_some());
    let result = result.unwrap();
    assert_eq!(result.len(), 1);
    assert_eq!(result.get("name"), Some(&Value::String("John".to_string())));
}

#[test]
fn test_geoip_disabled_without_person_properties() {
    let geoip_service = create_test_geoip_service();

    let result = properties::get_person_property_overrides(
        true,
        None,
        &IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)),
        &geoip_service,
    );

    assert!(result.is_none());
}

#[test]
fn test_geoip_enabled_local_ip() {
    let geoip_service = create_test_geoip_service();

    let result = properties::get_person_property_overrides(
        true,
        None,
        &IpAddr::V4(Ipv4Addr::new(127, 0, 0, 1)),
        &geoip_service,
    );

    assert!(result.is_none());
}

#[tokio::test]
async fn test_evaluate_feature_flags() {
    let reader: Arc<dyn Client + Send + Sync> = setup_pg_reader_client(None).await;
    let writer: Arc<dyn Client + Send + Sync> = setup_pg_writer_client(None).await;
    let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
    let team = insert_new_team_in_pg(reader.clone(), None)
        .await
        .expect("Failed to insert team in pg");
    let flag = FeatureFlag {
        name: Some("Test Flag".to_string()),
        id: 1,
        key: "test_flag".to_string(),
        active: true,
        deleted: false,
        team_id: team.id,
        filters: FlagFilters {
            groups: vec![FlagPropertyGroup {
                properties: Some(vec![PropertyFilter {
                    key: "country".to_string(),
                    value: Some(json!("US")),
                    operator: Some(OperatorType::Exact),
                    prop_type: PropertyType::Person,
                    group_type_index: None,
                    negation: None,
                }]),
                rollout_percentage: Some(100.0), // Set to 100% to ensure it's always on
                variant: None,
            }],
            multivariate: None,
            aggregation_group_type_index: None,
            payloads: None,
            super_groups: None,
            holdout_groups: None,
        },
        ensure_experience_continuity: false,
        version: Some(1),
    };

    let feature_flag_list = FeatureFlagList { flags: vec![flag] };

    let mut person_properties = HashMap::new();
    person_properties.insert("country".to_string(), json!("US"));

    let evaluation_context = FeatureFlagEvaluationContext {
        team_id: team.id,
        project_id: team.project_id,
        distinct_id: "user123".to_string(),
        feature_flags: feature_flag_list,
        reader,
        writer,
        cohort_cache,
        person_property_overrides: Some(person_properties),
        group_property_overrides: None,
        groups: None,
        hash_key_override: None,
        flag_keys: None,
    };

    let request_id = Uuid::new_v4();

    let result = evaluate_feature_flags(evaluation_context, request_id).await;

    assert!(!result.errors_while_computing_flags);
    assert!(result.flags.contains_key("test_flag"));
    assert!(result.flags["test_flag"].enabled);
    let legacy_response = LegacyFlagsResponse::from_response(result);
    assert!(!legacy_response.errors_while_computing_flags);
    assert!(legacy_response.feature_flags.contains_key("test_flag"));
    assert_eq!(
        legacy_response.feature_flags["test_flag"],
        FlagValue::Boolean(true)
    );
}

#[tokio::test]
async fn test_evaluate_feature_flags_with_errors() {
    // Set up test dependencies
    let reader: Arc<dyn Client + Send + Sync> = setup_pg_reader_client(None).await;
    let writer: Arc<dyn Client + Send + Sync> = setup_pg_writer_client(None).await;
    let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));

    let team = insert_new_team_in_pg(reader.clone(), None)
        .await
        .expect("Failed to insert team in pg");

    insert_person_for_team_in_pg(reader.clone(), team.id, "user123".to_string(), None)
        .await
        .expect("Failed to insert person");

    // Create a feature flag with conditions that will cause an error
    let flags = vec![FeatureFlag {
        name: Some("Error Flag".to_string()),
        id: 1,
        key: "error-flag".to_string(),
        active: true,
        deleted: false,
        team_id: team.id,
        filters: FlagFilters {
            groups: vec![FlagPropertyGroup {
                // Reference a non-existent cohort
                properties: Some(vec![PropertyFilter {
                    key: "id".to_string(),
                    value: Some(json!(999999999)), // Very large cohort ID that doesn't exist
                    operator: None,
                    prop_type: PropertyType::Cohort,
                    group_type_index: None,
                    negation: None,
                }]),
                rollout_percentage: Some(100.0), // Set to 100% to ensure it's always on
                variant: None,
            }],
            multivariate: None,
            aggregation_group_type_index: None,
            payloads: None,
            super_groups: None,
            holdout_groups: None,
        },
        ensure_experience_continuity: false,
        version: Some(1),
    }];

    let feature_flag_list = FeatureFlagList { flags };

    // Set up evaluation context
    let evaluation_context = FeatureFlagEvaluationContext {
        team_id: team.id,
        project_id: team.project_id,
        distinct_id: "user123".to_string(),
        feature_flags: feature_flag_list,
        reader,
        writer,
        cohort_cache,
        person_property_overrides: Some(HashMap::new()),
        group_property_overrides: None,
        groups: None,
        hash_key_override: None,
        flag_keys: None,
    };

    let request_id = Uuid::new_v4();

    let result = evaluate_feature_flags(evaluation_context, request_id).await;
    let error_flag = result.flags.get("error-flag");
    assert!(error_flag.is_some());
    assert_eq!(
        error_flag.unwrap(),
        &FlagDetails {
            key: "error-flag".to_string(),
            enabled: false,
            variant: None,
            reason: FlagEvaluationReason {
                code: "dependency_not_found_cohort".to_string(),
                condition_index: None,
                description: None,
            },
            metadata: FlagDetailsMetadata {
                id: 1,
                version: 1,
                description: None,
                payload: None,
            },
        }
    );
    let legacy_response = LegacyFlagsResponse::from_response(result);
    assert!(legacy_response.errors_while_computing_flags);
}

#[test]
fn test_decode_request() {
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_TYPE, "application/json".parse().unwrap());
    let body = Bytes::from(r#"{"token": "test_token", "distinct_id": "user123"}"#);
    let meta = FlagsQueryParams::default();

    let result = decoding::decode_request(&headers, body, &meta);

    assert!(result.is_ok());
    let request = result.unwrap();
    assert_eq!(request.token, Some("test_token".to_string()));
    assert_eq!(request.distinct_id, Some("user123".to_string()));
}

#[test]
fn test_decode_request_unsupported_content_encoding() {
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_TYPE, "application/json".parse().unwrap());
    let body = Bytes::from_static(b"{\"token\": \"test_token\", \"distinct_id\": \"user123\"}");
    let meta = FlagsQueryParams {
        compression: Some(Compression::Unsupported),
        ..Default::default()
    };

    let result = decoding::decode_request(&headers, body, &meta);
    assert!(matches!(result, Err(FlagError::RequestDecodingError(_))));
}

#[test]
fn test_decode_request_invalid_base64() {
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_TYPE, "application/json".parse().unwrap());
    let body = Bytes::from_static(b"invalid_base64==");
    let meta = FlagsQueryParams {
        compression: Some(Compression::Base64),
        ..Default::default()
    };

    let result = decoding::decode_request(&headers, body, &meta);
    assert!(matches!(result, Err(FlagError::RequestDecodingError(_))));
}

#[test]
fn test_compression_as_str() {
    assert_eq!(Compression::Gzip.as_str(), "gzip");
    assert_eq!(Compression::Unsupported.as_str(), "unsupported");
}

#[test]
fn test_get_person_property_overrides_ipv4() {
    let geoip_service = create_test_geoip_service();
    let result = properties::get_person_property_overrides(
        false,
        Some(HashMap::new()),
        &IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)),
        &geoip_service,
    );
    assert!(result.is_some());
    let props = result.unwrap();
    assert!(props.contains_key("$geoip_country_name"));
}

#[test]
fn test_get_person_property_overrides_ipv6() {
    let geoip_service = create_test_geoip_service();
    let result = properties::get_person_property_overrides(
        false,
        Some(HashMap::new()),
        &IpAddr::V6(Ipv6Addr::new(0x2001, 0x4860, 0x4860, 0, 0, 0, 0, 0x8888)),
        &geoip_service,
    );
    assert!(result.is_some());
    let props = result.unwrap();
    assert!(props.contains_key("$geoip_country_name"));
}

#[test]
fn test_decode_request_unsupported_content_type() {
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_TYPE, "text/plain".parse().unwrap());
    let body = Bytes::from_static(b"test");
    let meta = FlagsQueryParams::default();

    let result = decoding::decode_request(&headers, body, &meta);
    assert!(matches!(result, Err(FlagError::RequestDecodingError(_))));
}

#[test]
fn test_decode_request_malformed_json() {
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_TYPE, "application/json".parse().unwrap());
    let body = Bytes::from_static(b"{invalid json}");
    let meta = FlagsQueryParams::default();

    let result = decoding::decode_request(&headers, body, &meta);
    assert!(result.is_err(), "Expected an error, but got Ok");
}

#[test]
fn test_decode_request_form_urlencoded() {
    let mut headers = HeaderMap::new();
    headers.insert(
        CONTENT_TYPE,
        "application/x-www-form-urlencoded".parse().unwrap(),
    );
    let body =
        Bytes::from("data=eyJ0b2tlbiI6InRlc3RfdG9rZW4iLCJkaXN0aW5jdF9pZCI6InVzZXIxMjMifQ%3D%3D");
    let meta = FlagsQueryParams::default();

    let result = decoding::decode_request(&headers, body, &meta);
    assert!(result.is_ok());
    let request = result.unwrap();
    assert_eq!(request.token, Some("test_token".to_string()));
    assert_eq!(request.distinct_id, Some("user123".to_string()));
}

#[test]
fn test_decode_form_data_kludges() {
    // see https://github.com/PostHog/posthog/blob/master/posthog/utils.py#L686-L708
    // for the list of kludges we need to support
    let test_cases = vec![
        // No padding needed
        ("data=eyJ0b2tlbiI6InRlc3QifQ==", true),
        // Missing one padding character
        ("data=eyJ0b2tlbiI6InRlc3QifQ=", true),
        // Missing two padding characters
        ("data=eyJ0b2tlbiI6InRlc3QifQ", true),
        // With whitespace
        ("data=eyJ0b2tlbiI6I nRlc3QifQ==", true),
        // Missing data= prefix
        ("eyJ0b2tlbiI6InRlc3QifQ==", true),
    ];

    for (input, should_succeed) in test_cases {
        let body = Bytes::from(input);
        let result = decoding::decode_form_data(body, None);

        if should_succeed {
            assert!(result.is_ok(), "Failed to decode: {}", input);
            let request = result.unwrap();
            if input.contains("bio") {
                // Verify we can handle newlines in the decoded JSON
                let person_properties = request.person_properties.unwrap();
                assert_eq!(
                    person_properties.get("bio").unwrap().as_str().unwrap(),
                    "line1\nline2"
                );
            } else {
                assert_eq!(request.token, Some("test".to_string()));
            }
        } else {
            assert!(result.is_err(), "Expected error for input: {}", input);
        }
    }
}

#[test]
fn test_handle_unencoded_form_data_with_emojis() {
    let json = json!({
        "token": "test_token",
        "distinct_id": "test_id",
        "person_properties": {
            "bio": "Hello 👋 World 🌍"
        }
    });

    let base64 = general_purpose::STANDARD.encode(json.to_string());
    let body = Bytes::from(format!("data={}", base64));

    let result = decoding::decode_form_data(body, None);
    assert!(result.is_ok(), "Failed to decode emoji content");

    let request = result.unwrap();
    assert_eq!(request.token, Some("test_token".to_string()));
    assert_eq!(request.distinct_id, Some("test_id".to_string()));

    let person_properties = request.person_properties.unwrap();
    assert_eq!(
        person_properties.get("bio").unwrap(),
        &Value::String("Hello 👋 World 🌍".to_string())
    );
}

#[test]
fn test_decode_base64_encoded_form_data_with_emojis() {
    let json = json!({
        "token": "test_token",
        "distinct_id": "test_id",
        "person_properties": {
            "bio": "Hello 👋 World 🌍"
        }
    });

    let base64 = general_purpose::STANDARD.encode(json.to_string());
    let body = Bytes::from(format!("data={}", base64));

    let result = decoding::decode_form_data(body, Some(Compression::Base64));
    assert!(result.is_ok(), "Failed to decode emoji content");

    let request = result.unwrap();
    assert_eq!(request.token, Some("test_token".to_string()));
    assert_eq!(request.distinct_id, Some("test_id".to_string()));

    let person_properties = request.person_properties.unwrap();
    assert_eq!(
        person_properties.get("bio").unwrap(),
        &Value::String("Hello 👋 World 🌍".to_string())
    );
}

#[test]
fn test_decode_form_data_compression_types() {
    let input = "data=eyJ0b2tlbiI6InRlc3QifQ==";
    let body = Bytes::from(input);

    // Base64 compression should work
    let result = decoding::decode_form_data(body.clone(), Some(Compression::Base64));
    assert!(result.is_ok());

    // No compression should work
    let result = decoding::decode_form_data(body.clone(), None);
    assert!(result.is_ok());

    // Gzip compression should fail
    let result = decoding::decode_form_data(body.clone(), Some(Compression::Gzip));
    assert!(matches!(
        result,
        Err(FlagError::RequestDecodingError(msg)) if msg.contains("not supported")
    ));

    // Unsupported compression should fail
    let result = decoding::decode_form_data(body, Some(Compression::Unsupported));
    assert!(matches!(
        result,
        Err(FlagError::RequestDecodingError(msg)) if msg.contains("Unsupported")
    ));
}

#[test]
fn test_decode_form_data_malformed_input() {
    let test_cases = vec![
        // Invalid base64
        "data=!@#$%",
        // Valid base64 but invalid JSON
        "data=eyd9", // encoded '{'
        // Empty input
        "data=",
    ];

    for input in test_cases {
        let body = Bytes::from(input);
        let result = decoding::decode_form_data(body, None);
        assert!(
            result.is_err(),
            "Expected error for malformed input: {}",
            input
        );
    }
}

#[test]
fn test_decode_form_data_real_world_payload() {
    let input = "data=eyJ0b2tlbiI6InNUTUZQc0ZoZFAxU3NnIiwiZGlzdGluY3RfaWQiOiIkcG9zdGhvZ19jb29raWVsZXNzIiwiZ3JvdXBzIjp7fSwicGVyc29uX3Byb3BlcnRpZXMiOnsiJGluaXRpYWxfcmVmZXJyZXIiOiIkZGlyZWN0IiwiJGluaXRpYWxfcmVmZXJyaW5nX2RvbWFpbiI6IiRkaXJlY3QiLCIkaW5pdGlhbF9jdXJyZW50X3VybCI6Imh0dHBzOi8vcG9zdGhvZy5jb20vIiwiJGluaXRpYWxfaG9zdCI6InBvc3Rob2cuY29tIiwiJGluaXRpYWxfcGF0aG5hbWUiOiIvIiwiJGluaXRpYWxfdXRtX3NvdXJjZSI6bnVsbCwiJGluaXRpYWxfdXRtX21lZGl1bSI6bnVsbCwiJGluaXRpYWxfdXRtX2NhbXBhaWduIjpudWxsLCIkaW5pdGlhbF91dG1fY29udGVudCI6bnVsbCwiJGluaXRpYWxfdXRtX3Rlcm0iOm51bGwsIiRpbml0aWFsX2dhZF9zb3VyY2UiOm51bGwsIiRpbml0aWFsX21jX2NpZCI6bnVsbCwiJGluaXRpYWxfZ2NsaWQiOm51bGwsIiRpbml0aWFsX2djbHNyYyI6bnVsbCwiJGluaXRpYWxfZGNsaWQiOm51bGwsIiRpbml0aWFsX2dicmFpZCI6bnVsbCwiJGluaXRpYWxfd2JyYWlkIjpudWxsLCIkaW5pdGlhbF9mYmNsaWQiOm51bGwsIiRpbml0aWFsX21zY2xraWQiOm51bGwsIiRpbml0aWFsX3R3Y2xpZCI6bnVsbCwiJGluaXRpYWxfbGlfZmF0X2lkIjpudWxsLCIkaW5pdGlhbF9pZ3NoaWQiOm51bGwsIiRpbml0aWFsX3R0Y2xpZCI6bnVsbCwiJGluaXRpYWxfcmR0X2NpZCI6bnVsbCwiJGluaXRpYWxfZXBpayI6bnVsbCwiJGluaXRpYWxfcWNsaWQiOm51bGwsIiRpbml0aWFsX3NjY2lkIjpudWxsLCIkaW5pdGlhbF9pcmNsaWQiOm51bGwsIiRpbml0aWFsX19reCI6bnVsbCwic3F1ZWFrRW1haWwiOiJsdWNhc0Bwb3N0aG9nLmNvbSIsInNxdWVha1VzZXJuYW1lIjoibHVjYXNAcG9zdGhvZy5jb20iLCJzcXVlYWtDcmVhdGVkQXQiOiIyMDI0LTEyLTE2VDE1OjU5OjAzLjQ1MVoiLCJzcXVlYWtQcm9maWxlSWQiOjMyMzg3LCJzcXVlYWtGaXJzdE5hbWUiOiJMdWNhcyIsInNxdWVha0xhc3ROYW1lIjoiRmFyaWEiLCJzcXVlYWtCaW9ncmFwaHkiOiJIb3cgZG8gcGVvcGxlIGRlc2NyaWJlIG1lOlxuXG4tIFNvbWV0aW1lcyBvYnNlc3NpdmVcbi0gT3Zlcmx5IG9wdGltaXN0aWNcbi0gTG9va3MgYXQgc2NyZWVucyBmb3Igd2F5IHRvbyBtYW55IGhvdXJzXG5cblllYWgsIEkgZ290IGFkZGljdGVkIHRvIGNvbXB1dGVycyBwcmV0dHkgeW91bmcgZHVlIHRvIFRpYmlhIGFuZCBSYWduYXJvayBPbmxpbmUg7aC97biFXG5cblRoYXQncyBhY3R1YWxseSBob3cgSSBsZWFybmVkIHRvIHNwZWFrIGVuZ2xpc2ghXG5cbkFueXdheSwgSSdtIEx1Y2FzLCBhIEJyYXppbGlhbiBlbmdpbmVlciB3aG8gbG92ZXMgY29kaW5nLCBhbmltYWxzLCBib29rcyBhbmQgbmF0dXJlLiBbTXkgZnVsbCBhYm91dCBwYWdlIGlzIGhlcmVdKGh0dHBzOi8vbHVjYXNmYXJpYS5kZXYvYWJvdXQpLlxuXG5JIGFsc28gW3B1Ymxpc2ggYSBuZXdzbGV0dGVyXShodHRwOi8vbmV3c2xldHRlci5uYWdyaW5nYS5kZXYvKSBmb3IgQnJhemlsaWFuIGVuZ2luZWVycywgaWYgeW91J3JlIGxvb2tpbmcgdG8gZ2V0IHNvbWUgY2FyZWVyIGluc2lnaHRzLlxuXG5JIGRvbid0IGtub3cgaG93IGRpZCBJIGdldCBoZXJlLCBidXQgSSdsbCB0cnkgbXkgYmVzdCB0byB0ZWFjaCB5b3UgZXZlcnl0aGluZyBJIGxlYXJuIGFsb25nIHRoZSB3YXkuIiwic3F1ZWFrQ29tcGFueSI6bnVsbCwic3F1ZWFrQ29tcGFueVJvbGUiOiJQcm9kdWN0IEVuZ2luZWVyIiwic3F1ZWFrR2l0aHViIjoiaHR0cHM6Ly9naXRodWIuY29tL2x1Y2FzaGVyaXF1ZXMiLCJzcXVlYWtMaW5rZWRJbiI6Imh0dHBzOi8vd3d3LmxpbmtlZGluLmNvbS9pbi9sdWNhcy1mYXJpYS8iLCJzcXVlYWtMb2NhdGlvbiI6IkJyYXppbCIsInNxdWVha1R3aXR0ZXIiOiJodHRwczovL3guY29tL29uZWx1Y2FzZmFyaWEiLCJzcXVlYWtXZWJzaXRlIjoiaHR0cHM6Ly9sdWNhc2ZhcmlhLmRldi8ifSwidGltZXpvbmUiOiJBbWVyaWNhL1Nhb19QYXVsbyJ9";
    let body = Bytes::from(input);
    let result = decoding::decode_form_data(body, Some(Compression::Base64));

    assert!(result.is_ok(), "Failed to decode real world payload");
    let request = result.unwrap();

    // Verify key fields from the decoded request
    assert_eq!(request.token, Some("sTMFPsFhdP1Ssg".to_string()));
    assert_eq!(request.distinct_id, Some("$posthog_cookieless".to_string()));

    // Verify we can handle the biography with newlines
    let person_properties = request
        .person_properties
        .expect("Missing person_properties");
    assert!(person_properties
        .get("squeakBiography")
        .unwrap()
        .as_str()
        .unwrap()
        .contains("\n"));
}

#[tokio::test]
async fn test_evaluate_feature_flags_multiple_flags() {
    let reader: Arc<dyn Client + Send + Sync> = setup_pg_reader_client(None).await;
    let writer: Arc<dyn Client + Send + Sync> = setup_pg_writer_client(None).await;
    let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));

    let team = insert_new_team_in_pg(reader.clone(), None)
        .await
        .expect("Failed to insert team in pg");

    let distinct_id = "user_distinct_id".to_string();
    insert_person_for_team_in_pg(reader.clone(), team.id, distinct_id.clone(), None)
        .await
        .expect("Failed to insert person");

    let flags = vec![
        FeatureFlag {
            name: Some("Flag 1".to_string()),
            id: 1,
            key: "flag_1".to_string(),
            active: true,
            deleted: false,
            team_id: team.id,
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            },
            ensure_experience_continuity: false,
            version: Some(1),
        },
        FeatureFlag {
            name: Some("Flag 2".to_string()),
            id: 2,
            key: "flag_2".to_string(),
            active: true,
            deleted: false,
            team_id: team.id,
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(0.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            },
            ensure_experience_continuity: false,
            version: Some(1),
        },
    ];

    let feature_flag_list = FeatureFlagList { flags };

    let evaluation_context = FeatureFlagEvaluationContext {
        team_id: team.id,
        project_id: team.project_id,
        distinct_id: distinct_id.clone(),
        feature_flags: feature_flag_list,
        reader,
        writer,
        cohort_cache,
        person_property_overrides: None,
        group_property_overrides: None,
        groups: None,
        hash_key_override: None,
        flag_keys: None,
    };

    let request_id = Uuid::new_v4();
    let result = evaluate_feature_flags(evaluation_context, request_id).await;

    assert!(!result.errors_while_computing_flags);
    assert!(result.flags["flag_1"].enabled);
    assert!(!result.flags["flag_2"].enabled);
    let legacy_response = LegacyFlagsResponse::from_response(result);
    assert!(!legacy_response.errors_while_computing_flags);
    assert_eq!(
        legacy_response.feature_flags["flag_1"],
        FlagValue::Boolean(true)
    );
    assert_eq!(
        legacy_response.feature_flags["flag_2"],
        FlagValue::Boolean(false)
    );
}

#[tokio::test]
async fn test_evaluate_feature_flags_details() {
    let reader: Arc<dyn Client + Send + Sync> = setup_pg_reader_client(None).await;
    let writer: Arc<dyn Client + Send + Sync> = setup_pg_writer_client(None).await;
    let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
    let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
    let distinct_id = "user123".to_string();
    insert_person_for_team_in_pg(reader.clone(), team.id, distinct_id.clone(), None)
        .await
        .expect("Failed to insert person");

    let flags = vec![
        FeatureFlag {
            name: Some("Flag 1".to_string()),
            id: 1,
            key: "flag_1".to_string(),
            active: true,
            deleted: false,
            team_id: team.id,
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            },
            ensure_experience_continuity: false,
            version: Some(1),
        },
        FeatureFlag {
            name: Some("Flag 2".to_string()),
            id: 2,
            key: "flag_2".to_string(),
            active: true,
            deleted: false,
            team_id: team.id,
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![]),
                    rollout_percentage: Some(0.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            },
            ensure_experience_continuity: false,
            version: Some(1),
        },
    ];

    let feature_flag_list = FeatureFlagList { flags };

    let evaluation_context = FeatureFlagEvaluationContext {
        team_id: team.id,
        project_id: team.project_id,
        distinct_id: distinct_id.clone(),
        feature_flags: feature_flag_list,
        reader,
        writer,
        cohort_cache,
        person_property_overrides: None,
        group_property_overrides: None,
        groups: None,
        hash_key_override: None,
        flag_keys: None,
    };

    let request_id = Uuid::new_v4();
    let result = evaluate_feature_flags(evaluation_context, request_id).await;

    assert!(!result.errors_while_computing_flags);

    assert_eq!(
        result.flags["flag_1"],
        FlagDetails {
            key: "flag_1".to_string(),
            enabled: true,
            variant: None,
            reason: FlagEvaluationReason {
                code: "condition_match".to_string(),
                condition_index: Some(0),
                description: Some("Matched condition set 1".to_string()),
            },
            metadata: FlagDetailsMetadata {
                id: 1,
                version: 1,
                description: None,
                payload: None,
            },
        }
    );
    assert_eq!(
        result.flags["flag_2"],
        FlagDetails {
            key: "flag_2".to_string(),
            enabled: false,
            variant: None,
            reason: FlagEvaluationReason {
                code: "out_of_rollout_bound".to_string(),
                condition_index: Some(0),
                description: Some("Out of rollout bound".to_string()),
            },
            metadata: FlagDetailsMetadata {
                id: 2,
                version: 1,
                description: None,
                payload: None,
            },
        }
    );
}

#[test]
fn test_flags_query_params_deserialization() {
    let json = r#"{
            "v": "1.0",
            "compression": "gzip",
            "lib_version": "2.0",
            "sent_at": 1234567890
        }"#;
    let params: FlagsQueryParams = serde_json::from_str(json).unwrap();
    assert_eq!(params.version, Some("1.0".to_string()));
    assert!(matches!(params.compression, Some(Compression::Gzip)));
    assert_eq!(params.lib_version, Some("2.0".to_string()));
    assert_eq!(params.sent_at, Some(1234567890));
}

#[test]
fn test_compression_deserialization() {
    assert_eq!(
        serde_json::from_str::<Compression>("\"gzip\"").unwrap(),
        Compression::Gzip
    );
    assert_eq!(
        serde_json::from_str::<Compression>("\"gzip-js\"").unwrap(),
        Compression::Gzip
    );
    // If "invalid" is actually deserialized to Unsupported, we should change our expectation
    assert_eq!(
        serde_json::from_str::<Compression>("\"invalid\"").unwrap(),
        Compression::Unsupported
    );
}

#[test]
fn test_flag_error_request_decoding() {
    let error = FlagError::RequestDecodingError("Test error".to_string());
    assert!(matches!(error, FlagError::RequestDecodingError(_)));
}

#[tokio::test]
async fn test_evaluate_feature_flags_with_overrides() {
    let reader: Arc<dyn Client + Send + Sync> = setup_pg_reader_client(None).await;
    let writer: Arc<dyn Client + Send + Sync> = setup_pg_writer_client(None).await;
    let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
    let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

    let flag = FeatureFlag {
        name: Some("Test Flag".to_string()),
        id: 1,
        key: "test_flag".to_string(),
        active: true,
        deleted: false,
        team_id: team.id,
        filters: FlagFilters {
            groups: vec![FlagPropertyGroup {
                properties: Some(vec![PropertyFilter {
                    key: "industry".to_string(),
                    value: Some(json!("tech")),
                    operator: Some(OperatorType::Exact),
                    prop_type: PropertyType::Group,
                    group_type_index: Some(0),
                    negation: None,
                }]),
                rollout_percentage: Some(100.0),
                variant: None,
            }],
            multivariate: None,
            aggregation_group_type_index: Some(0),
            payloads: None,
            super_groups: None,
            holdout_groups: None,
        },
        ensure_experience_continuity: false,
        version: Some(1),
    };
    let feature_flag_list = FeatureFlagList { flags: vec![flag] };

    let groups = HashMap::from([("project".to_string(), json!("project_123"))]);
    let group_property_overrides = HashMap::from([(
        "project".to_string(),
        HashMap::from([
            ("industry".to_string(), json!("tech")),
            ("$group_key".to_string(), json!("project_123")),
        ]),
    )]);

    let evaluation_context = FeatureFlagEvaluationContext {
        team_id: team.id,
        project_id: team.project_id,
        distinct_id: "user123".to_string(),
        feature_flags: feature_flag_list,
        reader,
        writer,
        cohort_cache,
        person_property_overrides: None,
        group_property_overrides: Some(group_property_overrides),
        groups: Some(groups),
        hash_key_override: None,
        flag_keys: None,
    };

    let request_id = Uuid::new_v4();
    let result = evaluate_feature_flags(evaluation_context, request_id).await;

    assert!(
        result.flags.contains_key("test_flag"),
        "test_flag not found in result flags"
    );
    let legacy_response = LegacyFlagsResponse::from_response(result);
    assert!(
        !legacy_response.errors_while_computing_flags,
        "Error while computing flags"
    );
    assert!(
        legacy_response.feature_flags.contains_key("test_flag"),
        "test_flag not found in result feature_flags"
    );

    let flag_value = legacy_response
        .feature_flags
        .get("test_flag")
        .expect("test_flag not found");

    assert_eq!(
        flag_value,
        &FlagValue::Boolean(true),
        "Flag value is not true as expected"
    );
}

#[tokio::test]
async fn test_long_distinct_id() {
    // distinct_id is CHAR(400)
    let long_id = "a".repeat(400);
    let reader: Arc<dyn Client + Send + Sync> = setup_pg_reader_client(None).await;
    let writer: Arc<dyn Client + Send + Sync> = setup_pg_writer_client(None).await;
    let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
    let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();
    let distinct_id = long_id.to_string();
    insert_person_for_team_in_pg(reader.clone(), team.id, distinct_id.clone(), None)
        .await
        .expect("Failed to insert person");
    let flag = FeatureFlag {
        name: Some("Test Flag".to_string()),
        id: 1,
        key: "test_flag".to_string(),
        active: true,
        deleted: false,
        team_id: team.id,
        filters: FlagFilters {
            groups: vec![FlagPropertyGroup {
                properties: Some(vec![]),
                rollout_percentage: Some(100.0),
                variant: None,
            }],
            multivariate: None,
            aggregation_group_type_index: None,
            payloads: None,
            super_groups: None,
            holdout_groups: None,
        },
        ensure_experience_continuity: false,
        version: Some(1),
    };

    let feature_flag_list = FeatureFlagList { flags: vec![flag] };

    let evaluation_context = FeatureFlagEvaluationContext {
        team_id: team.id,
        project_id: team.project_id,
        distinct_id: long_id,
        feature_flags: feature_flag_list,
        reader,
        writer,
        cohort_cache,
        person_property_overrides: None,
        group_property_overrides: None,
        groups: None,
        hash_key_override: None,
        flag_keys: None,
    };

    let request_id = Uuid::new_v4();
    let result = evaluate_feature_flags(evaluation_context, request_id).await;

    let legacy_response = LegacyFlagsResponse::from_response(result);

    assert!(!legacy_response.errors_while_computing_flags);
    assert_eq!(
        legacy_response.feature_flags["test_flag"],
        FlagValue::Boolean(true)
    );
}

#[test]
fn test_process_group_property_overrides() {
    // Test case 1: Both groups and existing overrides
    let groups = HashMap::from([
        ("project".to_string(), json!("project_123")),
        ("organization".to_string(), json!("org_456")),
    ]);

    let mut existing_overrides = HashMap::new();
    let mut project_props = HashMap::new();
    project_props.insert("industry".to_string(), json!("tech"));
    existing_overrides.insert("project".to_string(), project_props);

    let result =
        properties::get_group_property_overrides(Some(groups.clone()), Some(existing_overrides));

    assert!(result.is_some());
    let result = result.unwrap();

    // Check project properties
    let project_props = result.get("project").expect("Project properties missing");
    assert_eq!(project_props.get("industry"), Some(&json!("tech")));
    assert_eq!(project_props.get("$group_key"), Some(&json!("project_123")));

    // Check organization properties
    let org_props = result
        .get("organization")
        .expect("Organization properties missing");
    assert_eq!(org_props.get("$group_key"), Some(&json!("org_456")));

    // Test case 2: Only groups, no existing overrides
    let result = properties::get_group_property_overrides(Some(groups.clone()), None);

    assert!(result.is_some());
    let result = result.unwrap();
    assert_eq!(result.len(), 2);
    assert_eq!(
        result.get("project").unwrap().get("$group_key"),
        Some(&json!("project_123"))
    );

    // Test case 3: No groups, only existing overrides
    let mut existing_overrides = HashMap::new();
    let mut project_props = HashMap::new();
    project_props.insert("industry".to_string(), json!("tech"));
    existing_overrides.insert("project".to_string(), project_props);

    let result = properties::get_group_property_overrides(None, Some(existing_overrides.clone()));

    assert!(result.is_some());
    assert_eq!(result.unwrap(), existing_overrides);

    // Test case 4: Neither groups nor existing overrides
    let result = properties::get_group_property_overrides(None, None);
    assert!(result.is_none());
}

#[test]
fn test_decode_request_content_types() {
    let test_json = r#"{"token": "test_token", "distinct_id": "user123"}"#;
    let body = Bytes::from(test_json);
    let meta = FlagsQueryParams::default();

    // Test application/json
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_TYPE, "application/json".parse().unwrap());
    let result = decoding::decode_request(&headers, body.clone(), &meta);
    assert!(result.is_ok());
    let request = result.unwrap();
    assert_eq!(request.token, Some("test_token".to_string()));
    assert_eq!(request.distinct_id, Some("user123".to_string()));

    // Test text/plain
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_TYPE, "text/plain".parse().unwrap());
    let result = decoding::decode_request(&headers, body.clone(), &meta);
    assert!(result.is_ok());
    let request = result.unwrap();
    assert_eq!(request.token, Some("test_token".to_string()));
    assert_eq!(request.distinct_id, Some("user123".to_string()));

    // Test application/json with charset
    let mut headers = HeaderMap::new();
    headers.insert(
        CONTENT_TYPE,
        "application/json; charset=utf-8".parse().unwrap(),
    );
    let result = decoding::decode_request(&headers, body.clone(), &meta);
    assert!(result.is_ok());
    let request = result.unwrap();
    assert_eq!(request.token, Some("test_token".to_string()));
    assert_eq!(request.distinct_id, Some("user123".to_string()));

    // Test default when no content type is provided
    let headers = HeaderMap::new();
    let result = decoding::decode_request(&headers, body.clone(), &meta);
    assert!(result.is_ok());
    let request = result.unwrap();
    assert_eq!(request.token, Some("test_token".to_string()));
    assert_eq!(request.distinct_id, Some("user123".to_string()));

    // Test unsupported content type
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_TYPE, "application/xml".parse().unwrap());
    let result = decoding::decode_request(&headers, body, &meta);
    assert!(matches!(result, Err(FlagError::RequestDecodingError(_))));
}

#[tokio::test]
async fn test_fetch_and_filter_flags() {
    let redis_reader_client = setup_redis_client(None).await;
    let redis_writer_client = setup_redis_client(None).await;
    let reader: Arc<dyn Client + Send + Sync> = setup_pg_reader_client(None).await;
    let flag_service = FlagService::new(
        redis_reader_client.clone(),
        redis_writer_client.clone(),
        reader.clone(),
    );
    let team = insert_new_team_in_pg(reader.clone(), None).await.unwrap();

    // Create a mix of survey and non-survey flags
    let flags = vec![
        FeatureFlag {
            name: Some("Survey Flag 1".to_string()),
            id: 1,
            key: format!("{}{}", SURVEY_TARGETING_FLAG_PREFIX, "survey1"),
            active: true,
            deleted: false,
            team_id: team.id,
            filters: FlagFilters::default(),
            ensure_experience_continuity: false,
            version: Some(1),
        },
        FeatureFlag {
            name: Some("Survey Flag 2".to_string()),
            id: 2,
            key: format!("{}{}", SURVEY_TARGETING_FLAG_PREFIX, "survey2"),
            active: true,
            deleted: false,
            team_id: team.id,
            filters: FlagFilters::default(),
            ensure_experience_continuity: false,
            version: Some(1),
        },
        FeatureFlag {
            name: Some("Regular Flag 1".to_string()),
            id: 3,
            key: "regular_flag1".to_string(),
            active: true,
            deleted: false,
            team_id: team.id,
            filters: FlagFilters::default(),
            ensure_experience_continuity: false,
            version: Some(1),
        },
        FeatureFlag {
            name: Some("Regular Flag 2".to_string()),
            id: 4,
            key: "regular_flag2".to_string(),
            active: true,
            deleted: false,
            team_id: team.id,
            filters: FlagFilters::default(),
            ensure_experience_continuity: false,
            version: Some(1),
        },
    ];

    // Insert flags into redis
    let flags_json = serde_json::to_string(&flags).unwrap();
    insert_flags_for_team_in_redis(
        redis_reader_client.clone(),
        team.id,
        team.project_id,
        Some(flags_json),
    )
    .await
    .unwrap();

    // Test 1: only_evaluate_survey_feature_flags = true
    let query_params = FlagsQueryParams {
        only_evaluate_survey_feature_flags: Some(true),
        ..Default::default()
    };
    let result = fetch_and_filter(&flag_service, team.project_id, &query_params)
        .await
        .unwrap();
    assert_eq!(result.flags.len(), 2);
    assert!(result
        .flags
        .iter()
        .all(|f| f.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX)));

    // Test 2: only_evaluate_survey_feature_flags = false
    let query_params = FlagsQueryParams {
        only_evaluate_survey_feature_flags: Some(false),
        ..Default::default()
    };
    let result = fetch_and_filter(&flag_service, team.project_id, &query_params)
        .await
        .unwrap();
    assert_eq!(result.flags.len(), 4);
    assert!(result
        .flags
        .iter()
        .any(|f| !f.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX)));

    // Test 3: only_evaluate_survey_feature_flags not set
    let query_params = FlagsQueryParams::default();
    let result = fetch_and_filter(&flag_service, team.project_id, &query_params)
        .await
        .unwrap();
    assert_eq!(result.flags.len(), 4);
    assert!(result
        .flags
        .iter()
        .any(|f| !f.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX)));

    // Test 4: Survey filter only (flag_keys filtering now happens in evaluation logic)
    let query_params = FlagsQueryParams {
        only_evaluate_survey_feature_flags: Some(true),
        ..Default::default()
    };

    let result = fetch_and_filter(&flag_service, team.project_id, &query_params)
        .await
        .unwrap();

    // Should return all survey flags since flag_keys filtering now happens in evaluation logic
    // Survey filter keeps only survey flags, but flag_keys filtering is deferred to evaluation
    assert_eq!(result.flags.len(), 2);
    assert!(result
        .flags
        .iter()
        .all(|f| f.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX)));
}
