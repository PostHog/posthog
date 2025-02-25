use crate::{
    api::v1::{constants::*, query::Manager},
    //metrics_consts::{},
    types::PropertyParentType,
};

use axum::{
    extract::{OriginalUri, Path, Query, State},
    http::{StatusCode, Uri},
    routing::get,
    Json, Router,
};
use serde::Serialize;
use sqlx::{Executor, Row};
use tracing::{error, warn};
use url::form_urlencoded;

use std::collections::{HashMap, HashSet};
use std::error;
use std::fmt;
use std::sync::Arc;

pub fn apply_routes(parent: Router, qmgr: Arc<Manager>) -> Router {
    let api_router = Router::new()
        .route(
            "/projects/:project_id/property_definitions",
            get(project_property_definitions_handler),
        )
        .with_state(qmgr);

    parent.nest("/api/v1", api_router)
}

async fn project_property_definitions_handler(
    State(qmgr): State<Arc<Manager>>,
    OriginalUri(uri): OriginalUri,
    Path(project_id): Path<i32>,
    Query(params): Query<HashMap<String, String>>,
) -> Result<Json<PropDefResponse>, StatusCode> {
    // parse and validate request's query params
    let params = parse_request(params);
    if let Err(e) = params.valid() {
        error!("invalid request parameter: {:?}", e);
        return Err(StatusCode::BAD_REQUEST);
    }

    // construct the count query
    let mut count_query_bldr = qmgr.count_query(project_id, &params);
    let count_dbg: String = count_query_bldr.sql().into();
    let count_query = count_query_bldr.build();

    // construct the property definitions query
    let mut props_query_bldr = qmgr.property_definitions_query(project_id, &params);
    let props_dbg: String = props_query_bldr.sql().into();
    let props_query = props_query_bldr.build();

    // TODO(eli): DEBUG
    warn!("COUNT QUERY: {:?}", &count_dbg);
    warn!("PROPS QUERY: {:?}", &props_dbg);

    let total_count: i64 = match qmgr.pool.fetch_one(count_query).await {
        Ok(row) => row.get(0),
        Err(_e) => {
            //panic!("COUNT QUERY ERROR: {:?}", e);
            return Err(StatusCode::INTERNAL_SERVER_ERROR);
        }
    };

    match qmgr.pool.fetch_all(props_query).await {
        Ok(result) => {
            for _row in result {
                // TODO: populate PropDefResponse.results entries!!!
            }
        }
        Err(_e) => {
            //panic!("PROPS QUERY ERROR: {:?}", e);
            return Err(StatusCode::INTERNAL_SERVER_ERROR);
        }
    }

    let (prev_url, next_url) = gen_next_prev_urls(uri, total_count, params.limit, params.offset);

    // execute the queries, and populate the response
    let out = PropDefResponse {
        count: total_count,
        next: next_url,
        prev: prev_url,
        results: vec![],
    };

    Ok(Json(out))
}

fn parse_request(params: HashMap<String, String>) -> Params {
    // parse the request parameters; use Option<T> to track presence for query step
    let search_terms: Option<Vec<String>> = params.get("search").map(|raw| {
        raw.split(" ")
            .map(|s| s.trim().to_string().to_lowercase())
            .collect()
    });

    // TODO: this can be parameterized in the orig Django query but
    // I didn't see any evidence of that happening in the code yet
    let search_fields: HashSet<String> = params
        .get("search_fields")
        .map(|raw| {
            raw.split(',')
                .map(|s| s.trim().to_string().to_lowercase())
                .collect()
        })
        .unwrap_or_default();
    let mut search_fields = search_fields;
    search_fields.insert("name".to_string());

    // default value is "event" type
    let property_type =
        params
            .get("type")
            .map_or(PropertyParentType::Event, |s| match s.as_str() {
                "event" => PropertyParentType::Event,
                "person" => PropertyParentType::Person,
                "group" => PropertyParentType::Group,
                "session" => PropertyParentType::Session,
                _ => PropertyParentType::Event,
            });

    // default to -1 if this is missing or present but invalid
    let group_type_index: i32 = params.get("group_type_index").map_or(-1, |s| {
        s.parse::<i32>().ok().map_or(-1, |gti| {
            if property_type == PropertyParentType::Group && (1..GROUP_TYPE_LIMIT).contains(&gti) {
                gti
            } else {
                -1
            }
        })
    });

    let properties = params
        .get("properties")
        .map(|raw| raw.split(",").map(|s| s.trim().to_string()).collect());

    let is_numerical = params
        .get("is_numerical")
        .and_then(|s| s.parse::<bool>().ok());

    let is_feature_flag = params
        .get("is_feature_flag")
        .and_then(|s| s.parse::<bool>().ok());

    let excluded_properties = params
        .get("excluded_properties")
        .map(|raw| raw.split(",").map(|s| s.trim().to_string()).collect());

    // this must be calculated on the Django (caller) side and passed to this API.
    // it allows us to decide the base table to select from in our property defs queries
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L463
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L504-L508
    let use_enterprise_taxonomy = params
        .get("use_enterprise_taxonomy")
        .and_then(|s| s.parse::<bool>().ok());

    let filter_by_event_names = params
        .get("filter_by_event_names")
        .and_then(|s| s.parse::<bool>().ok());

    // IMPORTANT: this is passed to the Django API as JSON but probably doesn't
    // matter how we pass it from Django to this service, so it's a CSV for now.
    // is this a mistake? TBD, revisit and see below:
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L214
    let event_names = params
        .get("event_names")
        .map(|raw| raw.split(",").map(|s| s.trim().to_string()).collect());

    let limit: i32 = params.get("limit").map_or(DEFAULT_QUERY_LIMIT, |s| {
        s.parse::<i32>().unwrap_or(DEFAULT_QUERY_LIMIT)
    });

    let offset: i32 = params.get("offset").map_or(DEFAULT_QUERY_OFFSET, |s| {
        s.parse::<i32>().unwrap_or(DEFAULT_QUERY_OFFSET)
    });

    // TODO: should this be a request param? not overridden in Django query
    let order_by_verified = true;

    Params {
        search_terms,
        search_fields,
        property_type,
        group_type_index,
        properties,
        excluded_properties,
        event_names,
        is_feature_flag,
        is_numerical,
        use_enterprise_taxonomy,
        filter_by_event_names,
        order_by_verified,
        limit,
        offset,
    }
}

