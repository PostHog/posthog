use crate::{
    api::{errors::FlagError, types::FlagsResponse},
    client::{database::Client, geoip::GeoIpClient},
    cohort::cohort_cache_manager::CohortCacheManager,
    flags::{
        flag_matching::{FeatureFlagMatcher, GroupTypeMappingCache},
        flag_models::{FeatureFlag, FeatureFlagList},
        flag_request::FlagRequest,
        flag_service::FlagService,
    },
    metrics::metrics_consts::FLAG_CACHE_HIT_COUNTER,
    router,
    team::team_models::Team,
};
use axum::{extract::State, http::HeaderMap};
use base64::{engine::general_purpose, Engine as _};
use bytes::Bytes;
use common_metrics::inc;
use flate2::read::GzDecoder;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use serde_urlencoded;
use std::{
    collections::{HashMap, HashSet},
    net::IpAddr,
};
use std::{io::Read, sync::Arc};

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
    #[serde(alias = "v")]
    pub version: Option<String>,

    pub compression: Option<Compression>,

    #[serde(alias = "ver")]
    pub lib_version: Option<String>,

    #[serde(alias = "_")]
    pub sent_at: Option<i64>,
}

pub struct RequestContext {
    pub state: State<router::State>,
    pub ip: IpAddr,
    pub headers: HeaderMap,
    pub meta: FlagsQueryParams,
    pub body: Bytes,
}

pub struct FeatureFlagEvaluationContext {
    team_id: i32,
    project_id: i64,
    distinct_id: String,
    feature_flags: FeatureFlagList,
    reader: Arc<dyn Client + Send + Sync>,
    writer: Arc<dyn Client + Send + Sync>,
    cohort_cache: Arc<CohortCacheManager>,
    person_property_overrides: Option<HashMap<String, Value>>,
    group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
    groups: Option<HashMap<String, Value>>,
    hash_key_override: Option<String>,
}

impl FeatureFlagEvaluationContext {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        team_id: i32,
        project_id: i64,
        distinct_id: String,
        feature_flags: FeatureFlagList,
        reader: Arc<dyn Client + Send + Sync>,
        writer: Arc<dyn Client + Send + Sync>,
        cohort_cache: Arc<CohortCacheManager>,
        person_property_overrides: Option<HashMap<String, Value>>,
        group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
        groups: Option<HashMap<String, Value>>,
        hash_key_override: Option<String>,
    ) -> Self {
        Self {
            team_id,
            project_id,
            distinct_id,
            feature_flags,
            reader,
            writer,
            cohort_cache,
            person_property_overrides,
            group_property_overrides,
            groups,
            hash_key_override,
        }
    }
}

/// Process a feature flag request and return the evaluated flags
///
/// ## Flow
/// 1. Decodes and validates the request
/// 2. Extracts and verifies the authentication token
/// 3. Retrieves team information
/// 4. Processes person and group properties
/// 5. Retrieves feature flags
/// 6. Evaluates flags given all the relevant request context
///
/// ## Error Handling
/// - Returns early if any step fails
/// - Maintains error context through the FlagError enum
/// - Individual flag evaluation failures don't fail the entire request
pub async fn process_request(context: RequestContext) -> Result<FlagsResponse, FlagError> {
    // 1. Parse and authenticate request
    let (distinct_id, verified_token, request) = parse_and_authenticate_request(&context).await?;

    // 2. Get team
    let team = fetch_team(&context.state, &verified_token).await?;
    let team_id = team.id;
    let project_id = team.project_id;

    // 3. Prepare property overrides
    let (person_property_overrides, group_property_overrides, groups, hash_key_override) =
        prepare_properties(&context, &request)?;

    // 4. Fetch and filter flags
    let filtered_flags =
        fetch_and_filter_flags(&context.state, project_id, team_id, &request).await?;

    // 5. Evaluate flags
    let flags_response = evaluate_flags_for_request(
        &context.state,
        team_id,
        project_id,
        distinct_id,
        filtered_flags,
        person_property_overrides,
        group_property_overrides,
        groups,
        hash_key_override,
    )
    .await;

    Ok(flags_response)
}

