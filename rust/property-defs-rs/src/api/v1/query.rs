use crate::{
    api::v1::{
        constants::{
            extract_aliases, ENTERPRISE_PROP_DEFS_TABLE, ENTERPRISE_PROP_DEFS_TABLE_COLUMNS,
            EVENTS_HIDDEN_PROPERTY_DEFINITIONS, EVENT_PROPERTY_TABLE, EVENT_PROPERTY_TABLE_ALIAS,
            PROPERTY_DEFS_TABLE, PROPERTY_DEFS_TABLE_COLUMNS, SEARCH_SCREEN_WORD,
        },
        routing::Params,
    },
    //metrics_consts::{},
    types::PropertyParentType,
};

use sqlx::{postgres::PgArguments, query::Query, PgPool, Postgres, QueryBuilder};

use std::collections::{HashMap, HashSet};

// Wraps Postgres client and builds queries
pub struct Manager {
    pub pool: PgPool,
    search_term_aliases: HashMap<&'static str, &'static str>,
}

impl Manager {
    pub async fn new(api_pool: PgPool) -> Result<Self, sqlx::Error> {
        Ok(Self {
            pool: api_pool,
            search_term_aliases: extract_aliases(),
        })
    }

    pub fn count_query<'args, 'builder: 'args>(
        &self,
        qb: &'builder mut QueryBuilder<'args, Postgres>,
        project_id: i32,
        params: &'args Params,
    ) -> Query<'args, Postgres, PgArguments> {
        /* The original Django query formulation we're duplicating
                 * https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L279-L289

        SELECT count(*) as full_count
        FROM {self.table}
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
        qb.push("SELECT count(*) AS full_count ");

        self.gen_from_clause(qb, params.use_enterprise_taxonomy);
        self.conditionally_join_event_properties(
            qb,
            project_id,
            params.parent_type,
            &params.event_names,
        );

        // begin the WHERE clause
        self.init_where_clause(qb, project_id);
        self.where_property_type(qb, params.parent_type);
        qb.push(format!(
            "AND COALESCE({PROPERTY_DEFS_TABLE}.\"group_type_index\", -1) = "
        ));
        qb.push_bind(params.group_type_index);
        qb.push(" ");

        self.conditionally_filter_excluded_properties(
            qb,
            params.parent_type,
            &params.excluded_properties,
        );
        self.conditionally_filter_properties(qb, &params.properties);
        self.conditionally_filter_numerical_properties(qb, params.is_numerical);

        self.conditionally_apply_search_clause(
            qb,
            &params.search_terms,
            &params.search_fields,
            params.filter_initial_props,
        );

        self.conditionally_filter_feature_flags(qb, &params.is_feature_flag);

        // NOTE: event_name_filter from orig Django query doesn't appear to be applied anywhere atm

        // NOTE: count query is global per project_id, so no LIMIT/OFFSET handling is applied

        qb.build()
    }

    pub fn property_definitions_query<'args, 'builder: 'args>(
        &self,
        qb: &'builder mut QueryBuilder<'args, Postgres>,
        project_id: i32,
        params: &'args Params,
    ) -> Query<'args, Postgres, PgArguments> {
        /* The original Django query we're duplicating
                 * https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L262-L275

        SELECT {self.property_definition_fields}, {self.event_property_field} AS is_seen_on_filtered_events
        FROM {self.table}
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
        ORDER BY is_seen_on_filtered_events DESC,
                 {verified_ordering}
                 {self.property_definition_table}.name ASC
        LIMIT {self.limit}
        OFFSET {self.offset}

                * Also, the conditionally-applied join on event properties table applied above as
                * self._join_on_event_property()
                * https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L293-L305
                */

        self.gen_prop_defs_select_clause(qb, params.use_enterprise_taxonomy);

        // append event_property_field clause to SELECT clause
        let is_seen_resolved = if self.is_parent_type_event(params.parent_type) {
            format!("{EVENT_PROPERTY_TABLE_ALIAS}.\"property\"")
        } else {
            "NULL".to_string()
        };
        qb.push(format!(
            ", {is_seen_resolved} IS NOT NULL AS is_seen_on_filtered_events "
        ));

        self.gen_from_clause(qb, params.use_enterprise_taxonomy);
        self.conditionally_join_event_properties(
            qb,
            project_id,
            params.parent_type,
            &params.event_names,
        );

        // begin the WHERE clause
        self.init_where_clause(qb, project_id);
        self.where_property_type(qb, params.parent_type);
        qb.push(format!(
            " AND COALESCE({PROPERTY_DEFS_TABLE}.\"group_type_index\", -1) = "
        ));
        qb.push_bind(params.group_type_index);
        qb.push(" ");

        self.conditionally_filter_excluded_properties(
            qb,
            params.parent_type,
            &params.excluded_properties,
        );
        self.conditionally_filter_properties(qb, &params.properties);
        self.conditionally_filter_numerical_properties(qb, params.is_numerical);

        self.conditionally_apply_search_clause(
            qb,
            &params.search_terms,
            &params.search_fields,
            params.filter_initial_props,
        );

        self.conditionally_filter_feature_flags(qb, &params.is_feature_flag);

        // ORDER BY clauses
        qb.push(" ORDER BY is_seen_on_filtered_events DESC, ");
        if params.use_enterprise_taxonomy {
            // "verified" col only exists on the enterprise prop defs table!
            qb.push(format!(
                " {ENTERPRISE_PROP_DEFS_TABLE}.\"verified\" DESC NULLS LAST, "
            ));
        }
        qb.push(format!(" {PROPERTY_DEFS_TABLE}.\"name\" ASC "));
        qb.push(" ");

        // LIMIT and OFFSET clauses
        qb.push(" LIMIT ");
        qb.push_bind(params.limit);
        qb.push(" OFFSET ");
        qb.push_bind(params.offset);
        qb.push(" ");

        qb.build()
    }

    fn gen_prop_defs_select_clause(
        &self,
        qb: &mut QueryBuilder<Postgres>,
        use_enterprise_taxonomy: bool,
    ) {
        let mut selections = vec![];

        for col_name in PROPERTY_DEFS_TABLE_COLUMNS {
            selections.push(format!("{PROPERTY_DEFS_TABLE}.\"{col_name}\""));
        }

        // if we're JOINing in the enterprise property def, select ee-specific cols too
        if use_enterprise_taxonomy {
            for col_name in ENTERPRISE_PROP_DEFS_TABLE_COLUMNS {
                selections.push(format!("{ENTERPRISE_PROP_DEFS_TABLE}.\"{col_name}\""));
            }
        }

        qb.push(format!(" SELECT {}", selections.join(", ")));
    }

    fn gen_from_clause(&self, qb: &mut QueryBuilder<Postgres>, use_enterprise_taxonomy: bool) {
        // conditionally apply JOIN on enterprise prop defs if request param flag is set
        // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L505-L506
        let from_clause = if use_enterprise_taxonomy {
            format!(
                " FROM {PROPERTY_DEFS_TABLE} FULL OUTER JOIN {ENTERPRISE_PROP_DEFS_TABLE} ON {PROPERTY_DEFS_TABLE}.\"id\"={ENTERPRISE_PROP_DEFS_TABLE}.\"propertydefinition_ptr_id\" "
            )
        } else {
            // this is the default if enterprise taxonomy is not requested
            format!(" FROM {PROPERTY_DEFS_TABLE} ")
        };
        qb.push(from_clause);
        qb.push(" ");
    }

    fn conditionally_join_event_properties<'args>(
        &self,
        qb: &mut QueryBuilder<'args, Postgres>,
        project_id: i32,
        parent_type: PropertyParentType,
        event_names: &'args [String],
    ) {
        // conditionally join on event properties table
        // this join is only applied if the query is scoped to type "event"
        if self.is_parent_type_event(parent_type) {
            let filter_by_event_names = !event_names.is_empty();

            // if a list of event_names was supplied, we want this join to narrow
            // to only those events. otherwise it's a LEFT JOIN for enrichment only
            qb.push(self.event_property_join_type(filter_by_event_names));
            qb.push(format!(
                " (SELECT DISTINCT property FROM {EVENT_PROPERTY_TABLE} WHERE COALESCE(project_id, team_id) = "
            ));
            qb.push_bind(project_id);
            qb.push(" ");

            // conditionally apply filter if event_names list was supplied
            if filter_by_event_names {
                qb.push(" AND event = ANY(");
                qb.push_bind(event_names);
                qb.push(") ");
            }

            // close the JOIN clause and add the JOIN condition
            qb.push(format!(
                ") AS {EVENT_PROPERTY_TABLE_ALIAS} ON {EVENT_PROPERTY_TABLE_ALIAS}.\"property\" = {PROPERTY_DEFS_TABLE}.\"name\" "
            ));
        }
    }

    fn init_where_clause(&self, qb: &mut QueryBuilder<Postgres>, project_id: i32) {
        qb.push(format!(
            "WHERE COALESCE({PROPERTY_DEFS_TABLE}.\"project_id\", {PROPERTY_DEFS_TABLE}.\"team_id\") = "
        ));
        qb.push_bind(project_id);
        qb.push(" ");
    }

    fn where_property_type(
        &self,
        qb: &mut QueryBuilder<Postgres>,
        parent_type: PropertyParentType,
    ) {
        qb.push(format!(" AND {PROPERTY_DEFS_TABLE}.\"type\" = "));
        qb.push_bind(parent_type as i32);
        qb.push(" ");
    }

    fn conditionally_filter_excluded_properties<'args>(
        &self,
        qb: &mut QueryBuilder<'args, Postgres>,
        parent_type: PropertyParentType,
        excluded_properties: &'args [String],
    ) {
        // conditionally filter on excluded_properties
        // NOTE: excluded_properties is also passed to the Django API as JSON,
        // but may not matter when passed to this service. TBD. See below:
        // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L241
        if self.is_parent_type_event(parent_type) {
            qb.push(format!(" AND NOT {PROPERTY_DEFS_TABLE}.\"name\" = ANY("));

            // here we combine fixed set of "hidden" event props with a
            // possibly empty list of user-supplied excluded props to filter
            let mut buf: Vec<&str> = vec![];
            for entry in EVENTS_HIDDEN_PROPERTY_DEFINITIONS {
                buf.push(entry);
            }
            for entry in excluded_properties.iter() {
                buf.push(entry);
            }
            qb.push_bind(buf);
            qb.push(") ");
        }
    }

    // conditionally filter on property names against prop defs "name" column
    fn conditionally_filter_properties<'args>(
        &self,
        qb: &mut QueryBuilder<'args, Postgres>,
        properties: &'args [String],
    ) {
        if !properties.is_empty() {
            qb.push(format!(" AND {PROPERTY_DEFS_TABLE}.\"name\" = ANY("));
            qb.push_bind(properties);
            qb.push(") ");
        }
    }

    fn conditionally_filter_numerical_properties(
        &self,
        qb: &mut QueryBuilder<Postgres>,
        is_numerical: bool,
    ) {
        // conditionally filter for numerical-valued properties:
        // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L493-L499
        // https://github.com/PostHog/posthog/blob/master/posthog/filters.py#L61-L84
        if is_numerical {
            qb.push(format!(
                " AND {PROPERTY_DEFS_TABLE}.\"is_numerical\" = true AND NOT {PROPERTY_DEFS_TABLE}.\"name\" = ANY(ARRAY['distinct_id', 'timestamp']) ",
            ));
        }
    }

    fn conditionally_apply_search_clause<'args>(
        &self,
        qb: &mut QueryBuilder<'args, Postgres>,
        search_terms: &'args [String],
        search_fields: &'args HashSet<String>,
        filter_initial_props: bool,
    ) {
        // conditionally apply search term matching; skip this if possible, it's not cheap!
        // logic: https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L493-L499
        if !search_terms.is_empty() {
            // step 1: identify property def "aliases" to enrich our fuzzy matching; see also:
            // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L309-L324

            // attempt to enrich basic search terms using a heuristic:
            // if the description associated with any std PostHog event properties
            // matches *every search term* in the incoming query, capture the
            // associated property name and add it to the search terms we'll
            // attempt to return from the prop defs query. This is expensive :(
            let term_aliases: Vec<&str> = self
                .search_term_aliases
                .iter()
                .filter(|(_key, prop_long_slug)| {
                    search_terms
                        .iter()
                        .all(|term| prop_long_slug.contains(term))
                })
                .map(|(key, _matched_slug)| *key)
                .collect();

            // build a query fragment if we found aliases. We can do this
            // outside of the builder because these aren't user inputs
            let search_extras = if !term_aliases.is_empty() {
                format!(
                    " OR name = ANY(ARRAY[{}]) ",
                    term_aliases
                        .iter()
                        .map(|ta| format!("'{ta}'"))
                        .collect::<Vec<_>>()
                        .join(", ")
                )
            } else {
                "".to_string()
            };

            // step 2: filter "initial" prop defs if the user wants "latest"
            // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L326-L339
            let screening_clause = if filter_initial_props {
                format!(" OR NOT name ILIKE '%{SEARCH_SCREEN_WORD}%' ")
            } else {
                "".to_string()
            };

            // step 2.5: join whatever we found in search_extras and trigger word result
            let search_extras = format!("{search_extras}{screening_clause}");

            // step 3: generate the search fuzzy-matching SQL clause
            // Original Django monolith query construction step is here:
            // https://github.com/PostHog/posthog/blob/master/posthog/filters.py#L61-L84
            if !search_fields.is_empty() && !search_terms.is_empty() {
                // outer loop: one AND clause for every search term supplied by caller.
                // each of these clauses may be enriched with "search_extras" suffix
                for (tndx, term) in search_terms.iter().enumerate() {
                    if tndx == 0 {
                        qb.push(" AND ((");
                    }
                    // inner loop: nested OR clause for every search field (column; by default
                    // "name" only) performing a fuzzy match attempt (ILIKE) for the current
                    // search term against that column
                    for (fndx, field) in search_fields.iter().enumerate() {
                        if fndx == 0 {
                            qb.push("(");
                        }
                        qb.push(field.clone());
                        qb.push(" ILIKE ");
                        // applying terms directly to ensure fuzzy matches are
                        // in parity with original query. Terms are cleansed
                        // upstream to ensure this is safe.
                        qb.push(format!("'{term}%'"));
                        if search_fields.len() > 1 && fndx < search_fields.len() - 1 {
                            qb.push(" OR ");
                        }
                        if fndx == search_fields.len() - 1 {
                            qb.push(")");
                        }
                    }
                    if search_terms.len() > 1 && tndx < search_terms.len() - 1 {
                        qb.push(" AND ");
                    }
                    if tndx == search_terms.len() - 1 {
                        qb.push(format!(") {}) ", search_extras.clone()));
                    }
                }
            }
        }
    }

    fn conditionally_filter_feature_flags(
        &self,
        qb: &mut QueryBuilder<Postgres>,
        is_feature_flag: &Option<bool>,
    ) {
        // conditionally apply feature flag property filters
        if is_feature_flag.is_some() {
            if is_feature_flag.unwrap() {
                qb.push(format!(
                    " AND ({PROPERTY_DEFS_TABLE}.\"name\" LIKE '$feature/%') ",
                ));
            } else {
                qb.push(format!(
                    " AND ({PROPERTY_DEFS_TABLE}.\"name\" NOT LIKE '$feature/%') ",
                ));
            }
        }
    }

    // if the parent_type is "event" for this request, we will join on the
    // posthog_eventproperty table. BUT if the req also includes an event_names
    // list, we change the JOIN type to narrow to only those event props
    fn event_property_join_type(&self, filter_by_event_names: bool) -> &str {
        if filter_by_event_names {
            " INNER JOIN "
        } else {
            " LEFT JOIN "
        }
    }

    // is the "parent type" of this request (and prop defs query) the default "event" type?
    // this controls whether the base query should include a JOIN on posthog_eventproperty
    fn is_parent_type_event(&self, parent_type: PropertyParentType) -> bool {
        parent_type == PropertyParentType::Event
    }
}
