use crate::{
    api::v1::{
        constants::{
            extract_aliases, EVENTS_HIDDEN_PROPERTY_DEFINITIONS,
            POSTHOG_EVENT_PROPERTY_TABLE_NAME_ALIAS, SEARCH_SCREEN_WORD, SEARCH_TRIGGER_WORD,
        },
        routing::Params,
    },
    //metrics_consts::{},
    config::Config,
};

use sqlx::{postgres::PgPoolOptions, PgPool, Postgres, QueryBuilder};

use std::collections::{HashMap, HashSet};

// Wraps Postgres client and builds queries
pub struct Manager {
    // TODO: capture more config::Config values here as needed
    pub pool: PgPool,
    enterprise_prop_defs_table: String,
    prop_defs_table: String,
    event_props_table: String,
    search_term_aliases: HashMap<&'static str, &'static str>,
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
            search_term_aliases: extract_aliases(),
        })
    }

    pub fn count_query(&self, project_id: i32, params: &Params) -> String {
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
        let mut qb = QueryBuilder::<Postgres>::new("SELECT count(*) AS full_count FROM ");

        qb = self.gen_from_clause(qb, &params.use_enterprise_taxonomy);
        qb = self.gen_conditional_join_event_props(
            qb,
            project_id,
            &params.property_type,
            &params.filter_by_event_names,
            &params.event_names,
        );

        // begin the WHERE clause
        qb = self.init_where_clause(qb, project_id);
        qb = self.where_property_type(qb, &params.property_type);
        qb.push("AND COALESCE(group_type_index, -1) = ");
        qb.push_bind(params.group_type_index);

        qb = self.conditionally_filter_excluded_properties(
            qb,
            &params.property_type,
            &params.excluded_properties,
        );
        qb = self.conditionally_filter_properties(qb, &params.properties);
        qb = self.conditionally_filter_numerical_properties(qb, &params.is_numerical);

        qb =
            self.conditionally_apply_search_clause(qb, &params.search_terms, &params.search_fields);

        qb = self.conditionally_filter_event_names(
            qb,
            &params.filter_by_event_names,
            &params.event_names,
        );
        qb = self.conditionally_filter_feature_flags(qb, &params.is_feature_flag);

        // NOTE: event_name_filter from orig Django query doesn't appear to be applied anywhere atm

        // NOTE: count query is global per project_id, so no LIMIT/OFFSET handling is applied

        qb.sql().into()
    }

    pub fn property_definitions_query(&self, project_id: i32, params: &Params) -> String {
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

        let mut qb = QueryBuilder::<Postgres>::new("SELECT ");
        if params.use_enterprise_taxonomy.is_some_and(|uet| uet) {
            // borrowed from EnterprisePropertyDefinition from Django monolith
            // via EnterprisePropertyDefinition._meta.get_fields()
            qb.push("id, project, team, name, is_numerical, property_type, type, group_type_index, property_type_format, description, updated_at, updated_by, verified_at, verified_by ");
        } else {
            // borrowed from Django monolith via PropertyDefinition._meta.get_fields()
            qb.push("id, project, team, name, is_numerical, property_type, type, group_type_index, property_type_format ");
        }

        // append event_property_field clause to SELECT clause
        let is_seen_resolved = if params
            .event_names
            .as_ref()
            .is_some_and(|evs| !evs.is_empty())
        {
            format!("{}.property", POSTHOG_EVENT_PROPERTY_TABLE_NAME_ALIAS)
        } else {
            "NULL".to_string()
        };
        qb.push(format!(
            ", {} IS NOT NULL AS is_seen_on_filtered_events ",
            is_seen_resolved
        ));

        qb = self.gen_from_clause(qb, &params.use_enterprise_taxonomy);
        qb = self.gen_conditional_join_event_props(
            qb,
            project_id,
            &params.property_type,
            &params.filter_by_event_names,
            &params.event_names,
        );

        // begin the WHERE clause
        qb = self.init_where_clause(qb, project_id);
        qb = self.where_property_type(qb, &params.property_type);
        qb.push("AND COALESCE(group_type_index, -1) = ");
        qb.push_bind(params.group_type_index);

        qb = self.conditionally_filter_excluded_properties(
            qb,
            &params.property_type,
            &params.excluded_properties,
        );
        qb = self.conditionally_filter_properties(qb, &params.properties);
        qb = self.conditionally_filter_numerical_properties(qb, &params.is_numerical);

        qb =
            self.conditionally_apply_search_clause(qb, &params.search_terms, &params.search_fields);

        qb = self.conditionally_filter_event_names(
            qb,
            &params.filter_by_event_names,
            &params.event_names,
        );
        qb = self.conditionally_filter_feature_flags(qb, &params.is_feature_flag);

        // ORDER BY clauses
        qb.push("ORDER BY is_seen_on_filtered_events DESC, ");
        if params.order_by_verified {
            qb.push("verified DESC NULLS LAST, ");
        }
        qb.push(format!("{}.name ASC ", &self.prop_defs_table));

        // LIMIT and OFFSET clauses
        qb.push("LIMIT ");
        qb.push_bind(params.limit);
        qb.push("OFFSET ");
        qb.push_bind(params.offset);

        qb.sql().into()
    }

    fn gen_from_clause<'a>(
        &self,
        mut qb: QueryBuilder<'a, Postgres>,
        use_enterprise_taxonomy: &Option<bool>,
    ) -> QueryBuilder<'a, Postgres> {
        let from_clause = if use_enterprise_taxonomy.is_some_and(|uet| uet) {
            // TODO: ensure this all behaves as it does in Django (and that we need it!) later...
            // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L505-L506
            format!(
                "{0} FULL OUTER JOIN {1} ON {1}.id={0}.propertydefinition_ptr_id",
                &self.enterprise_prop_defs_table, &self.prop_defs_table
            )
        } else {
            // this is the default if enterprise taxonomy is not requested
            self.prop_defs_table.clone()
        };
        qb.push_bind(from_clause);

        qb
    }

    fn gen_conditional_join_event_props<'a>(
        &self,
        mut qb: QueryBuilder<'a, Postgres>,
        project_id: i32,
        property_type: &String,
        filter_by_event_names: &Option<bool>,
        event_names: &'a Option<Vec<String>>,
    ) -> QueryBuilder<'a, Postgres> {
        // conditionally join on event properties table
        // this join is only applied if the query is scoped to type "event"
        if self.is_prop_type_event(property_type) {
            qb.push(self.event_property_join_type(filter_by_event_names));
            qb.push(" (SELECT DISTINCT property FROM ");
            qb.push_bind(self.event_props_table.clone());
            qb.push(" WHERE COALESCE(project_id, team_id) = ");
            qb.push_bind(project_id);

            // conditionally apply event_names filter
            if filter_by_event_names.is_some_and(|fben| fben) {
                if let Some(names) = event_names {
                    if !names.is_empty() {
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

        qb
    }

    fn init_where_clause<'a>(
        &self,
        mut qb: QueryBuilder<'a, Postgres>,
        project_id: i32,
    ) -> QueryBuilder<'a, Postgres> {
        qb.push(format!(
            "WHERE COALESCE({0}.project_id, {0}.team_id) = ",
            self.prop_defs_table
        ));
        qb.push_bind(project_id);

        qb
    }

    fn where_property_type<'a>(
        &self,
        mut qb: QueryBuilder<'a, Postgres>,
        property_type: &'a String,
    ) -> QueryBuilder<'a, Postgres> {
        qb.push("AND type = ");
        qb.push_bind(property_type);

        qb
    }

    fn conditionally_filter_excluded_properties<'a>(
        &self,
        mut qb: QueryBuilder<'a, Postgres>,
        property_type: &String,
        excluded_properties: &'a Option<Vec<String>>,
    ) -> QueryBuilder<'a, Postgres> {
        // conditionally filter on excluded_properties
        // NOTE: excluded_properties is also passed to the Django API as JSON,
        // but may not matter when passed to this service. TBD. See below:
        // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L241
        if let Some(excludes) = excluded_properties {
            if self.is_prop_type_event(property_type) && !excludes.is_empty() {
                qb.push(format!("AND NOT {0}.name = ANY(", self.prop_defs_table));
                let mut buf: Vec<&str> = vec![];
                for entry in EVENTS_HIDDEN_PROPERTY_DEFINITIONS {
                    buf.push(entry);
                }
                for entry in excludes.iter() {
                    buf.push(entry);
                }
                qb.push_bind(buf);
                qb.push(") ");
            }
        }

        qb
    }

    fn conditionally_filter_properties<'a>(
        &self,
        mut qb: QueryBuilder<'a, Postgres>,
        properties: &'a Option<Vec<String>>,
    ) -> QueryBuilder<'a, Postgres> {
        // conditionally filter on property names ("name" col)
        if let Some(props) = properties {
            if !props.is_empty() {
                qb.push(" AND name = ANY(");
                qb.push_bind(props);
                qb.push(") ");
            }
        }

        qb
    }

    fn conditionally_filter_numerical_properties<'a>(
        &self,
        mut qb: QueryBuilder<'a, Postgres>,
        is_numerical: &Option<bool>,
    ) -> QueryBuilder<'a, Postgres> {
        // conditionally filter for numerical-valued properties:
        // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L493-L499
        // https://github.com/PostHog/posthog/blob/master/posthog/filters.py#L61-L84
        if is_numerical.is_some_and(|is_num| is_num) {
            qb.push(
                " AND is_numerical = true AND NOT name = ANY(ARRAY['distinct_id', 'timestamp']) ",
            );
        }

        qb
    }

    fn conditionally_apply_search_clause<'a>(
        &self,
        mut qb: QueryBuilder<'a, Postgres>,
        search_terms: &'a Option<Vec<String>>,
        search_fields: &'a HashSet<String>,
    ) -> QueryBuilder<'a, Postgres> {
        // conditionally apply search term matching; skip this if possible, it's not cheap!
        // logic: https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L493-L499
        if search_terms.as_ref().is_some_and(|terms| !terms.is_empty()) {
            // step 1: identify property def "aliases" to enrich our fuzzy matching; see also:
            // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L309-L324

            // attempt to enrich basic search terms using a heuristic:
            // if the long slug associated with any std PostHog event properties
            // matches *every search term* in the incoming query, capture the
            // associated property name and add it to the search terms we'll
            // attempt to return from the prop defs query. This is expensive :(
            let term_aliases: Vec<&str> = self
                .search_term_aliases
                .iter()
                .filter(|(_key, prop_long_slug)| {
                    search_terms
                        .as_ref()
                        .unwrap()
                        .iter()
                        .all(|term| prop_long_slug.contains(term))
                })
                .map(|(key, _matched_slug)| *key)
                .collect();

            // build a query fragment if we found aliases. We can do this
            // outside of the builder because these aren't user inputs
            let search_extras = if !term_aliases.is_empty() {
                format!(
                    " OR name = ANY(ARRAY[{}])",
                    term_aliases
                        .iter()
                        .map(|ta| format!("'{}'", ta))
                        .collect::<Vec<_>>()
                        .join(", ")
                )
            } else {
                "".to_string()
            };

            // step 2: filter "initial" prop defs if the user wants "latest"
            // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L326-L339
            let screening_clause = if term_aliases.iter().any(|ta| *ta == SEARCH_TRIGGER_WORD) {
                format!(" OR NOT name ILIKE '%{}%'", SEARCH_SCREEN_WORD)
            } else {
                "".to_string()
            };

            // step 2.5: join whatever we found in search_extras and trigger word result
            let search_extras = format!("{}{}", search_extras, screening_clause);

            // step 3: generate the search SQL which consistes of nested AND/OR clauses of arbitrary size,
            // with each clasue testing search *fields* (like "name") in the table against fuzzy-matched
            // search *terms* (event props.) Original Django monolith query construction step is here:
            // https://github.com/PostHog/posthog/blob/master/posthog/filters.py#L61-L84
            if !search_fields.is_empty() || !search_terms.as_ref().is_some_and(|s| s.is_empty()) {
                /* TODO: I don't think we need this cleansing step in the Rust service as Django does
                let cleansed_terms: Vec<String> = search
                    .as_ref()
                    .unwrap()
                    .iter()
                    .map(|s| s.replace("\0", ""))
                    .collect();
                */

                // TODO: this code is unhinged!! I'll circle back to refactor after
                // I battle the borrow checker some more, apologies! :)
                if let Some(terms) = search_terms {
                    for (tndx, term) in terms.iter().enumerate() {
                        if search_fields.is_empty() {
                            continue;
                        }
                        if tndx == 0 {
                            qb.push(" AND ((");
                        }
                        for (fndx, field) in search_fields.iter().enumerate() {
                            if fndx == 0 {
                                qb.push("(");
                            }
                            qb.push_bind(field.clone());
                            qb.push(" ILIKE '%");
                            qb.push_bind(term);
                            qb.push("%' ");
                            if search_fields.len() > 1 && fndx < search_fields.len() - 1 {
                                qb.push(" OR ");
                            }
                            if fndx == search_fields.len() - 1 {
                                qb.push(") ");
                            }
                        }
                        if terms.len() > 1 && tndx < terms.len() - 1 {
                            qb.push(" AND ");
                        }
                        if tndx == terms.len() - 1 {
                            qb.push(") ");
                            qb.push_bind(search_extras.clone());
                            qb.push(") ");
                        }
                    }
                }
            }
        }

        qb
    }

    fn conditionally_filter_event_names<'a>(
        &self,
        mut qb: QueryBuilder<'a, Postgres>,
        filter_by_event_names: &Option<bool>,
        event_names: &'a Option<Vec<String>>,
    ) -> QueryBuilder<'a, Postgres> {
        // conditionally apply event_names filter for outer query
        //
        // NOTE: the conditional join on event props table applied
        // above applies the same filter, but it can be an INNER or
        // LEFT join, so this is still required.
        if filter_by_event_names.is_some() && filter_by_event_names.unwrap() {
            if let Some(names) = event_names {
                if !names.is_empty() {
                    qb.push(" AND event = ANY(");
                    qb.push_bind(names);
                    qb.push(") ");
                }
            }
        }

        qb
    }

    fn conditionally_filter_feature_flags<'a>(
        &self,
        mut qb: QueryBuilder<'a, Postgres>,
        is_feature_flag: &Option<bool>,
    ) -> QueryBuilder<'a, Postgres> {
        // conditionally apply feature flag property filters
        if is_feature_flag.is_some_and(|iff| iff) {
            qb.push(" AND (name LIKE '$feature/%') ");
        } else {
            qb.push(" AND (name NOT LIKE '$feature/%') ");
        }

        qb
    }

    fn event_property_join_type(&self, filter_by_event_names: &Option<bool>) -> &str {
        if let Some(true) = filter_by_event_names {
            "INNER JOIN"
        } else {
            "LEFT JOIN"
        }
    }

    fn is_prop_type_event(&self, property_type: &str) -> bool {
        property_type == "event"
    }
}
