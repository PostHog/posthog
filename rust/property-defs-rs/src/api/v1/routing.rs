use crate::{
    api::v1::{constants::*, errors::ApiError, query::Manager},
    types::PropertyParentType,
    //metrics_consts::{},
    AppContext,
};

use anyhow::Result;
use axum::{
    extract::{OriginalUri, Path, Query, State},
    http::{
        uri::{Authority, Scheme},
        Uri,
    },
    routing::get,
    Json, Router,
};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::{Execute, Executor, FromRow, Postgres, QueryBuilder, Row};
use tracing::debug;
use url::form_urlencoded;

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

pub fn apply_routes(parent: Router, app_ctx: Arc<AppContext>) -> Router {
    let api_router = Router::new()
        .route(
            "/projects/:project_id/property_definitions",
            get(project_property_definitions_handler),
        )
        .with_state(app_ctx);

    parent.nest("/api/v1", api_router)
}

async fn project_property_definitions_handler(
    State(app_ctx): State<Arc<AppContext>>,
    OriginalUri(uri): OriginalUri,
    Path(project_id): Path<i32>,
    Query(params): Query<HashMap<String, String>>,
) -> Result<Json<PropertyDefinitionResponse>, ApiError> {
    // parse and validate request's query params
    let params = parse_request(params);
    params.valid()?;
    debug!(
        "Request for project_id({}) w/params: {:?}",
        project_id, &params
    );

    let qmgr: &Manager = &app_ctx.query_manager;

    // construct the count query
    let mut count_bldr = QueryBuilder::<Postgres>::new("");
    let count_query = qmgr.count_query(&mut count_bldr, project_id, &params);
    let count_dbg: String = count_query.sql().into();
    debug!("Count query: {:?}", &count_dbg);

    // construct the property definitions query
    let mut props_bldr = QueryBuilder::<Postgres>::new("");
    let props_query = qmgr.property_definitions_query(&mut props_bldr, project_id, &params);
    let props_dbg: String = props_query.sql().into();
    debug!("Prop defs query: {:?}", &props_dbg);

    let total_count: i64 = match qmgr.pool.fetch_one(count_query).await {
        Ok(row) => row.get(0),
        Err(e) => {
            return Err(ApiError::QueryError(format!(
                "executing count query: {}",
                e
            )))
        }
    };

    let mut prop_defs: Vec<PropertyDefinition> = vec![];
    match qmgr.pool.fetch_all(props_query).await {
        Ok(result) => {
            for row in result {
                let pd = PropDefRow::from_row(&row).map_err(|e| {
                    ApiError::QueryError(format!("deserializing prop defs row: {}", e))
                })?;
                prop_defs.push(pd.into());
            }
        }
        Err(e) => {
            return Err(ApiError::QueryError(format!(
                "executing prop defs query: {}",
                e
            )))
        }
    }

    // TODO: since this is an internal API, and using the incoming URI
    // will likely not behave as expected for building user-visible
    // next/prev URIs, we could return next limit/offset instead
    // and let the caller (Django) build the URIs for responses?
    let (prev_url, next_url) = gen_next_prev_urls(uri, total_count, params.limit, params.offset);

    // execute the queries, and populate the response
    let out = PropertyDefinitionResponse {
        count: total_count,
        next: next_url,
        prev: prev_url,
        results: prop_defs,
    };

    Ok(Json(out))
}