fn gen_next_prev_urls(
    uri: Uri,
    total_count: i64,
    curr_limit: i32,
    curr_offset: i32,
) -> (Option<String>, Option<String>) {
    let next_offset = curr_offset + curr_limit;
    let prev_offset = curr_offset - curr_limit;

    (
        gen_url(uri.clone(), total_count, prev_offset),
        gen_url(uri.clone(), total_count, next_offset),
    )
}

fn gen_url(uri: Uri, total_count: i64, new_offset: i32) -> Option<String> {
    if new_offset < 0 || new_offset as i64 > total_count {
        return None;
    }

    // Parse the query parameters
    let mut query_params = uri
        .query()
        .map(|query| {
            form_urlencoded::parse(query.as_bytes())
                .into_owned()
                .collect::<HashMap<String, String>>()
        })
        .unwrap_or_default();

    // Modify a single query parameter
    query_params.insert("offset".to_string(), new_offset.to_string());

    // Rebuild the Uri with the modified query parameters
    let new_query = form_urlencoded::Serializer::new(String::new())
        .extend_pairs(query_params)
        .finish();

    // Replace the original query with the modified query
    let base_uri = uri
        .clone()
        .into_parts()
        .path_and_query
        .unwrap()
        .path()
        .to_string();
    let uri = Uri::builder()
        .scheme(uri.scheme().unwrap().as_str())
        .authority(uri.authority().unwrap().as_str())
        .path_and_query(base_uri + "?" + &new_query)
        .build()
        .unwrap();

    Some(uri.to_string())
}

pub struct Params {
    pub search_terms: Option<Vec<String>>,
    pub search_fields: HashSet<String>,
    pub property_type: PropertyParentType,
    pub group_type_index: i32,
    pub properties: Option<Vec<String>>,
    pub excluded_properties: Option<Vec<String>>,
    pub event_names: Option<Vec<String>>,
    pub is_feature_flag: Option<bool>,
    pub is_numerical: Option<bool>,
    pub use_enterprise_taxonomy: Option<bool>,
    pub filter_by_event_names: Option<bool>,
    pub order_by_verified: bool,
    pub limit: i32,
    pub offset: i32,
}

impl Params {
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L81-L96
    pub fn valid(&self) -> Result<(), InvalidParamError> {
        if self.property_type == PropertyParentType::Group && self.group_type_index <= 0 {
            return Err(InvalidParamError(
                "property_type 'group' requires 'group_type_index' parameter".to_string(),
            ));
        }

        if self.property_type != PropertyParentType::Group && self.group_type_index != -1 {
            return Err(InvalidParamError(
                "parameter 'group_type_index' is only allowed with property_type 'group'"
                    .to_string(),
            ));
        }

        if self.event_names.as_ref().is_some_and(|ens| !ens.is_empty())
            && self.property_type != PropertyParentType::Event
        {
            return Err(InvalidParamError(
                "parameter 'event_names' is only allowed with property_type 'event'".to_string(),
            ));
        }

        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct InvalidParamError(String);
impl error::Error for InvalidParamError {}

impl fmt::Display for InvalidParamError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "invalid request parameter: {}", self.0)
    }
}

#[derive(Serialize)]
pub struct PropDefResponse {
    count: i64,
    next: Option<String>,
    prev: Option<String>,
    results: Vec<PropDef>,
}

#[derive(Serialize)]
pub struct PropDef {
    id: String,
    name: String,
    description: String,
    is_numeric: bool,
    updated_at: String, // UTC ISO8601
    updated_by: Person,
    is_seen_on_filtered_events: Option<String>, // VALIDATE THIS!
    property_type: i32,
    verified: bool,
    verified_at: String, // UTC ISO8601
    verified_by: Person,
    tags: Vec<String>,
}

#[derive(Serialize)]
pub struct Person {
    id: u32,
    uuid: String,
    distinct_id: String,
    first_name: String,
    last_name: String,
    email: String,
    is_email_verified: bool,
    hedgehog_config: HedgehogConfig,
}

#[derive(Serialize)]
pub struct HedgehogConfig {
    use_as_profile: bool,
    color: String,
    accessories: Vec<String>,
    role_at_organization: Option<String>,
}
