use crate::{
    api::v1::constants::*,
    //metrics_consts::{},
    api::v1::query::Manager,
};

use axum::{
    extract::{OriginalUri, Path, Query, State},
    http::Uri,
    routing::get,
    Json, Router,
};
use serde::Serialize;
use sqlx::{Executor, Row};
use url::form_urlencoded;

use std::collections::HashMap;
use std::sync::Arc;

pub fn apply_routes(parent: Router, qmgr: Arc<Manager>) -> Router {
    let api_router = Router::new()
        .route(
            "projects/{project_id}/property_definitions/",
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
) -> Json<PropDefResponse> {
    // parse the request parameters; use Option<T> to track presence for query step
    let search: Option<Vec<String>> = match params.get("search") {
        Some(raw) => Some(
            raw.split(" ")
                .map(|s| s.trim().to_string().to_lowercase())
                .collect(),
        ),
        _ => None,
    };

    let property_type = match params.get("type") {
        Some(s) if PARENT_PROPERTY_TYPES.iter().any(|pt| *pt == s) => Some(s.clone()),
        _ => None,
    };

    // default to -1 if this is missing or present but invalid
    let group_type_index: i32 = match params.get("group_type_index") {
        Some(s) => match s.parse::<i32>().ok() {
            Some(gti)
                if property_type.as_ref().is_some_and(|pt| pt == "group")
                    && gti >= 0
                    && gti < GROUP_TYPE_LIMIT =>
            {
                gti
            }
            _ => -1,
        },
        _ => -1,
    };

    let properties = match params.get("properties") {
        Some(raw) => Some(raw.split(",").map(|s| s.trim().to_string()).collect()),
        _ => None,
    };

    let is_numerical = match params.get("is_numerical") {
        Some(s) => s.parse::<bool>().ok(),
        _ => None,
    };

    let is_feature_flag: Option<bool> = match params.get("is_feature_flag") {
        Some(s) => s.parse::<bool>().ok(),
        _ => None,
    };

    let excluded_properties = match params.get("excluded_properties") {
        Some(raw) => Some(raw.split(",").map(|s| s.trim().to_string()).collect()),
        _ => None,
    };

    // this must be calculated on the Django (caller) side and passed to this API.
    // it allows us to decide the base table to select from in our property defs queries
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L463
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L504-L508
    let use_enterprise_taxonomy = match params.get("use_enterprise_taxonomy") {
        Some(s) => s.parse::<bool>().ok(),
        _ => None,
    };

    let filter_by_event_names: Option<bool> = match params.get("filter_by_event_names") {
        Some(s) => s.parse::<bool>().ok(),
        _ => None,
    };

    // IMPORTANT: this is passed to the Django API as JSON but probably doesn't
    // matter how we pass it from Django to this service, so it's a CSV for now.
    // is this a mistake? TBD, revisit and see below:
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L214
    let event_names = match params.get("event_names") {
        Some(raw) => Some(raw.split(",").map(|s| s.trim().to_string()).collect()),
        _ => None,
    };

    let limit: i32 = match params.get("limit") {
        Some(s) => match s.parse::<i32>().ok() {
            Some(val) => val,
            _ => DEFAULT_QUERY_LIMIT,
        },
        _ => DEFAULT_QUERY_LIMIT,
    };

    let offset: i32 = match params.get("offset") {
        Some(s) => match s.parse::<i32>().ok() {
            Some(val) => val,
            _ => DEFAULT_QUERY_OFFSET,
        },
        _ => DEFAULT_QUERY_OFFSET,
    };

    let order_by_verified = true; // default behavior

    // construct the count query
    let count_query = qmgr.count_query(
        project_id,
        &search,
        &property_type,
        group_type_index,
        &properties,
        &excluded_properties,
        &event_names,
        &is_feature_flag,
        &is_numerical,
        &use_enterprise_taxonomy,
        &filter_by_event_names,
    );

    // construct the property definitions query
    let props_query = qmgr.property_definitions_query(
        project_id,
        &search,
        &property_type,
        group_type_index,
        &properties,
        &excluded_properties,
        &event_names,
        &is_feature_flag,
        &is_numerical,
        &use_enterprise_taxonomy,
        &filter_by_event_names,
        order_by_verified,
        limit,
        offset,
    );

    let total_count: i32 = match qmgr.pool.fetch_one(count_query.as_str()).await {
        Ok(row) => row.get(0),
        Err(e) => unimplemented!("TODO: handle count query error!"),
    };

    match qmgr.pool.fetch_all(props_query.as_str()).await {
        Ok(result) => {
            for row in result {
                // TODO: populate PropDefResponse.results entries!!!
            }
        }
        Err(e) => unimplemented!("TODO: handle props query error!"),
    }

    let (prev_url, next_url) = gen_next_prev_urls(uri, total_count, limit, offset);

    // execute the queries, and populate the response
    let mut out = PropDefResponse {
        count: total_count as u32,
        next: next_url,
        prev: prev_url,
        results: vec![],
    };

    Json(out)
}

fn gen_next_prev_urls(
    uri: Uri,
    total_count: i32,
    curr_limit: i32,
    curr_offset: i32,
) -> (Option<String>, Option<String>) {
    let next_offset = curr_limit + curr_offset;
    let prev_offset = curr_offset - curr_limit;

    (
        gen_url(uri.clone(), total_count, prev_offset),
        gen_url(uri.clone(), total_count, next_offset),
    )
}

fn gen_url(uri: Uri, total_count: i32, new_offset: i32) -> Option<String> {
    if new_offset < 0 || new_offset >= total_count {
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
    query_params.insert("offset".to_string(), "new_value".to_string());

    // Rebuild the Uri with the modified query parameters
    let new_query = form_urlencoded::Serializer::new(String::new())
        .extend_pairs(query_params.into_iter())
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
        .scheme(uri.scheme().clone().unwrap().as_str())
        .authority(uri.authority().cloned().unwrap().as_str())
        .path_and_query(base_uri + "?" + &new_query)
        .build()
        .unwrap();

    Some(uri.to_string())
}

#[derive(Serialize)]
pub struct PropDefResponse {
    count: u32,
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
    property_type: String,
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
