use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    cohorts::cohort_cache_manager::CohortCacheManager,
    flags::{
        flag_analytics::{increment_request_count, SURVEY_TARGETING_FLAG_PREFIX},
        flag_group_type_mapping::GroupTypeMappingCache,
        flag_matching::FeatureFlagMatcher,
        flag_models::FeatureFlagList,
        flag_request::{FlagRequest, FlagRequestType},
        flag_service::FlagService,
    },
    metrics::consts::FLAG_REQUEST_KLUDGE_COUNTER,
    router,
};
use axum::{
    extract::State,
    http::{header::CONTENT_TYPE, header::ORIGIN, header::USER_AGENT, HeaderMap},
};
use base64::{engine::general_purpose, Engine as _};
use bytes::Bytes;
use chrono;
use common_cookieless::{CookielessServerHashMode, EventData, TeamData};
use common_database::Client;
use common_geoip::GeoIpClient;
use common_metrics::inc;
use common_models::team_models::Team;
use flate2::read::GzDecoder;
use limiters::redis::ServiceName;
use percent_encoding::percent_decode;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::{HashMap, HashSet},
    io::Read,
    net::IpAddr,
    sync::Arc,
};
use uuid::Uuid;

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum Compression {
    #[serde(rename = "gzip", alias = "gzip-js")]
    Gzip,
    #[serde(rename = "base64")]
    Base64,
    #[default]
    #[serde(other)]
    Unsupported,
}

impl Compression {
    pub fn as_str(&self) -> &'static str {
        match self {
            Compression::Gzip => "gzip",
            Compression::Base64 => "base64",
            Compression::Unsupported => "unsupported",
        }
    }
}

#[derive(Clone, Deserialize, Default)]
pub struct FlagsQueryParams {
    /// Optional API version identifier
    #[serde(alias = "v")]
    pub version: Option<String>,

    /// Compression type for the incoming request
    pub compression: Option<Compression>,

    /// Library version (alias: "ver")
    #[serde(alias = "ver")]
    pub lib_version: Option<String>,

    /// Optional timestamp indicating when the request was sent
    #[serde(alias = "_")]
    pub sent_at: Option<i64>,
}
pub struct RequestContext {
    /// Shared state holding services (DB, Redis, GeoIP, etc.)
    pub state: State<router::State>,

    /// Client IP
    pub ip: IpAddr,

    /// HTTP headers
    pub headers: HeaderMap,

    /// Query params (contains compression, library version, etc.)
    pub meta: FlagsQueryParams,

    /// Raw request body
    pub body: Bytes,

    /// Request ID
    pub request_id: Uuid,
}

/// Represents the various property overrides that can be passed around
/// (person, group, groups, and optional hash key).
pub type RequestPropertyOverrides = (
    Option<HashMap<String, Value>>, // person_property_overrides
    Option<HashMap<String, HashMap<String, Value>>>, // group_property_overrides
    Option<HashMap<String, Value>>, // groups
    Option<String>,                 // hash_key_override
);

