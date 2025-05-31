use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    cohorts::cohort_cache_manager::CohortCacheManager,
    flags::{
        flag_analytics::{increment_request_count, SURVEY_TARGETING_FLAG_PREFIX},
        flag_group_type_mapping::GroupTypeMappingCache,
        flag_matching::FeatureFlagMatcher,
        flag_models::{FeatureFlag, FeatureFlagList},
        flag_request::{FlagRequest, FlagRequestType},
        flag_service::FlagService,
    },
    metrics::consts::FLAG_REQUEST_KLUDGE_COUNTER,
    router,
    team::team_models::Team,
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

    /// Optional flag to only evaluate survey feature flags
    pub only_evaluate_survey_feature_flags: Option<bool>,
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
    let flag_service = FlagService::new(
        context.state.redis_writer.clone(),
        context.state.redis_reader.clone(),
        context.state.postgres_reader.clone(),
    );

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

    let filtered_flags =
        fetch_and_filter_flags(&flag_service, project_id, &request, &context.meta).await?;

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
            context.state.redis_writer.clone(),
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

/// Filters flags to only include survey flags if requested
/// This field is optional, passed in as a query param, and defaults to false
fn filter_survey_flags(flags: Vec<FeatureFlag>, only_survey_flags: bool) -> Vec<FeatureFlag> {
    if only_survey_flags {
        flags
            .into_iter()
            .filter(|flag| flag.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX))
            .collect()
    } else {
        flags
    }
}

/// Filters flags to only include those with keys in the requested set
/// This field is optional, passed in as part of the request body, and if it is not provided, we return all flags
fn filter_by_requested_keys(
    flags: Vec<FeatureFlag>,
    requested_keys: Option<&[String]>,
) -> Vec<FeatureFlag> {
    if let Some(keys) = requested_keys {
        let requested_keys_set: HashSet<String> = keys.iter().cloned().collect();
        flags
            .into_iter()
            .filter(|flag| requested_keys_set.contains(&flag.key))
            .collect()
    } else {
        flags
    }
}

/// Fetches flags from cache/DB and filters them based on requested keys and survey flag preferences.
///
/// The filtering happens in two stages:
/// 1. If only_evaluate_survey_feature_flags is true, filter to only survey flags
/// 2. If specific flag_keys are requested, filter to only those flags
async fn fetch_and_filter_flags(
    flag_service: &FlagService,
    project_id: i64,
    request: &FlagRequest,
    query_params: &FlagsQueryParams,
) -> Result<FeatureFlagList, FlagError> {
    let all_flags = flag_service.get_flags_from_cache_or_pg(project_id).await?;

    let flags_after_survey_filter = filter_survey_flags(
        all_flags.flags,
        query_params
            .only_evaluate_survey_feature_flags
            .unwrap_or(false),
    );

    let final_filtered_flags =
        filter_by_requested_keys(flags_after_survey_filter, request.flag_keys.as_deref());

    Ok(FeatureFlagList::new(final_filtered_flags))
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
        reader: state.postgres_reader.clone(),
        writer: state.postgres_writer.clone(),
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
    use crate::{
        api::types::{
            FlagDetails, FlagDetailsMetadata, FlagEvaluationReason, FlagValue, LegacyFlagsResponse,
        },
        config::Config,
        flags::flag_models::{FeatureFlag, FlagFilters, FlagPropertyGroup},
        properties::property_models::{OperatorType, PropertyFilter},
        utils::test_utils::{
            insert_flags_for_team_in_redis, insert_new_team_in_pg, insert_person_for_team_in_pg,
            setup_pg_reader_client, setup_pg_writer_client, setup_redis_client,
        },
    };

    use super::*;
    use axum::http::HeaderMap;
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

    #[tokio::test]
    async fn test_fetch_and_filter_flags() {
        let redis_client = setup_redis_client(None);
        let reader: Arc<dyn Client + Send + Sync> = setup_pg_reader_client(None).await;
        let flag_service = FlagService::new(redis_client.clone(), reader.clone());
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
            redis_client.clone(),
            team.id,
            team.project_id,
            Some(flags_json),
        )
        .await
        .unwrap();

        let base_request = FlagRequest {
            token: Some(team.api_token.clone()),
            distinct_id: Some("test_user".to_string()),
            ..Default::default()
        };

        // Test 1: only_evaluate_survey_feature_flags = true
        let query_params = FlagsQueryParams {
            only_evaluate_survey_feature_flags: Some(true),
            ..Default::default()
        };
        let result =
            fetch_and_filter_flags(&flag_service, team.project_id, &base_request, &query_params)
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
        let result =
            fetch_and_filter_flags(&flag_service, team.project_id, &base_request, &query_params)
                .await
                .unwrap();
        assert_eq!(result.flags.len(), 4);
        assert!(result
            .flags
            .iter()
            .any(|f| !f.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX)));

        // Test 3: only_evaluate_survey_feature_flags not set
        let query_params = FlagsQueryParams::default();
        let result =
            fetch_and_filter_flags(&flag_service, team.project_id, &base_request, &query_params)
                .await
                .unwrap();
        assert_eq!(result.flags.len(), 4);
        assert!(result
            .flags
            .iter()
            .any(|f| !f.key.starts_with(SURVEY_TARGETING_FLAG_PREFIX)));

        // Test 4: Both survey filter and specific keys requested
        let request = FlagRequest {
            flag_keys: Some(vec![
                format!("{}{}", SURVEY_TARGETING_FLAG_PREFIX, "survey1"),
                "regular_flag1".to_string(),
            ]),
            ..base_request
        };

        let query_params = FlagsQueryParams {
            only_evaluate_survey_feature_flags: Some(true),
            ..Default::default()
        };

        let result =
            fetch_and_filter_flags(&flag_service, team.project_id, &request, &query_params)
                .await
                .unwrap();

        // Should only return survey1 since both filters are applied:
        // 1. Survey filter keeps only survey flags
        // 2. Key filter then keeps only survey1 from those
        assert_eq!(result.flags.len(), 1);
        assert_eq!(
            result.flags[0].key,
            format!("{}{}", SURVEY_TARGETING_FLAG_PREFIX, "survey1")
        );
    }
}