/// Get person property overrides based on the request
/// - If geoip is enabled, fetch geoip properties and merge them with any person properties
/// - If geoip is disabled, return the person properties as is
/// - If no person properties are provided, return None
pub fn get_person_property_overrides(
    geoip_enabled: bool,
    person_properties: Option<HashMap<String, Value>>,
    ip: &IpAddr,
    geoip_service: &GeoIpClient,
) -> Option<HashMap<String, Value>> {
    match (geoip_enabled, person_properties) {
        (true, Some(mut props)) => {
            let geoip_props = geoip_service.get_geoip_properties(Some(&ip.to_string()));
            if !geoip_props.is_empty() {
                props.extend(geoip_props.into_iter().map(|(k, v)| (k, Value::String(v))));
            }
            Some(props)
        }
        (true, None) => {
            let geoip_props = geoip_service.get_geoip_properties(Some(&ip.to_string()));
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
        }
        (false, Some(props)) => Some(props),
        (false, None) => None,
    }
}

/// Decode a request into a `FlagRequest`
pub fn decode_request(
    headers: &HeaderMap,
    body: Bytes,
    query: &FlagsQueryParams,
) -> Result<FlagRequest, FlagError> {
    let content_type = headers
        .get("content-type")
        .map_or("unknown", |v| v.to_str().unwrap_or("unknown"));

    match content_type {
        "application/json" => {
            // Apply compression first if specified
            let decoded_body = match query.compression {
                Some(Compression::Gzip) => decompress_gzip(body)?,
                Some(Compression::Base64) => {
                    let decoded = general_purpose::STANDARD.decode(body).map_err(|e| {
                        FlagError::RequestDecodingError(format!("Base64 decoding error: {}", e))
                    })?;
                    Bytes::from(decoded)
                }
                Some(Compression::Unsupported) => {
                    return Err(FlagError::RequestDecodingError(
                        "Unsupported compression type".to_string(),
                    ))
                }
                None => body,
            };
            FlagRequest::from_bytes(decoded_body)
        }
        "application/json; encoding=base64" => {
            let decoded = general_purpose::STANDARD.decode(body).map_err(|e| {
                FlagError::RequestDecodingError(format!("Base64 decoding error: {}", e))
            })?;
            FlagRequest::from_bytes(Bytes::from(decoded))
        }
        "application/x-www-form-urlencoded" => {
            // For form data, first parse the form
            let form_data = String::from_utf8(body.to_vec()).map_err(|e| {
                FlagError::RequestDecodingError(format!("Invalid UTF-8 in form data: {}", e))
            })?;

            #[derive(Deserialize)]
            struct FormData {
                data: String,
            }

            let form: FormData = serde_urlencoded::from_str(&form_data).map_err(|e| {
                FlagError::RequestDecodingError(format!("Failed to parse form data: {}", e))
            })?;

            // URL-decode the data field
            let data = urlencoding::decode(&form.data)
                .map_err(|e| {
                    FlagError::RequestDecodingError(format!("Failed to URL-decode data: {}", e))
                })?
                .into_owned();

            // Now handle compression if specified
            let decoded = match query.compression {
                Some(Compression::Base64) | None => {
                    general_purpose::STANDARD.decode(data).map_err(|e| {
                        FlagError::RequestDecodingError(format!("Base64 decoding error: {}", e))
                    })?
                }
                Some(Compression::Gzip) => {
                    return Err(FlagError::RequestDecodingError(
                        "Gzip compression not supported for form-urlencoded data".to_string(),
                    ))
                }
                Some(Compression::Unsupported) => {
                    return Err(FlagError::RequestDecodingError(
                        "Unsupported compression type".to_string(),
                    ))
                }
            };

            FlagRequest::from_bytes(Bytes::from(decoded))
        }
        ct => Err(FlagError::RequestDecodingError(format!(
            "unsupported content type: {}",
            ct
        ))),
    }
}

