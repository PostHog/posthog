use crate::{
    api::v1::constants::*,
    //metrics_consts::{},
    config::Config,
};

use serde::Serialize;
use sqlx::{postgres::PgPoolOptions, PgPool, Postgres, QueryBuilder};

// Wraps Postgres client and builds queries
pub struct Manager {
    // TODO: capture more config::Config values here as needed
    pool: PgPool,
    enterprise_prop_defs_table: String,
    prop_defs_table: String,
    event_props_table: String,
}

impl Manager {
    pub async fn new(cfg: &Config) -> Result<Self, sqlx::Error> {
        let options = PgPoolOptions::new().max_connections(cfg.max_pg_connections);
        let api_pool = options.connect(&cfg.database_url).await?;

        Ok(Self {
            pool: api_pool,
            enterprise_prop_defs_table: cfg.enterprise_prop_defs_table_name.clone(),
            prop_defs_table: cfg.prop_defs_table_name.clone(),
            event_props_table: cfg.event_props_table_name.clone(),
        })
    }

    pub fn count_query<'a>(
        &self,
        project_id: i32,
        search: &Option<Vec<String>>,
        property_type: &Option<String>,
        group_type_index: i32,
        properties: &'a Option<Vec<String>>,
        excluded_properties: &'a Option<Vec<String>>,
        event_names: &'a Option<Vec<String>>,
        is_feature_flag: &Option<bool>,
        is_numerical: &Option<bool>,
        use_enterprise_taxonomy: &Option<bool>,
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

        // build & render the query
        let mut qb = QueryBuilder::<Postgres>::new("SELECT count(*) AS full_count FROM ");

        let from_clause = if use_enterprise_taxonomy.is_some_and(|uet| uet == true) {
            // TODO: ensure this all behaves as it does in Django (and that we need it!) later...
            // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L505-L506
            &format!(
                "{0} FULL OUTER JOIN {1} ON {1}.id={0}.propertydefinition_ptr_id",
                &self.enterprise_prop_defs_table, &self.prop_defs_table
            )
        } else {
            // this is the default if enterprise taxonomy is not requested
            &self.prop_defs_table
        };
        qb.push_bind(from_clause);

        // conditionally join on event properties table
        // this join is only applied if the query is scoped to type "event"
        if self.is_prop_type_event(property_type) {
            qb.push(self.event_property_join_type(filter_by_event_names));
            qb.push(" (SELECT DISTINCT property FROM ");
            qb.push_bind(self.event_props_table.clone());
            qb.push(" WHERE COALESCE(project_id, team_id) = ");
            qb.push_bind(project_id);

            // conditionally apply event_names filter
            if filter_by_event_names.is_some() && filter_by_event_names.unwrap() == true {
                if let Some(names) = event_names {
                    if names.len() > 0 {
                        qb.push(" AND event = ANY(");
                        qb.push_bind(names);
                        qb.push(") ");
                    }
                }
            }

            // close the JOIN clause and add the JOIN condition
            qb.push(format!(
                ") {0} ON {0}.property = name ",
                POSTHOG_EVENT_PROPERTY_TABLE_NAME_ALIAS
            ));
        }

        // begin the WHERE clause
        qb.push(format!(
            "WHERE COALESCE({0}.project_id, {0}.team_id) = ",
            self.prop_defs_table
        ));
        qb.push_bind(project_id);

        // add condition on "type" (here, ProperyParentType)
        // TODO: throw error in input validation if this is missing!
        if let Some(prop_type) = property_type {
            qb.push("AND type = ");
            qb.push_bind(prop_type);
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
                let mut buf: Vec<&str> = vec![];
                if self.is_prop_type_event(property_type) {
                    for entry in EVENTS_HIDDEN_PROPERTY_DEFINITIONS {
                        buf.push(entry);
                    }
                }
                if excludes.len() > 0 {
                    for entry in excludes.iter() {
                        buf.push(entry);
                    }
                }
                qb.push_bind(buf);
                qb.push(") ");
            }
        }

        // conditionally filter on property names ("name" col)
        if let Some(props) = properties {
            if props.len() > 0 {
                qb.push(" AND name = ANY(");
                qb.push_bind(props);
                qb.push(") ");
            }
        }

        // conditionally filter for numerical-valued properties:
        // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L493-L499
        // https://github.com/PostHog/posthog/blob/master/posthog/filters.py#L61-L84
        if is_numerical.is_some_and(|is_num| is_num == true) {
            qb.push(
                " AND is_numerical = true AND NOT name = ANY(ARRAY['distinct_id', 'timestamp']) ",
            );
        }

        // conditionally apply search term matching
        // logic: https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L493-L499
        // helpers logic:
        // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L308-L323
        // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L326-L339
        //
        // https://github.com/PostHog/posthog/blob/master/posthog/filters.py#L61-L84

        /* **** TODO: implement! ****
           let search_extras = HashMap::<String, String>::new();
           **************************
        */

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

    pub fn property_definitions_query<'a>(
        &self,
        project_id: i32,
        search: &Option<Vec<String>>,
        property_type: &Option<String>,
        group_type_index: i32,
        properties: &Option<Vec<String>>,
        excluded_properties: &Option<Vec<String>>,
        event_names: &'a Option<Vec<String>>,
        is_feature_flag: &Option<bool>,
        is_numerical: &Option<bool>,
        use_enterprise_taxonomy: &Option<bool>,
        filter_by_event_names: &Option<bool>,
        order_by_verified: bool, // TODO: where is this coming from?
        limit: i32,
        offset: i32,
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

        let mut qb = QueryBuilder::<Postgres>::new(
            r#"
        SELECT **TODO**
        "#,
        );

        // TODO: implement query construction!

        let verified_ordering = match order_by_verified {
            true => "verified DESC NULLS LAST,",
            _ => "",
        };

        qb.sql().into()
    }

    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L232-L237
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L494-L499

    fn event_property_join_type(&self, filter_by_event_names: &Option<bool>) -> &str {
        if let Some(true) = filter_by_event_names {
            "INNER JOIN"
        } else {
            "LEFT JOIN"
        }
    }

    fn is_prop_type_event(&self, property_type: &Option<String>) -> bool {
        property_type.is_some() && property_type.as_ref().unwrap() == "event"
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
