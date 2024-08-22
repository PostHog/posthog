use crate::{
    api::{FlagError, FlagValue, FlagsResponse},
    database::Client,
    flag_definitions::FeatureFlagList,
    flag_matching::FeatureFlagMatcher,
    flag_request::FlagRequest,
    geoip::get_geoip_properties,
    router,
};
use axum::{extract::State, http::HeaderMap};
use bytes::Bytes;
use serde::Deserialize;
use serde_json::Value;
use std::sync::Arc;
use std::{collections::HashMap, net::IpAddr};
use tracing::{error, warn};

#[derive(Deserialize, Default)]
pub enum Compression {
    #[default]
    Unsupported,
    #[serde(rename = "gzip", alias = "gzip-js")]
    Gzip,
}

impl Compression {
    pub fn as_str(&self) -> &'static str {
        match self {
            Compression::Gzip => "gzip",
            Compression::Unsupported => "unsupported",
        }
    }
}

#[derive(Deserialize, Default)]
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
    pub meta: FlagsQueryParams,
    pub headers: HeaderMap,
    pub body: Bytes,
}

pub async fn process_request(context: RequestContext) -> Result<FlagsResponse, FlagError> {
    let RequestContext {
        state,
        ip,
        meta: _, // TODO use this
        headers,
        body,
    } = context;

    let request = decode_request(&headers, body)?;
    let token = request
        .extract_and_verify_token(state.redis.clone(), state.postgres.clone())
        .await?;
    let team = request
        .get_team_from_cache_or_pg(&token, state.redis.clone(), state.postgres.clone())
        .await?;
    let distinct_id = request.extract_distinct_id()?;
    let geoip_enabled = request.geoip_disable.unwrap_or(true);
    let person_properties = request.person_properties.clone();

    let person_property_overrides =
        extend_person_properties(person_properties, &ip.to_string(), geoip_enabled);

    // let group_property_overrides = request.group_properties.clone();

    let all_feature_flags = request
        .get_flags_from_cache_or_pg(team.id, state.redis.clone(), state.postgres.clone())
        .await?;

    let flags_response = evaluate_feature_flags(
        distinct_id,
        all_feature_flags,
        Some(state.postgres.clone()),
        person_property_overrides,
        // group_property_overrides,
    )
    .await;

    return Ok(flags_response);
}

fn decode_request(headers: &HeaderMap, body: Bytes) -> Result<FlagRequest, FlagError> {
    match headers
        .get("content-type")
        .map_or("", |v| v.to_str().unwrap_or(""))
    {
        "application/json" => FlagRequest::from_bytes(body),
        ct => Err(FlagError::RequestDecodingError(format!(
            "unsupported content type: {}",
            ct
        ))),
    }
}

pub fn extend_person_properties(
    person_properties: Option<HashMap<String, Value>>,
    ip: &str,
    geoip_enabled: bool,
) -> Option<HashMap<String, Value>> {
    let mut extended_properties = person_properties;

    if geoip_enabled {
        let geoip_properties: HashMap<String, String> = get_geoip_properties(Some(ip));
        match extended_properties {
            Some(ref mut props) => {
                props.extend(
                    geoip_properties
                        .into_iter()
                        .map(|(k, v)| (k, Value::String(v))),
                );
            }
            None => {
                // Create a new HashMap with Value type
                extended_properties = Some(
                    geoip_properties
                        .into_iter()
                        .map(|(k, v)| (k, Value::String(v)))
                        .collect(),
                );
            }
        }
    }

    extended_properties
}

pub async fn evaluate_feature_flags(
    distinct_id: String,
    feature_flag_list: FeatureFlagList,
    database_client: Option<Arc<dyn Client + Send + Sync>>,
    person_property_overrides: Option<HashMap<String, Value>>,
    // group_property_overrides: Option<HashMap<String, HashMap<String, Value>>>,
) -> FlagsResponse {
    let mut matcher = FeatureFlagMatcher::new(
        distinct_id.clone(),
        database_client,
        person_property_overrides,
        // group_property_overrides,
    );
    let mut feature_flags = HashMap::new();
    let mut error_while_computing_flags = false;
    let all_feature_flags = feature_flag_list.flags;

    for flag in all_feature_flags {
        if !flag.active || flag.deleted {
            continue;
        }

        let flag_match = matcher.get_match(&flag).await;

        let flag_value = if flag_match.matches {
            match flag_match.variant {
                Some(variant) => FlagValue::String(variant),
                None => FlagValue::Boolean(true),
            }
        } else {
            FlagValue::Boolean(false)
        };

        feature_flags.insert(flag.key.clone(), flag_value);

        if let Err(e) = matcher
            .get_person_properties_from_cache_or_db(flag.team_id, distinct_id.clone())
            .await
        {
            error_while_computing_flags = true;
            error!(
                "Error fetching properties for feature flag '{}' and distinct_id '{}': {:?}",
                flag.key, distinct_id, e
            );
        }
    }

    if error_while_computing_flags {
        warn!(
            "Errors occurred while computing feature flags for distinct_id '{}'",
            distinct_id
        );
    }

    FlagsResponse {
        error_while_computing_flags,
        feature_flags,
    }
}