/// Evaluate feature flags for a given distinct_id
/// - Returns a map of feature flag keys to their values
/// - If an error occurs while evaluating a flag, we'll set `errors_while_computing_flags` to true be logged,
///   and that flag will be omitted from the result (we will still attempt to evaluate other flags)
// TODO: it could be a cool idea to store the errors as a tuple instead of top-level, so that users can see
// which flags failed to evaluate
pub async fn evaluate_feature_flags(context: FeatureFlagEvaluationContext) -> FlagsResponse {
    let group_type_mapping_cache =
        GroupTypeMappingCache::new(context.project_id, context.reader.clone());

    let mut feature_flag_matcher = FeatureFlagMatcher::new(
        context.distinct_id,
        context.team_id,
        context.project_id,
        context.reader,
        context.writer,
        context.cohort_cache,
        Some(group_type_mapping_cache),
        context.groups,
    );
    feature_flag_matcher
        .evaluate_all_feature_flags(
            context.feature_flags,
            context.person_property_overrides,
            context.group_property_overrides,
            context.hash_key_override,
        )
        .await
}

async fn parse_and_authenticate_request(
    context: &RequestContext,
) -> Result<(String, String, FlagRequest), FlagError> {
    let RequestContext {
        headers,
        body,
        meta,
        ..
    } = context;

    let request = decode_request(headers, body.clone(), meta)?; // parse JSON, validate
    let distinct_id = request.extract_distinct_id()?;
    let token = request.extract_token()?;

    // verify token
    let flag_service = FlagService::new(context.state.redis.clone(), context.state.reader.clone());
    let verified_token = flag_service.verify_token(&token).await?;

    Ok((distinct_id, verified_token, request))
}

async fn fetch_team(state: &State<router::State>, verified_token: &str) -> Result<Team, FlagError> {
    let flag_service = FlagService::new(state.redis.clone(), state.reader.clone());
    let team = flag_service
        .get_team_from_cache_or_pg(verified_token)
        .await?;
    Ok(team)
}

fn prepare_properties(
    context: &RequestContext,
    request: &FlagRequest,
) -> Result<
    (
        Option<HashMap<String, Value>>, // person_property_overrides
        Option<HashMap<String, HashMap<String, Value>>>, // group_property_overrides
        Option<HashMap<String, Value>>, // groups
        Option<String>,                 // hash_key_override
    ),
    FlagError,
