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
use serde::Serialize;
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
) -> Result<Json<PropDefResponse>, ApiError> {
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

    let mut prop_defs = vec![];
    match qmgr.pool.fetch_all(props_query).await {
        Ok(result) => {
            for row in result {
                debug!("PgRow: {:?}", row);

                // TODO: iterate on this! populate ee & User fields when available etc.
                let pd = PropDef::from_row(&row).map_err(|e| {
                    ApiError::QueryError(format!("deserializing prop defs row: {}", e))
                })?;
                prop_defs.push(pd);
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
    let out = PropDefResponse {
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

    // NOTE: so far I'm assuming this should be calculated on the Django (caller) side and
    // passed to this app as a flag b/c it references User model (etc.) but perhaps we just
    // manually run those queries here too? TBD. the flag allows us to decide the base table
    // to select from in our property defs queries. see also:
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L463
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L504-L508
    let use_enterprise_taxonomy = params
        .get("use_enterprise_taxonomy")
        .and_then(|s| s.parse::<bool>().ok())
        .unwrap_or(false);

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

#[derive(Serialize)]
pub struct PropDefResponse {
    count: i64,
    next: Option<String>,
    prev: Option<String>,
    results: Vec<PropDef>,
}

#[derive(Serialize, FromRow)]
pub struct PropDef {
    // required fields
    id: uuid::Uuid,
    name: String,
    property_type: String,
    is_numerical: bool,
    is_seen_on_filtered_events: bool,

    // enterprise prop defs only fields below
    #[serde(default)]
    updated_at: Option<DateTime<Utc>>,
    #[serde(default)]
    updated_by_id: Option<i64>, // TODO: when available, JOIN in the User record instead!
    #[serde(default)]
    verified: Option<bool>,
    #[serde(default)]
    verified_at: Option<DateTime<Utc>>,
    #[serde(default)]
    verified_by_id: Option<i64>, // TODO: when available, JOIN in the User record instead!
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    tags: Vec<String>,
}

// TODO: hydrate User(s) JOINed into prop defs query into this
#[derive(Serialize, FromRow)]
pub struct User {
    id: u32,
    uuid: uuid::Uuid,
    distinct_id: String,
    first_name: String,
    last_name: String,
    email: String,
    is_email_verified: bool,
    hedgehog_config: HedgehogConfig,
}

// TODO: optionally include when prop defs query JOINs in User records
#[derive(Serialize, FromRow)]
pub struct HedgehogConfig {
    use_as_profile: bool,
    color: String,
    accessories: Vec<String>,
    role_at_organization: Option<String>,
}
