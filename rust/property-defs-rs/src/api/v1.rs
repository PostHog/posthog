use crate::{
    config::Config,
    types::{PropertyParentType, PropertyValueType},
    //metrics_consts::{},
};

use axum::{
    extract::{Path, Query, State},
    routing::get,
    Json, Router,
};
use serde::Serialize;
use sqlx::{
    Postgres,
    postgres::{PgArguments, PgPoolOptions},
    PgPool,
    QueryBuilder
};

use std::collections::HashMap;
use std::sync::Arc;

// keep this in sync with Django posthog.taxonomy pkg values
const GROUP_TYPE_LIMIT: i32 = 5;
const DEFAULT_QUERY_LIMIT: u32 = 0;
const DEFAULT_QUERY_OFFSET: u32 = 100;
const POSTHOG_EVENT_PROPERTY_TABLE_NAME_ALIAS: &'static str = "check_for_matching_event_property";

// shamelessly stolen from:
// https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L343-L361
const EVENTS_HIDDEN_PROPERTY_DEFINITIONS: [&str; 14] = [
    // distinct_id is set in properties by some libraries, but not consistently, so we shouldn't allow users to filter on it
    "distinct_id",
    // used for updating properties
    "$set",
    "$set_once",
    // posthog-js used to send it on events and shouldn't have, now it confuses users
    "$initial_referrer",
    "$initial_referring_domain",
    // Group Analytics
    "$groups",
    "$group_type",
    "$group_key",
    "$group_set",
    "$group_0",
    "$group_1",
    "$group_2",
    "$group_3",
    "$group_4",
];

pub fn apply_routes(parent: Router, qmgr: Arc<QueryManager>) -> Router {
    let api_router = Router::new()
        .route(
            "projects/{project_id}/property_definitions/",
            get(handle_prop_defs_by_project),
        )
        .with_state(qmgr);

    parent.nest("/api/v1", api_router)
}

