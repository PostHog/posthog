use crate::{
    api::v1::query::{Manager, PropDefResponse},
    api::v1::constants::*,
    //metrics_consts::{},
};

use axum::{
    extract::{Path, Query, State},
    routing::get,
    Json, Router,
};

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
        Some(s) if PARENT_PROPERTY_TYPES.iter().any(|pt| *pt == s) => Some(*s),
        _ => None,
    };

    // default to -1 if this is missing or present but invalid
    let group_type_index: i32 = match params.get("group_type_index") {
        Some(s) => match s.parse::<i32>().ok() {
            Some(gti)
                if property_type.is_some_and(|pt| pt == "group")
                    && gti >= 0 && gti < GROUP_TYPE_LIMIT => gti,
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
        _ => None
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
            _ => DEFAULT_QUERY_LIMIT
        }
        _ => DEFAULT_QUERY_LIMIT
    };

    let offset: i32 = match params.get("offset") {
        Some(s) => match s.parse::<i32>().ok() {
            Some(val) => val,
            _ => DEFAULT_QUERY_OFFSET
        }
        _ => DEFAULT_QUERY_OFFSET
    };

    let order_by_verified = true; // default behavior

    // construct the count query
    let count_query = qmgr
        .count_query(
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
    let mut props_query = qmgr
        .property_definitions_query(
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

    // TODO: execute queries, build result structs

    // TODO: Implement!
    Json(PropDefResponse {})
}