> {
    let ip = &context.ip;
    let state = &context.state;

    let person_property_overrides = get_person_property_overrides(
        !request.geoip_disable.unwrap_or(false),
        request.person_properties.clone(),
        ip,
        &state.geoip,
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

async fn fetch_and_filter_flags(
    state: &State<router::State>,
    project_id: i64,
    team_id: i32,
    request: &FlagRequest,
) -> Result<FeatureFlagList, FlagError> {
    let flag_service = FlagService::new(state.redis.clone(), state.reader.clone());

    // 1. Fetch flags from cache or DB
    let (all_flags, cache_hit) = flag_service
        .get_flags_from_cache_or_pg(project_id, &state.redis, &state.reader)
        .await?;

    // 2. Track cache hits vs misses
    inc(
        FLAG_CACHE_HIT_COUNTER,
        &[
            ("team_id".to_string(), team_id.to_string()),
            ("cache_hit".to_string(), cache_hit.to_string()),
        ],
        1,
    );

    // 3. If there are specific keys to filter on
    if let Some(flag_keys) = &request.flag_keys {
        let flag_keys_set: HashSet<String> = flag_keys.iter().cloned().collect();
        let filtered: Vec<FeatureFlag> = all_flags
            .flags
            .into_iter()
            .filter(|flag| flag_keys_set.contains(&flag.key))
            .collect();
        Ok(FeatureFlagList::new(filtered))
    } else {
        // No filtering needed
        Ok(all_flags)
    }
}

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
) -> FlagsResponse {
    let evaluation_context = FeatureFlagEvaluationContext::new(
        team_id,
        project_id,
        distinct_id,
        filtered_flags,
        state.reader.clone(),
        state.writer.clone(),
        state.cohort_cache_manager.clone(),
        person_property_overrides,
        group_property_overrides,
        groups,
        hash_key_override,
    );

    evaluate_feature_flags(evaluation_context).await
}

/// Processes group property overrides by combining existing overrides with group key overrides
///
/// When groups are provided in the format {"group_type": "group_key"}, we need to ensure these
/// are included in the group property overrides with the special "$group_key" property.
fn process_group_property_overrides(
    groups: Option<HashMap<String, Value>>,
    existing_overrides: Option<HashMap<String, HashMap<String, Value>>>,
) -> Option<HashMap<String, HashMap<String, Value>>> {
    match groups {
        Some(groups) => {
            let group_key_overrides: HashMap<String, HashMap<String, Value>> = groups
                .into_iter()
                .map(|(group_type, group_key)| {
                    let mut properties = existing_overrides
                        .as_ref()
                        .and_then(|g| g.get(&group_type))
                        .cloned()
                        .unwrap_or_default();

                    properties.insert("$group_key".to_string(), group_key);

                    (group_type, properties)
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

#[cfg(test)]
mod tests {
    use crate::{
        api::types::FlagValue,
        config::Config,
        flags::flag_models::{FeatureFlag, FlagFilters, FlagGroupType},
        properties::property_models::{OperatorType, PropertyFilter},
        utils::test_utils::{
            insert_new_team_in_pg, setup_pg_reader_client, setup_pg_writer_client,
        },
    };

    use super::*;
    use axum::http::HeaderMap;
    use serde_json::{json, Value};
    use std::net::{Ipv4Addr, Ipv6Addr};

    fn create_test_geoip_service() -> GeoIpClient {
        let config = Config::default_test_config();
        GeoIpClient::new(&config).expect("Failed to create GeoIpService for testing")
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
        let flag = FeatureFlag {
            name: Some("Test Flag".to_string()),
            id: 1,
            key: "test_flag".to_string(),
            active: true,
            deleted: false,
            team_id: 1,
            filters: FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "country".to_string(),
                        value: json!("US"),
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
            },
            ensure_experience_continuity: false,
        };

        let feature_flag_list = FeatureFlagList { flags: vec![flag] };

        let mut person_properties = HashMap::new();
        person_properties.insert("country".to_string(), json!("US"));

        let evaluation_context = FeatureFlagEvaluationContext::new(
            1,
            1,
            "user123".to_string(),
            feature_flag_list,
            reader,
            writer,
            cohort_cache,
            Some(person_properties),
            None,
            None,
            None,
        );

        let result = evaluate_feature_flags(evaluation_context).await;

        assert!(!result.errors_while_computing_flags);
        assert!(result.feature_flags.contains_key("test_flag"));
        assert_eq!(result.feature_flags["test_flag"], FlagValue::Boolean(true));
    }

    #[test]
    fn test_decode_request() {
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());
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
        headers.insert("content-type", "application/json".parse().unwrap());
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
        headers.insert("content-type", "application/json".parse().unwrap());
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
        headers.insert("content-type", "text/plain".parse().unwrap());
        let body = Bytes::from_static(b"test");
        let meta = FlagsQueryParams::default();

        let result = decode_request(&headers, body, &meta);
        assert!(matches!(result, Err(FlagError::RequestDecodingError(_))));
    }

    #[test]
    fn test_decode_request_malformed_json() {
        let mut headers = HeaderMap::new();
        headers.insert("content-type", "application/json".parse().unwrap());
        let body = Bytes::from_static(b"{invalid json}");
        let meta = FlagsQueryParams::default();

        let result = decode_request(&headers, body, &meta);
        assert!(result.is_err(), "Expected an error, but got Ok");
    }

    #[test]
    fn test_decode_request_form_urlencoded() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "content-type",
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

    #[tokio::test]
    async fn test_evaluate_feature_flags_multiple_flags() {
        let reader: Arc<dyn Client + Send + Sync> = setup_pg_reader_client(None).await;
        let writer: Arc<dyn Client + Send + Sync> = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let flags = vec![
            FeatureFlag {
                name: Some("Flag 1".to_string()),
                id: 1,
                key: "flag_1".to_string(),
                active: true,
                deleted: false,
                team_id: 1,
                filters: FlagFilters {
                    groups: vec![FlagGroupType {
                        properties: Some(vec![]),
                        rollout_percentage: Some(100.0),
                        variant: None,
                    }],
                    multivariate: None,
                    aggregation_group_type_index: None,
                    payloads: None,
                    super_groups: None,
                },
                ensure_experience_continuity: false,
            },
            FeatureFlag {
                name: Some("Flag 2".to_string()),
                id: 2,
                key: "flag_2".to_string(),
                active: true,
                deleted: false,
                team_id: 1,
                filters: FlagFilters {
                    groups: vec![FlagGroupType {
                        properties: Some(vec![]),
                        rollout_percentage: Some(0.0),
                        variant: None,
                    }],
                    multivariate: None,
                    aggregation_group_type_index: None,
                    payloads: None,
                    super_groups: None,
                },
                ensure_experience_continuity: false,
            },
        ];

        let feature_flag_list = FeatureFlagList { flags };

        let evaluation_context = FeatureFlagEvaluationContext::new(
            1,
            1,
            "user123".to_string(),
            feature_flag_list,
            reader,
            writer,
            cohort_cache,
            None,
            None,
            None,
            None,
        );

        let result = evaluate_feature_flags(evaluation_context).await;

        assert!(!result.errors_while_computing_flags);
        assert_eq!(result.feature_flags["flag_1"], FlagValue::Boolean(true));
        assert_eq!(result.feature_flags["flag_2"], FlagValue::Boolean(false));
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
                groups: vec![FlagGroupType {
                    properties: Some(vec![PropertyFilter {
                        key: "industry".to_string(),
                        value: json!("tech"),
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
            },
            ensure_experience_continuity: false,
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

        let evaluation_context = FeatureFlagEvaluationContext::new(
            team.id,
            team.project_id,
            "user123".to_string(),
            feature_flag_list,
            reader,
            writer,
            cohort_cache,
            None,
            Some(group_property_overrides),
            Some(groups),
            None,
        );

        let result = evaluate_feature_flags(evaluation_context).await;

        println!("result: {:?}", result);

        assert!(
            !result.errors_while_computing_flags,
            "Error while computing flags"
        );
        assert!(
            result.feature_flags.contains_key("test_flag"),
            "test_flag not found in result"
        );

        let flag_value = result
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
        let long_id = "a".repeat(1000);
        let reader: Arc<dyn Client + Send + Sync> = setup_pg_reader_client(None).await;
        let writer: Arc<dyn Client + Send + Sync> = setup_pg_writer_client(None).await;
        let cohort_cache = Arc::new(CohortCacheManager::new(reader.clone(), None, None));
        let flag = FeatureFlag {
            name: Some("Test Flag".to_string()),
            id: 1,
            key: "test_flag".to_string(),
            active: true,
            deleted: false,
            team_id: 1,
            filters: FlagFilters {
                groups: vec![FlagGroupType {
                    properties: Some(vec![]),
                    rollout_percentage: Some(100.0),
                    variant: None,
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
            },
            ensure_experience_continuity: false,
        };

        let feature_flag_list = FeatureFlagList { flags: vec![flag] };

        let evaluation_context = FeatureFlagEvaluationContext::new(
            1,
            1,
            long_id,
            feature_flag_list,
            reader,
            writer,
            cohort_cache,
            None,
            None,
            None,
            None,
        );

        let result = evaluate_feature_flags(evaluation_context).await;

        assert!(!result.errors_while_computing_flags);
        assert_eq!(result.feature_flags["test_flag"], FlagValue::Boolean(true));
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
}