/// Primary entry point for feature flag requests.
/// 1) Parses and authenticates the request,
/// 2) Fetches the team and feature flags,
/// 3) Prepares property overrides,
/// 4) Evaluates the requested flags,
/// 5) Returns a [`ServiceResponse`] or an error.
pub async fn process_request(context: RequestContext) -> Result<FlagsResponse, FlagError> {
    let flag_service = FlagService::new(context.state.redis.clone(), context.state.reader.clone());

    let (original_distinct_id, verified_token, request) =
        parse_and_authenticate_request(&context, &flag_service).await?;

    // Once we've verified the token, check if the token is billing limited (this will save us from hitting the DB if we have a quota-limited token)
    let billing_limited = context
        .state
        .billing_limiter
        .is_limited(verified_token.as_str())
        .await;
    if billing_limited {
        // return an empty FlagsResponse with a quotaLimited field called "feature_flags"
        // TODO docs
        return Ok(FlagsResponse {
            flags: HashMap::new(),
            errors_while_computing_flags: false,
            quota_limited: Some(vec![ServiceName::FeatureFlags.as_string()]),
            request_id: context.request_id,
        });
    }

    // again, now we can start doing heavier queries, since at this point most stuff has been from redis

    let team = flag_service
        .get_team_from_cache_or_pg(&verified_token)
        .await?;

    let team_id = team.id;
    let project_id = team.project_id;

    let distinct_id =
        handle_cookieless_distinct_id(&context, &request, &team, original_distinct_id.clone())
            .await?;

    let filtered_flags = fetch_and_filter_flags(&flag_service, project_id, &request).await?;

    let (person_prop_overrides, group_prop_overrides, groups, hash_key_override) =
        prepare_property_overrides(&context, &request)?;

    let response = evaluate_flags_for_request(
        &context.state,
        team_id,
        project_id,
        distinct_id,
        filtered_flags.clone(),
        person_prop_overrides,
        group_prop_overrides,
        groups,
        hash_key_override,
        context.request_id,
    )
    .await;

    // bill the flag request
    if filtered_flags
        .flags
        .iter()
        .all(|f| !f.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX))
    // NB don't charge if all the flags are survey targeting flags
    {
        if let Err(e) = increment_request_count(
            context.state.redis.clone(),
            team_id,
            1,
            FlagRequestType::Decide,
        )
        .await
        {
            inc(
                "flag_request_redis_error",
                &[("error".to_string(), e.to_string())],
                1,
            );
        }
    }

    Ok(response)
}

/// Parses the request body, extracts the distinct_id and token, then verifies the token.
async fn parse_and_authenticate_request(
    context: &RequestContext,
    flag_service: &FlagService,
) -> Result<(String, String, FlagRequest), FlagError> {
    let RequestContext {
        headers,
        body,
        meta,
        ..
    } = context;

    let request = decode_request(headers, body.clone(), meta)?;
    let distinct_id = request.extract_distinct_id()?;
    let token = request.extract_token()?;
    let verified_token = flag_service.verify_token(&token).await?;

    Ok((distinct_id, verified_token, request))
}

/// Fetches flags from cache/DB and filters them based on requested keys, if any.
async fn fetch_and_filter_flags(
    flag_service: &FlagService,
    project_id: i64,
    request: &FlagRequest,
) -> Result<FeatureFlagList, FlagError> {
    let all_flags = flag_service.get_flags_from_cache_or_pg(project_id).await?;
    if let Some(flag_keys) = &request.flag_keys {
        let keys: HashSet<String> = flag_keys.iter().cloned().collect();
        let filtered = all_flags
            .flags
            .into_iter()
            .filter(|f| keys.contains(&f.key))
            .collect();
        Ok(FeatureFlagList::new(filtered))
    } else {
        Ok(all_flags)
    }
}

/// Determines property overrides for person and group properties,
/// applying geoip if enabled, and returning the optional hash key override.
fn prepare_property_overrides(
    context: &RequestContext,
    request: &FlagRequest,
) -> Result<RequestPropertyOverrides, FlagError> {
    let geoip_enabled = !request.geoip_disable.unwrap_or(false);
    let person_property_overrides = get_person_property_overrides(
        geoip_enabled,
        request.person_properties.clone(),
        &context.ip,
        &context.state.geoip,
    );

    let groups = request.groups.clone();
    let group_property_overrides =
        process_group_property_overrides(groups.clone(), request.group_properties.clone());

    let hash_key_override = request.anon_distinct_id.clone();

    Ok((
        person_property_overrides,
        group_property_overrides,
        groups,
        hash_key_override,
    ))
}

/// Represents all context required for evaluating a set of feature flags.
pub struct FeatureFlagEvaluationContext {
    pub team_id: i32,
    pub project_id: i64,
    pub distinct_id: String,
    pub feature_flags: FeatureFlagList,
    pub reader: Arc<dyn Client + Send + Sync>,
    pub writer: Arc<dyn Client + Send + Sync>,
    pub cohort_cache: Arc<CohortCacheManager>,
    pub person_property_overrides: Option<HashMap<String, Value>>,
    pub group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    pub groups: Option<HashMap<String, Value>>,
    pub hash_key_override: Option<String>,
}