fn parse_request(params: HashMap<String, String>) -> Params {
    // search terms: optional - each term is a fragment that will be
    // fuzzy-searched in Postgres against the specified search fields
    // DIVERGES FROM DJANGO API: the new Rust API will accept lists as space-separated query param values
    let search_terms: Vec<String> = params
        .get("search")
        .map(|raw| {
            raw.split(" ")
                .map(|s| s.trim().to_string().to_lowercase())
                .collect()
        })
        .unwrap_or_default();

    // which columns should we fuzzy-search for each of the user-supplied search terms?
    // defaults to "posthog_propertydefinition.name" column, but user can supply more
    // DIVERGES FROM DJANGO API: the new Rust API will accept lists as space-separated query param values
    let search_fields: HashSet<String> = HashSet::from([
        "name".to_string(), // this is the default value, always include it
        params
            .get("search_fields")
            .map(|raw| {
                raw.split(" ")
                    .map(|s| s.trim().to_string().to_lowercase())
                    .collect()
            })
            .unwrap_or_default(),
    ]);

    // which category of properties do we filter for? default is "event"
    let parent_type = params
        .get("type")
        .map_or(PropertyParentType::Event, |s| match s.as_str() {
            "event" => PropertyParentType::Event,
            "person" => PropertyParentType::Person,
            "group" => PropertyParentType::Group,
            "session" => PropertyParentType::Session,
            _ => PropertyParentType::Event,
        });

    // defaults to "-1" if the caller didn't supply the group_type_index, or the parent_type != "group"
    let group_type_index: i32 = params.get("group_type_index").map_or(-1, |s| {
        s.parse::<i32>().ok().map_or(-1, |gti| {
            if parent_type == PropertyParentType::Group && (1..GROUP_TYPE_LIMIT).contains(&gti) {
                gti
            } else {
                -1
            }
        })
    });

    // DIVERGES FROM DJANGO API: the new Rust API will accept lists as space-separated query param values
    let properties: Vec<String> = params
        .get("properties")
        .map(|raw| raw.split(" ").map(|s| s.trim().to_string()).collect())
        .unwrap_or_default();

    let is_numerical = params
        .get("is_numerical")
        .and_then(|s| s.parse::<bool>().ok())
        .unwrap_or(false);

    // false is not equivalent of absence here so make this an Option
    let is_feature_flag = params
        .get("is_feature_flag")
        .and_then(|s| s.parse::<bool>().ok());

    // DIVERGES FROM DJANGO API: the new Rust API will accept lists as space-separated query param values
    let excluded_properties = params
        .get("excluded_properties")
        .map(|raw| raw.split(" ").map(|s| s.trim().to_string()).collect())
        .unwrap_or_default();

    // NOTE: this is calculated using the User model in the Django app, so probably easiest to
    // to just pass the result of those checks from the caller (Django) to this API? the flag decides
    // if the props def query should join in enterprise prop defs and (indirectly) the users table.
    // defaulting to true for now, but TBD if this is in parity w/original yet. see also:
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L463
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L504-L508
    let use_enterprise_taxonomy = params
        .get("use_enterprise_taxonomy")
        .and_then(|s| s.parse::<bool>().ok())
        .unwrap_or(true);

    // DIVERGES FROM DJANGO API: the new Rust API will accept lists as space-separated query param values
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L214
    let event_names = params
        .get("event_names")
        .map(|raw| raw.split(" ").map(|s| s.trim().to_string()).collect())
        .unwrap_or_default();

    let limit: i64 = params.get("limit").map_or(DEFAULT_QUERY_LIMIT, |s| {
        s.parse::<i64>().unwrap_or(DEFAULT_QUERY_LIMIT)
    });

    let offset: i64 = params.get("offset").map_or(DEFAULT_QUERY_OFFSET, |s| {
        s.parse::<i64>().unwrap_or(DEFAULT_QUERY_OFFSET)
    });

    Params {
        search_terms,
        search_fields,
        parent_type,
        group_type_index,
        properties,
        excluded_properties,
        event_names,
        is_feature_flag,
        is_numerical,
        use_enterprise_taxonomy,
        limit,
        offset,
    }
}

fn gen_next_prev_urls(
    uri: Uri,
    total_count: i64,
    curr_limit: i64,
    curr_offset: i64,
) -> (Option<String>, Option<String>) {
    let next_offset = curr_offset + curr_limit;
    let prev_offset = curr_offset - curr_limit;

    (
        gen_url(uri.clone(), total_count, curr_limit, prev_offset),
        gen_url(uri.clone(), total_count, curr_limit, next_offset),
    )
}

