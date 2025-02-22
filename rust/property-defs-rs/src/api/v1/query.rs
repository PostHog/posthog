use crate::{
    api::v1::constants::{
        extract_aliases,
        POSTHOG_EVENT_PROPERTY_TABLE_NAME_ALIAS,
        EVENTS_HIDDEN_PROPERTY_DEFINITIONS,
        SEARCH_SCREEN_WORD,
        SEARCH_TRIGGER_WORD,
    },
    //metrics_consts::{},
    config::Config,
};

use sqlx::{postgres::PgPoolOptions, PgPool, Postgres, QueryBuilder};

use std::collections::HashMap;

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

    pub fn count_query<'a>(
        &self,
        project_id: i32,
        search_terms: &Option<Vec<String>>,
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

        // conditionally apply search term matching; skip this if possible, it's not cheap!
        // logic: https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L493-L499
        if search_terms.as_ref().is_some_and(|terms| !terms.is_empty()) {
            // step 1: prep list of legal search fields (default: just property "name")
            // TODO: augment w/user-supplied fields to search in? verify in Django orig
            let mut search_fields = vec!["name"];

            // step 2: identify property def "aliases" to enrich our fuzzy matching; see also:
            // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L309-L324

            // attempt to enrich basic search terms using a heuristic:
            // if the long slug associated with any std PostHog event properties
            // matches *every search term* in the incoming query, capture the
            // associated property name and add it to the search terms we'll
            // attempt to return from the prop defs query. This is expensive :(
            let term_aliases: Vec<&str> = self.search_term_aliases
                .iter()
                .filter(|(_key, prop_long_slug)|
                    search_terms
                        .as_ref()
                        .unwrap()
                        .iter()
                        .all(|term| prop_long_slug.contains(term)))
                .map(|(key, _matched_slug)| *key)
                .collect();

            // build a query fragment if we found aliases. We can do this
            // outside of the builder because these aren't user inputs
            let search_extras = if !term_aliases.is_empty() {
                format!(" OR name = ANY(ARRAY[{}])",
                    term_aliases
                        .iter()
                        .map(|ta| format!("'{}'", ta))
                        .collect::<Vec<_>>()
                        .join(", "))
            } else { "".to_string() };

            // step 3: filter "initial" prop defs if the user wants "latest"
            // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L326-L339
            let screening_clause = if term_aliases.iter().any(|ta| *ta == SEARCH_TRIGGER_WORD) {
                format!(" OR NOT name ILIKE '%{}%'", SEARCH_SCREEN_WORD)
            } else { "".to_string() };

            // step 3.5: join whatever we found in search_extras and trigger word result
            let search_extras = format!("{}{}", search_extras, screening_clause);

            // step 4: generate the search SQL which consistes of nested AND/OR clauses of arbitrary size,
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
                            continue
                        }
                        if tndx == 0 {
                            qb.push(" AND ((");
                        }
                        for (fndx, field ) in search_fields.iter().enumerate() {
                            if fndx == 0 {
                                qb.push("(");
                            }
                            qb.push_bind(*field);
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

        // conditionally apply event_names filter for outer query
        //
        // NOTE: the conditional join on event props table applied
        // above applies the same filter, but it can be an INNER or
        // LEFT join, so this is still required.
        if filter_by_event_names.is_some() && filter_by_event_names.unwrap() {
            if let Some(names) = event_names {
                if names.len() > 0 {
                    qb.push(" AND event = ANY(");
                    qb.push_bind(names);
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
        search_terms: &Option<Vec<String>>,
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
        if use_enterprise_taxonomy.is_some_and(|uet| uet == true) {
            // borrowed from EnterprisePropertyDefinition from Django monolith
            // via EnterprisePropertyDefinition._meta.get_fields()
            qb.push("id, project, team, name, is_numerical, property_type, type, group_type_index, property_type_format, description, updated_at, updated_by, verified_at, verified_by ");
        } else {
            // borrowed from Django monolith via PropertyDefinition._meta.get_fields()
            qb.push("id, project, team, name, is_numerical, property_type, type, group_type_index, property_type_format ");
        }

        // append event_property_field clause to SELECT clause
        let is_seen_resolved = if event_names.as_ref().is_some_and(|evs| !evs.is_empty()) {
            format!("{}.property", POSTHOG_EVENT_PROPERTY_TABLE_NAME_ALIAS)
        } else {
            "NULL".to_string()
        };
        qb.push(format!(", {} IS NOT NULL AS is_seen_on_filtered_events ", is_seen_resolved));
       
        // TODO(eli): FROM clause (self.table?!)

        // conditionally join on event properties table
        // this join is only applied if the query is scoped to type "event"
        if self.is_prop_type_event(property_type) {
            qb.push(self.event_property_join_type(filter_by_event_names));
            qb.push(" (SELECT DISTINCT property FROM ");
            qb.push_bind(&self.event_props_table);
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

        // conditionally apply search term matching; skip this if possible, it's not cheap!
        // logic: https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L493-L499
        if search_terms.as_ref().is_some_and(|terms| !terms.is_empty()) {
            // step 1: prep list of legal search fields (default: just property "name")
            // TODO: augment w/user-supplied fields to search in? verify in Django orig
            let mut search_fields = vec!["name"];

            // step 2: identify property def "aliases" to enrich our fuzzy matching; see also:
            // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L309-L324

            // attempt to enrich basic search terms using a heuristic:
            // if the long slug associated with any std PostHog event properties
            // matches *every search term* in the incoming query, capture the
            // associated property name and add it to the search terms we'll
            // attempt to return from the prop defs query. This is expensive :(
            let term_aliases: Vec<&str> = self.search_term_aliases
                .iter()
                .filter(|(_key, prop_long_slug)|
                    search_terms
                        .as_ref()
                        .unwrap()
                        .iter()
                        .all(|term| prop_long_slug.contains(term)))
                .map(|(key, _matched_slug)| *key)
                .collect();

            // build a query fragment if we found aliases. We can do this
            // outside of the builder because these aren't user inputs
            let search_extras = if !term_aliases.is_empty() {
                format!(" OR name = ANY(ARRAY[{}])",
                    term_aliases
                        .iter()
                        .map(|ta| format!("'{}'", ta))
                        .collect::<Vec<_>>()
                        .join(", "))
            } else { "".to_string() };

            // step 3: filter "initial" prop defs if the user wants "latest"
            // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L326-L339
            let screening_clause = if term_aliases.iter().any(|ta| *ta == SEARCH_TRIGGER_WORD) {
                format!(" OR NOT name ILIKE '%{}%'", SEARCH_SCREEN_WORD)
            } else { "".to_string() };

            // step 3.5: join whatever we found in search_extras and trigger word result
            let search_extras = format!("{}{}", search_extras, screening_clause);

            // step 4: generate the search SQL which consistes of nested AND/OR clauses of arbitrary size,
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
                            continue
                        }
                        if tndx == 0 {
                            qb.push(" AND ((");
                        }
                        for (fndx, field ) in search_fields.iter().enumerate() {
                            if fndx == 0 {
                                qb.push("(");
                            }
                            qb.push_bind(*field);
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

        // conditionally apply event_names filter for outer query
        //
        // NOTE: the conditional join on event props table applied
        // above applies the same filter, but it can be an INNER or
        // LEFT join, so this is still required.
        if filter_by_event_names.is_some() && filter_by_event_names.unwrap() {
            if let Some(names) = event_names {
                if names.len() > 0 {
                    qb.push(" AND event = ANY(");
                    qb.push_bind(names);
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

        // ORDER BY clauses
        qb.push("ORDER BY is_seen_on_filtered_events DESC, ");
        if order_by_verified {
            qb.push("verified DESC NULLS LAST, ");
        }
        qb.push(format!("{}.name ASC ", &self.prop_defs_table));

        // LIMIT and OFFSET clauses
        qb.push("LIMIT ");
        qb.push_bind(limit);
        qb.push("OFFSET ");
        qb.push_bind(offset);

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