/// Constructs a [`FeatureFlagEvaluationContext`] and evaluates the flags using the provided overrides.
#[allow(clippy::too_many_arguments)]
async fn evaluate_flags_for_request(
    state: &State<router::State>,
    team_id: i32,
    project_id: i64,
    distinct_id: String,
    filtered_flags: FeatureFlagList,
    person_property_overrides: Option<HashMap<String, Value>>,
    group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    groups: Option<HashMap<String, Value>>,
    hash_key_override: Option<String>,
    request_id: Uuid,
) -> FlagsResponse {
    let ctx = FeatureFlagEvaluationContext {
        team_id,
        project_id,
        distinct_id,
        feature_flags: filtered_flags,
        reader: state.reader.clone(),
        writer: state.writer.clone(),
        cohort_cache: state.cohort_cache_manager.clone(),
        person_property_overrides,
        group_property_overrides,
        groups,
        hash_key_override,
    };

    evaluate_feature_flags(ctx, request_id).await
}

/// Translates the request body and query params into a [`FlagRequest`] by examining Content-Type and compression settings.
/// We support (i.e. our SDKs send) the following content types:
/// - application/json
/// - application/json-patch; charset=utf-8
/// - text/plain
/// - application/x-www-form-urlencoded
///
/// We also support gzip and base64 compression.
pub fn decode_request(
    headers: &HeaderMap,
    body: Bytes,
    query: &FlagsQueryParams,
) -> Result<FlagRequest, FlagError> {
    let content_type = headers
        .get(CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("application/json"); // Default to JSON if no content type

    let base_content_type = content_type.split(';').next().unwrap_or("").trim();

    match base_content_type {
        "application/json" | "text/plain" => {
            let decoded_body = decode_body(body, query.compression)?;
            FlagRequest::from_bytes(decoded_body)
        }
        "application/x-www-form-urlencoded" => decode_form_data(body, query.compression),
        _ => Err(FlagError::RequestDecodingError(format!(
            "unsupported content type: {content_type}"
        ))),
    }
}

/// Evaluates all requested feature flags in the provided context, returning a [`FlagsResponse`].
pub async fn evaluate_feature_flags(
    context: FeatureFlagEvaluationContext,
    request_id: Uuid,
) -> FlagsResponse {
    let group_type_mapping_cache = GroupTypeMappingCache::new(context.project_id);

    let mut matcher = FeatureFlagMatcher::new(
        context.distinct_id,
        context.team_id,
        context.project_id,
        context.reader,
        context.writer,
        context.cohort_cache,
        Some(group_type_mapping_cache),
        context.groups,
    );

    matcher
        .evaluate_all_feature_flags(
            context.feature_flags,
            context.person_property_overrides,
            context.group_property_overrides,
            context.hash_key_override,
            request_id,
        )
        .await
}

/// Determines whether to merge geoip properties into the existing person properties.
pub fn get_person_property_overrides(
    geoip_enabled: bool,
    person_properties: Option<HashMap<String, Value>>,
    ip: &IpAddr,
    geoip_service: &GeoIpClient,
) -> Option<HashMap<String, Value>> {
    match (geoip_enabled, person_properties) {
        (true, Some(mut props)) => {
            if let Some(geoip_props) = geoip_service.get_geoip_properties(&ip.to_string()) {
                props.extend(geoip_props.into_iter().map(|(k, v)| (k, Value::String(v))));
            }
            Some(props)
        }
        (true, None) => {
            if let Some(geoip_props) = geoip_service.get_geoip_properties(&ip.to_string()) {
                if !geoip_props.is_empty() {
                    Some(
                        geoip_props
                            .into_iter()
                            .map(|(k, v)| (k, Value::String(v)))
                            .collect(),
                    )
                } else {
                    None
                }
            } else {
                None
            }
        }
        (false, Some(props)) => Some(props),
        (false, None) => None,
    }
}

/// Incorporates `groups` into group property overrides by assigning each `$group_key`.
pub fn process_group_property_overrides(
    groups: Option<HashMap<String, Value>>,
    existing_overrides: Option<HashMap<String, HashMap<String, Value>>>,
) -> Option<HashMap<String, HashMap<String, Value>>> {
    match groups {
        Some(group_map) => {
            let group_key_overrides: HashMap<String, HashMap<String, Value>> = group_map
                .into_iter()
                .map(|(group_type, group_key)| {
                    let mut merged_props = existing_overrides
                        .as_ref()
                        .and_then(|m| m.get(&group_type))
                        .cloned()
                        .unwrap_or_default();
                    merged_props.insert("$group_key".to_string(), group_key);
                    (group_type, merged_props)
                })
                .collect();

            let mut result = existing_overrides.unwrap_or_default();
            result.extend(group_key_overrides);
            Some(result)
        }
        None => existing_overrides,
    }
}

// TODO: Make sure this protects against zip bombs, etc.  `/capture` does this
// and it's a good idea to do that here as well, probably worth extracting that method into
// /common given that it's used in multiple places
fn decompress_gzip(compressed: Bytes) -> Result<Bytes, FlagError> {
    let mut decoder = GzDecoder::new(&compressed[..]);
    let mut decompressed = Vec::new();
    decoder.read_to_end(&mut decompressed).map_err(|e| {
        FlagError::RequestDecodingError(format!("gzip decompression failed: {}", e))
    })?;
    Ok(Bytes::from(decompressed))
}

/// Decodes and decompresses raw bytes according to the provided [`Compression`].
fn decode_body(body: Bytes, compression: Option<Compression>) -> Result<Bytes, FlagError> {
    match compression {
        Some(Compression::Gzip) => decompress_gzip(body),
        Some(Compression::Base64) => decode_base64(body),
        Some(Compression::Unsupported) => Err(FlagError::RequestDecodingError(
            "Unsupported compression type".to_string(),
        )),
        None => Ok(body),
    }
}

/// Decodes base64 into raw bytes.
fn decode_base64(body: Bytes) -> Result<Bytes, FlagError> {
    let decoded = general_purpose::STANDARD
        .decode(body)
        .map_err(|e| FlagError::RequestDecodingError(format!("Base64 decoding error: {}", e)))?;
    Ok(Bytes::from(decoded))
}

/// Decodes form-encoded data that contains a base64-encoded JSON FlagRequest.
/// Expects data in the format: data=<base64-encoded-json> or just <base64-encoded-json>
pub fn decode_form_data(
    body: Bytes,
    compression: Option<Compression>,
) -> Result<FlagRequest, FlagError> {
    // Convert bytes to string first so we can manipluate it
    let form_data = String::from_utf8(body.to_vec()).map_err(|e| {
        tracing::debug!("Invalid UTF-8 in form data: {}", e);
        FlagError::RequestDecodingError("Invalid UTF-8 in form data".into())
    })?;

    // URL decode the string if needed
    let decoded_form = percent_decode(form_data.as_bytes())
        .decode_utf8()
        .map_err(|e| {
            tracing::debug!("Failed to URL decode form data: {}", e);
            FlagError::RequestDecodingError("Failed to URL decode form data".into())
        })?;

    // Extract base64 part, handling both with and without 'data=' prefix
    // see https://github.com/PostHog/posthog/blob/master/posthog/utils.py#L693-L699
    let base64_str = if decoded_form.starts_with("data=") {
        decoded_form.split('=').nth(1).unwrap_or("")
    } else {
        // Count how often we receive base64 data without the 'data=' prefix
        inc(
            FLAG_REQUEST_KLUDGE_COUNTER,
            &[("type".to_string(), "missing_data_prefix".to_string())],
            1,
        );
        &decoded_form
    };

    // Remove whitespace and add padding if necessary
    // https://github.com/PostHog/posthog/blob/master/posthog/utils.py#L701-L705
    let mut cleaned_base64 = base64_str.replace(' ', "");
    let padding_needed = cleaned_base64.len() % 4;
    if padding_needed > 0 {
        inc(
            FLAG_REQUEST_KLUDGE_COUNTER,
            &[("type".to_string(), "padding_needed".to_string())],
            1,
        );
        cleaned_base64.push_str(&"=".repeat(4 - padding_needed));
    }

    // Handle compression if specified (we don't support gzip for form-urlencoded data)
    let decoded = match compression {
        Some(Compression::Gzip) => {
            return Err(FlagError::RequestDecodingError(
                "Gzip compression not supported for form-urlencoded data".into(),
            ))
        }
        Some(Compression::Base64) | None => decode_base64(Bytes::from(cleaned_base64))?,
        Some(Compression::Unsupported) => {
            return Err(FlagError::RequestDecodingError(
                "Unsupported compression type".into(),
            ))
        }
    };

    // Convert to UTF-8 string with utf8_lossy to handle invalid UTF-8 sequences
    // this is equivalent to using Python's `surrogatepass`, since it just replaces
    // unparseable characters with the Unicode replacement character (U+FFFD) instead of failing to decode the request
    // at all.
    let json_str = {
        let lossy_str = String::from_utf8_lossy(&decoded);
        // Count how often we receive base64 data with invalid UTF-8 sequences
        if lossy_str.contains('\u{FFFD}') {
            inc(
                FLAG_REQUEST_KLUDGE_COUNTER,
                &[("type".to_string(), "lossy_utf8".to_string())],
                1,
            );
        }
        lossy_str.into_owned()
    };

    // Parse JSON into FlagRequest
    serde_json::from_str(&json_str).map_err(|e| {
        tracing::debug!("failed to parse JSON: {}", e);
        FlagError::RequestDecodingError("invalid JSON structure".into())
    })
}

async fn handle_cookieless_distinct_id(
    context: &RequestContext,
    request: &FlagRequest,
    team: &Team,
    distinct_id: String,
) -> Result<String, FlagError> {
    let event_data = EventData {
        ip: &context.ip.to_string(),
        timestamp_ms: context
            .meta
            .sent_at
            .unwrap_or_else(|| chrono::Utc::now().timestamp_millis()) as u64,
        host: context
            .headers
            .get(ORIGIN)
            .map(|h| h.to_str().unwrap_or(""))
            .unwrap_or(""),
        user_agent: context
            .headers
            .get(USER_AGENT)
            .map(|h| h.to_str().unwrap_or(""))
            .unwrap_or(""),
        event_time_zone: request.timezone.as_deref(),
        hash_extra: request.cookieless_hash_extra.as_deref(),
        distinct_id: &distinct_id,
    };

    let team_data = TeamData {
        team_id: team.id,
        timezone: team.timezone.clone(),
        cookieless_server_hash_mode: CookielessServerHashMode::from(
            team.cookieless_server_hash_mode,
        ),
    };

    context
        .state
        .cookieless_manager
        .compute_cookieless_distinct_id(event_data, team_data)
        .await
        .map_err(FlagError::CookielessError)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        api::types::{
            FlagDetails, FlagDetailsMetadata, FlagEvaluationReason, FlagValue, LegacyFlagsResponse,
        },
        config::Config,
        flags::flag_models::{FeatureFlag, FlagFilters, FlagPropertyGroup},
        properties::property_models::{OperatorType, PropertyFilter},
        utils::test_utils::{
            insert_person_for_team_in_pg, setup_pg_reader_client, setup_pg_writer_client,
        },
    };
    use axum::http::HeaderMap;
    use common_models::test_utils::insert_new_team_in_pg;
    use serde_json::{json, Value};
    use std::net::{Ipv4Addr, Ipv6Addr};

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

        let result = get_person_property_overrides(
            true,
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

        let result = get_person_property_overrides(
            true,
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

        let result = get_person_property_overrides(
            false,
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

        let result = get_person_property_overrides(
            false,
            None,
            &IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)),
            &geoip_service,
        );

        assert!(result.is_none());
    }

    #[test]
    fn test_geoip_enabled_local_ip() {
        let geoip_service = create_test_geoip_service();

        let result = get_person_property_overrides(
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
                        prop_type: "person".to_string(),
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
                        prop_type: "cohort".to_string(),
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
                    code: "unknown".to_string(),
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

        let result = decode_request(&headers, body, &meta);

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

        let result = decode_request(&headers, body, &meta);
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

        let result = decode_request(&headers, body, &meta);
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
        let result = get_person_property_overrides(
            true,
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
        let result = get_person_property_overrides(
            true,
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

        let result = decode_request(&headers, body, &meta);
        assert!(matches!(result, Err(FlagError::RequestDecodingError(_))));
    }

    #[test]
    fn test_decode_request_malformed_json() {
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_TYPE, "application/json".parse().unwrap());
        let body = Bytes::from_static(b"{invalid json}");
        let meta = FlagsQueryParams::default();

        let result = decode_request(&headers, body, &meta);
        assert!(result.is_err(), "Expected an error, but got Ok");
    }

    #[test]
    fn test_decode_request_form_urlencoded() {
        let mut headers = HeaderMap::new();
        headers.insert(
            CONTENT_TYPE,
            "application/x-www-form-urlencoded".parse().unwrap(),
        );
        let body = Bytes::from(
            "data=eyJ0b2tlbiI6InRlc3RfdG9rZW4iLCJkaXN0aW5jdF9pZCI6InVzZXIxMjMifQ%3D%3D",
        );
        let meta = FlagsQueryParams::default();

        let result = decode_request(&headers, body, &meta);
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
            let result = decode_form_data(body, None);

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

        let result = decode_form_data(body, None);
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

        let result = decode_form_data(body, Some(Compression::Base64));
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
        let result = decode_form_data(body.clone(), Some(Compression::Base64));
        assert!(result.is_ok());

        // No compression should work
        let result = decode_form_data(body.clone(), None);
        assert!(result.is_ok());

        // Gzip compression should fail
        let result = decode_form_data(body.clone(), Some(Compression::Gzip));
        assert!(matches!(
            result,
            Err(FlagError::RequestDecodingError(msg)) if msg.contains("not supported")
        ));

        // Unsupported compression should fail
        let result = decode_form_data(body, Some(Compression::Unsupported));
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
            let result = decode_form_data(body, None);
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
        let result = decode_form_data(body, Some(Compression::Base64));

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
            .unwrap();

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
                        prop_type: "group".to_string(),
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
            process_group_property_overrides(Some(groups.clone()), Some(existing_overrides));

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
        let result = process_group_property_overrides(Some(groups.clone()), None);

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

        let result = process_group_property_overrides(None, Some(existing_overrides.clone()));

        assert!(result.is_some());
        assert_eq!(result.unwrap(), existing_overrides);

        // Test case 4: Neither groups nor existing overrides
        let result = process_group_property_overrides(None, None);
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
        let result = decode_request(&headers, body.clone(), &meta);
        assert!(result.is_ok());
        let request = result.unwrap();
        assert_eq!(request.token, Some("test_token".to_string()));
        assert_eq!(request.distinct_id, Some("user123".to_string()));

        // Test text/plain
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_TYPE, "text/plain".parse().unwrap());
        let result = decode_request(&headers, body.clone(), &meta);
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
        let result = decode_request(&headers, body.clone(), &meta);
        assert!(result.is_ok());
        let request = result.unwrap();
        assert_eq!(request.token, Some("test_token".to_string()));
        assert_eq!(request.distinct_id, Some("user123".to_string()));

        // Test default when no content type is provided
        let headers = HeaderMap::new();
        let result = decode_request(&headers, body.clone(), &meta);
        assert!(result.is_ok());
        let request = result.unwrap();
        assert_eq!(request.token, Some("test_token".to_string()));
        assert_eq!(request.distinct_id, Some("user123".to_string()));

        // Test unsupported content type
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_TYPE, "application/xml".parse().unwrap());
        let result = decode_request(&headers, body, &meta);
        assert!(matches!(result, Err(FlagError::RequestDecodingError(_))));
    }
}