async fn handle_prop_defs_by_project(
    State(qmgr): State<Arc<QueryManager>>,
    Path(project_id): Path<i32>,
    Query(params): Query<HashMap<String, String>>,
) -> Json<PropDefResponse> {
    // parse request params; copy things for now instead of fighting the borrow checker ;)
    let search: Option<Vec<String>> = match params.get("search") {
        Some(raw) => Some(
            raw.split(" ")
                .map(|s| s.trim().to_string().to_lowercase())
                .collect(),
        ),
        _ => None,
    };

    let property_type = match params.get("type") {
        Some(s) => match s.as_str() {
            "event" => Some(PropertyParentType::Event),
            "person" => Some(PropertyParentType::Person),
            "group" => Some(PropertyParentType::Group),
            "session" => Some(PropertyParentType::Session),
            _ => None,
        },
        _ => None,
    };

    let group_type_index: i32 = match params.get("group_type_index") {
        Some(s) => match s.parse::<i32>().ok() {
            Some(gti)
                if property_type == Some(PropertyParentType::Group)
                    && gti >= 0
                    && gti < GROUP_TYPE_LIMIT => gti,
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

    let limit: u32 = match params.get("limit") {
        Some(s) => match s.parse::<u32>().ok() {
            Some(val) => val,
            _ => DEFAULT_QUERY_LIMIT
        }
        _ => DEFAULT_QUERY_LIMIT
    };

    let offset: u32 = match params.get("offset") {
        Some(s) => match s.parse::<u32>().ok() {
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
            &filter_by_event_names,
            order_by_verified,
            limit,
            offset,
        );

    // TODO: execute queries, build result structs

    // TODO: Implement!
    Json(PropDefResponse {})
}

// Wraps Postgres client and builds queries
pub struct QueryManager {
    // TODO: capture more config::Config values here as needed
    pool: PgPool,
    table_name: String,
    prop_defs_table: String,
    event_props_table: String,
}

impl QueryManager {
    pub async fn new(cfg: &Config) -> Result<Self, sqlx::Error> {
        let options = PgPoolOptions::new().max_connections(cfg.max_pg_connections);
        let api_pool = options.connect(&cfg.database_url).await?;

        Ok(Self {
            pool: api_pool,
            table_name: cfg.table_name.clone(),
            prop_defs_table: cfg.prop_defs_table_name.clone(),
            event_props_table: cfg.event_props_table_name.clone(),
        })
    }

    fn count_query<'a>(
        &self,
        project_id: i32,
        search: &Option<Vec<String>>,
        property_type: &Option<PropertyParentType>,
        group_type_index: i32,
        properties: &'a Option<Vec<String>>,
        excluded_properties: &'a Option<Vec<String>>,
        event_names: &'a Option<Vec<String>>,
        is_feature_flag: &Option<bool>,
        is_numerical: &Option<bool>,
        filter_by_event_names: &Option<bool>,
    ) -> String {
        /* The original Django query formulation we're duplicating
         * https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L279-L289

SELECT count(*) as full_count
FROM {self.table_name}
{self._join_on_event_property()}
WHERE coalesce({self.property_definition_table}.project_id, {self.property_definition_table}.team_id) = %(project_id)s
    AND type = %(type)s
    AND coalesce(group_type_index, -1) = %(group_type_index)s
    {self.excluded_properties_filter}
    {self.name_filter}
    {self.numerical_filter}
    {self.search_query}
    {self.event_property_filter}
    {self.is_feature_flag_filter}
    {self.event_name_filter}

        * Also, the conditionally-applied join on event properties table applied above as
        * self._join_on_event_property()
        * https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L293-L305
        */

        let mut qb = sqlx::QueryBuilder::<Postgres>::new("SELECT count(*) AS full_count FROM ");
        qb.push_bind(self.table_name.clone());
        
        // conditionally join on event properties table
        // this join is only applied if the query is scoped to type "event"
        if self.is_prop_type_event(property_type) {
            qb.push(self.event_property_join_type(filter_by_event_names));
            qb.push("(SELECT DISTINCT property FROM ");
            qb.push_bind(self.event_props_table.clone());
            qb.push(" WHERE COALESCE(project_id, team_id) = ");
            qb.push_bind(project_id);

            // conditionally apply event_names filter
            if filter_by_event_names.is_some() && filter_by_event_names.unwrap() == true {
                if let Some(names) = event_names {
                    if names.len() > 0 {
                        qb.push(" AND event = ANY(");
                        for name in names.iter() {
                            qb.push_bind(name);
                        }
                        qb.push(") ");
                    }
                }
            }

            // close the JOIN clause and add the JOIN condition
            qb.push(format!( ") {0} ON {0}.property = name ", POSTHOG_EVENT_PROPERTY_TABLE_NAME_ALIAS));
        }

        // begin the WHERE clause
        qb.push(format!("WHERE COALESCE({0}.project_id, {0}.team_id) = ", self.prop_defs_table));
        qb.push_bind(project_id);
        
        // add condition on "type" (here, ProperyParentType)
        // TODO: throw error in input validation if this is missing!
        if let Some(prop_type) =  property_type {
            qb.push("AND type = ");
            qb.push_bind(*prop_type as i32);
        }

        // add condition on group_type_index
        qb.push("AND COALESCE(group_type_index, -1) = ");
        qb.push_bind(group_type_index);

        // conditionally filter on excluded_properties
        // NOTE: excluded_properties is also passed to the Django API as JSON,
        // but may not matter when passed to this service. TBD. See below:
        // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L241
        if let Some(excludes) = excluded_properties {
            if self.is_prop_type_event(property_type) || excludes.len() > 0 {
                qb.push(format!("AND NOT {0}.name = ANY(", self.prop_defs_table));
                if self.is_prop_type_event(property_type) {
                    for prop in EVENTS_HIDDEN_PROPERTY_DEFINITIONS.iter() {
                        qb.push_bind(prop);
                    }
                }
                for prop in excludes.iter() {
                    qb.push_bind(prop);
                }
                qb.push(") ");
            }
        }

        // conditionally filter on property names ("name" col)
        if let Some(props) = properties {
            if props.len() > 0 {
                qb.push(" AND name = ANY(");
                for prop in props.iter() {
                    qb.push_bind(prop);
                }
                qb.push(") ");
            }
        }

        // conditionally filter for numerical-valued properties
        if is_numerical.is_some() {
            qb.push(" AND is_numerical = true AND NOT name = ANY(ARRAY['distinct_id', 'timestamp']) ");
        }

        // conditionally apply search term matching
        let search_extras = HashMap::<String, String>::new(); // TODO: impl method to populate this!
        // TODO: not implemented yet!!

        // conditionally apply event_names filter for outer query
        //
        // NOTE: the conditional join on event props table applied
        // above applies the same filter, but it can be an INNER or
        // LEFT join, so this is still required.
        if filter_by_event_names.is_some() && filter_by_event_names.unwrap() == true {
            if let Some(names) = event_names {
                if names.len() > 0 {
                    qb.push(" AND event = ANY(");
                    for name in names.iter() {
                        qb.push_bind(name);
                    }
                    qb.push(") ");
                }
            }
        }

        // conditionally apply feature flag property filters
        if is_feature_flag.is_some() {
            if is_feature_flag.unwrap() {
                qb.push(" AND (name LIKE '$feature/%') ");
            } else {
                qb.push(" AND (name NOT LIKE '$feature/%') ");
            }
        }

        // NOTE: event_name_filter from orig Django query doesn't appear to be applied anywhere atm

        // NOTE: count query is global per project_id, so no LIMIT/OFFSET handling is applied

        qb.sql().into()
    }

    fn property_definitions_query<'a>(
        &self,
        project_id: i32,
        search: &Option<Vec<String>>,
        property_type: &Option<PropertyParentType>,
        group_type_index: i32,
        properties: &Option<Vec<String>>,
        excluded_properties: &Option<Vec<String>>,
        event_names: &'a Option<Vec<String>>,
        is_feature_flag: &Option<bool>,
        is_numerical: &Option<bool>,
        filter_by_event_names: &Option<bool>,
        order_by_verified: bool, // TODO: where is this coming from?
        limit: u32,
        offset: u32,
    ) -> String {
        /* The original Django query we're duplicating
         * https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L262-L275

SELECT {self.property_definition_fields}, {self.event_property_field} AS is_seen_on_filtered_events
FROM {self.table}
{self._join_on_event_property()}
WHERE coalesce({self.property_definition_table}.project_id, {self.property_definition_table}.team_id) = %(project_id)s
    AND type = %(type)s
    AND coalesce(group_type_index, -1) = %(group_type_index)s
    {self.excluded_properties_filter}
    {self.name_filter} {self.numerical_filter}
    {self.search_query}
    {self.event_property_filter}
    {self.is_feature_flag_filter}
    {self.event_name_filter}
ORDER BY is_seen_on_filtered_events DESC,
         {verified_ordering}
         {self.property_definition_table}.name ASC
LIMIT {self.limit}
OFFSET {self.offset}

        * Also, the conditionally-applied join on event properties table applied above as
        * self._join_on_event_property()
        * https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L293-L305
        */

        let verified_ordering = match order_by_verified {
            true => "verified DESC NULLS LAST,",
            _ => "",
        };

        let mut qb = sqlx::QueryBuilder::<Postgres>::new("SELECT ");
        qb.push(self.prop_defs_table.clone());

        // TODO: implement query construction!

        qb.sql().into()
    }

    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L232-L237
    fn with_search_query<'a>(&self, qb: &'a mut QueryBuilder<'a, Postgres>, search_query: &Option<Vec<String>>, search_extras: &HashMap<String, String>) {
        // search_extras and formatted search_query (*NOT* just the Vec<String> of input keywords!)
        // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L494-L499

        // TODO: IMPLEMENT THIS!
    }

    fn event_property_join_type(&self, filter_by_event_names: &Option<bool>) -> &str {
        if let Some(true) = filter_by_event_names {
            "INNER JOIN"
        } else {
            "LEFT JOIN"
        }
    }

    fn is_prop_type_event(&self, property_type: &Option<PropertyParentType>) -> bool {
        match property_type {
            Some(PropertyParentType::Event) => true,
            _ => false,
        }
    }
}

#[derive(Serialize)]
pub struct PropDefResponse {
    count: u32,
    next: Option<String>,
    prev: Option<String>,
    results: Vec<PropDef>,
}

#[derive(Serialize)]
struct PropDef {
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
struct Person {
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
struct HedgehogConfig {
    use_as_profile: bool,
    color: String,
    accessories: Vec<String>,
    role_at_organization: Option<String>,
}