// TODO: since this is an internal API to be called by Django, we will
// probably eliminate this in favor of letting the PropertyDefinitionsViewSet
// handling next & prev URI generation...
fn gen_url(uri: Uri, total_count: i64, curr_limit: i64, new_offset: i64) -> Option<String> {
    if new_offset < 0 || new_offset > total_count {
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

    // Modify limit and offset params only
    query_params.insert("offset".to_string(), new_offset.to_string());
    query_params.insert("limit".to_string(), curr_limit.to_string());

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
        .scheme(uri.scheme().unwrap_or(&Scheme::HTTP).as_str())
        .authority(
            uri.authority()
                .unwrap_or(&Authority::from_static("localhost:3301"))
                .as_str(),
        )
        .path_and_query(base_uri + "?" + &new_query)
        .build()
        .unwrap();

    Some(uri.to_string())
}

#[derive(Debug)]
pub struct Params {
    pub search_terms: Vec<String>,
    pub search_fields: HashSet<String>,
    pub parent_type: PropertyParentType,
    pub group_type_index: i32,
    pub properties: Vec<String>,
    pub excluded_properties: Vec<String>,
    pub event_names: Vec<String>,
    pub is_feature_flag: Option<bool>,
    pub is_numerical: bool,
    pub use_enterprise_taxonomy: bool,
    pub limit: i64,
    pub offset: i64,
}

impl Params {
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L81-L96
    pub fn valid(&self) -> Result<(), ApiError> {
        if self.parent_type == PropertyParentType::Group && self.group_type_index <= 0 {
            return Err(ApiError::InvalidRequestParam(
                "property_type 'group' requires 'group_type_index' parameter".to_string(),
            ));
        }

        if self.parent_type != PropertyParentType::Group && self.group_type_index != -1 {
            return Err(ApiError::InvalidRequestParam(
                "parameter 'group_type_index' is only allowed with property_type 'group'"
                    .to_string(),
            ));
        }

        if !self.event_names.is_empty() && self.parent_type != PropertyParentType::Event {
            return Err(ApiError::InvalidRequestParam(
                "parameter 'event_names' is only allowed with property_type 'event'".to_string(),
            ));
        }

        Ok(())
    }
}

#[derive(Serialize, FromRow)]
struct PropDefRow {
    id: uuid::Uuid,
    name: String,
    #[serde(rename = "type")]
    parent_type: Option<String>,
    property_type: Option<String>,
    is_numerical: Option<bool>,
    is_seen_on_filtered_events: Option<bool>,
    updated_at: Option<DateTime<Utc>>,
    // if present, the "updated_by" posthog_user
    ub_id: Option<i64>,
    ub_uuid: Option<uuid::Uuid>,
    ub_distinct_id: Option<String>,
    ub_first_name: Option<String>,
    ub_last_name: Option<String>,
    ub_email: Option<String>,
    ub_is_email_verified: Option<bool>,
    ub_hedgehog_config: Option<String>, // JSON value; TODO: hydrate this for resp
    verified: Option<bool>,
    verified_at: Option<DateTime<Utc>>,
    // if present, the "verified_by" posthog_user
    vb_id: Option<i64>,
    vb_uuid: Option<uuid::Uuid>,
    vb_distinct_id: Option<String>,
    vb_first_name: Option<String>,
    vb_last_name: Option<String>,
    vb_email: Option<String>,
    vb_is_email_verified: Option<bool>,
    vb_hedgehog_config: Option<String>, // JSON value; TODO: hydrate this for resp
    tags: Option<Vec<String>>,
}

//
// JSON API response structures below. These are shaped as the original Django API does
//

#[derive(Serialize)]
pub struct PropertyDefinitionResponse {
    count: i64,
    next: Option<String>,
    prev: Option<String>,
    results: Vec<PropertyDefinition>,
}

#[derive(Serialize)]
pub struct PropertyDefinition {
    id: uuid::Uuid,
    name: String,
    #[serde(rename = "type")]
    parent_type: Option<String>,
    property_type: Option<String>,
    is_numerical: Option<bool>,
    is_seen_on_filtered_events: Option<bool>,
    updated_at: Option<DateTime<Utc>>,
    updated_by: Option<User>,
    verified: Option<bool>,
    verified_at: Option<DateTime<Utc>>,
    verified_by: Option<User>,
    tags: Option<Vec<String>>,
}

impl From<PropDefRow> for PropertyDefinition {
    fn from(row: PropDefRow) -> Self {
        let mut updated_by: Option<User> = None;
        if row.ub_id.is_some() {
            let mut hcfg: Option<HedgehogConfig> = None;
            if row.ub_hedgehog_config.is_some() {
                let raw = row.ub_hedgehog_config.unwrap();
                hcfg = serde_json::from_str(&raw).unwrap_or(None);
            }

            let ub = User {
                id: row.ub_id.unwrap(),
                uuid: row.ub_uuid.unwrap(),
                first_name: row.ub_first_name,
                last_name: row.ub_last_name,
                distinct_id: row.ub_distinct_id,
                email: row.ub_email,
                is_email_verified: row.ub_is_email_verified,
                hedgehog_config: hcfg,
            };

            updated_by = Some(ub);
        }

        let mut verified_by: Option<User> = None;
        if row.vb_id.is_some() {
            let mut hcfg: Option<HedgehogConfig> = None;
            if row.vb_hedgehog_config.is_some() {
                let raw = row.vb_hedgehog_config.unwrap();
                hcfg = serde_json::from_str(&raw).unwrap_or(None);
            }

            let vb = User {
                id: row.vb_id.unwrap(),
                uuid: row.vb_uuid.unwrap(),
                first_name: row.vb_first_name,
                last_name: row.vb_last_name,
                distinct_id: row.vb_distinct_id,
                email: row.vb_email,
                is_email_verified: row.vb_is_email_verified,
                hedgehog_config: hcfg,
            };

            verified_by = Some(vb);
        }

        PropertyDefinition {
            id: row.id,
            name: row.name,
            parent_type: row.parent_type,
            property_type: row.property_type,
            is_numerical: row.is_numerical,
            is_seen_on_filtered_events: row.is_seen_on_filtered_events,
            updated_at: row.updated_at,
            updated_by: updated_by,
            verified: row.verified,
            verified_at: row.verified_at,
            verified_by: verified_by,
            tags: row.tags,
        }
    }
}

#[derive(Serialize)]
pub struct User {
    id: i64,
    uuid: uuid::Uuid,
    distinct_id: Option<String>,
    first_name: Option<String>,
    last_name: Option<String>,
    email: Option<String>,
    is_email_verified: Option<bool>,
    hedgehog_config: Option<HedgehogConfig>, // JSON value; TODO: hydrate this for resp
}

#[derive(Deserialize, Serialize)]
pub struct HedgehogConfig {
    use_as_profile: Option<bool>,
    color: Option<String>,
    accessories: Option<Vec<String>>,
    role_at_organization: Option<String>,
}
