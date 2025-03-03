use property_defs_rs::api::v1::{query::Manager, routing::Params};

use chrono::{DateTime, Utc};
use sqlx::{postgres::PgArguments, Arguments, Executor, PgPool, Row};
use uuid::Uuid;

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_property_definitions_queries(test_pool: PgPool) {
    // seed the test DB
    bootstrap_seed_data(test_pool.clone()).await.unwrap();

    // plumbing that won't change during the test suite exec
    let qmgr = Manager::new(test_pool.clone()).await.unwrap();
    let project_id = 1;

    //
    // unit tests
    //

    // PropertyParentType::Event scoped tests
    query_type_event_no_filters(&qmgr, project_id).await;
    query_type_event_properties_filter(&qmgr, project_id).await;
    query_type_event_excluded_props_filter(&qmgr, project_id).await;
    query_type_event_names_filter(&qmgr, project_id).await;
    query_type_event_is_numerical_filter(&qmgr, project_id).await;
    query_type_event_is_feature_flag_filter(&qmgr, project_id).await;
    query_type_event_is_not_feature_flag_filter(&qmgr, project_id).await;
}

// fetch all PropertyParentType::Event records without filtering
async fn query_type_event_no_filters(qmgr: &Manager, project_id: i32) {
    let mut qb = sqlx::QueryBuilder::new("");
    let params = Params::default();

    // sanity check query with default arguments; TODO: exercise filter params, corner cases, etc.
    let count_events_unfiltered = qmgr.count_query(&mut qb, project_id, &params);
    let result = qmgr.pool.fetch_one(count_events_unfiltered).await;
    assert!(result.is_ok());

    let total_count: i64 = result.unwrap().get(0);
    let expected_event_rows: i64 = 9;
    assert_eq!(expected_event_rows, total_count);

    let mut qb = sqlx::QueryBuilder::new("");
    let fetch_events_unfiltered = qmgr.property_definitions_query(&mut qb, project_id, &params);
    let results = qmgr.pool.fetch_all(fetch_events_unfiltered).await;
    assert!(results.is_ok());
    for row in results.unwrap() {
        let prop_name: String = row.get("name");
        assert!(expected_event_props_all().contains(&prop_name.as_str()))
    }
}

// fetch all PropertyParentType::Event records with a "properties" (prop name) filter
async fn query_type_event_properties_filter(qmgr: &Manager, project_id: i32) {
    let mut qb = sqlx::QueryBuilder::new("");

    let mut params = Params::default();
    let expected_props = vec!["$time".to_string(), "user_email".to_string()];
    params.properties = expected_props.clone();

    let count_events_props_filter = qmgr.count_query(&mut qb, project_id, &params);
    let result = qmgr.pool.fetch_one(count_events_props_filter).await;
    assert!(result.is_ok());

    let total_count: i64 = result.unwrap().get(0);
    let expected_event_rows: i64 = 2;
    assert_eq!(expected_event_rows, total_count);

    // should only return type "event" records matching the prop names in the "properties" filter
    let mut qb = sqlx::QueryBuilder::new("");
    let fetch_events_props_filter = qmgr.property_definitions_query(&mut qb, project_id, &params);
    let results = qmgr.pool.fetch_all(fetch_events_props_filter).await;
    assert!(results.is_ok());

    for row in results.unwrap() {
        let prop_name: String = row.get("name");
        assert!(expected_props.contains(&prop_name))
    }
}

// fetch all PropertyParentType::Event records with a "excluded_properties" (prop name) filter
async fn query_type_event_excluded_props_filter(qmgr: &Manager, project_id: i32) {
    let mut qb = sqlx::QueryBuilder::new("");

    let params = Params {
        excluded_properties: vec!["$time".to_string(), "user_email".to_string()],
        ..Default::default()
    };

    let count_events_ex_props_filter = qmgr.count_query(&mut qb, project_id, &params);
    let result = qmgr.pool.fetch_one(count_events_ex_props_filter).await;
    assert!(result.is_ok());

    let total_count: i64 = result.unwrap().get(0);
    let expected_event_rows: i64 = 7;
    assert_eq!(expected_event_rows, total_count);

    let mut qb = sqlx::QueryBuilder::new("");
    let fetch_events_ex_props_filter =
        qmgr.property_definitions_query(&mut qb, project_id, &params);
    let results = qmgr.pool.fetch_all(fetch_events_ex_props_filter).await;
    assert!(results.is_ok());

    // all seed events *except* the two filtered by "excluded_properties" should be present
    let expected_props: Vec<&str> = expected_event_props_all()
        .into_iter()
        .filter(|prop_name| !["$time", "user_email"].contains(prop_name))
        .collect();
    for row in results.unwrap() {
        let prop_name: String = row.get("name");
        assert!(expected_props.contains(&prop_name.as_str()))
    }
}

// fetch all PropertyParentType::Event records (properties) matching the "event_names"
// (particular event) filter. This is determined by a JOIN on the posthog_eventproperty table
async fn query_type_event_names_filter(qmgr: &Manager, project_id: i32) {
    let mut qb = sqlx::QueryBuilder::new("");

    let params = Params {
        event_names: vec!["$pageview".to_string()],
        ..Default::default()
    };

    let count_events_names_filter = qmgr.count_query(&mut qb, project_id, &params);
    let result = qmgr.pool.fetch_one(count_events_names_filter).await;
    assert!(result.is_ok());

    let total_count: i64 = result.unwrap().get(0);
    let expected_event_rows: i64 = 7;
    assert_eq!(expected_event_rows, total_count);

    let mut qb = sqlx::QueryBuilder::new("");
    let fetch_events_names_filter = qmgr.property_definitions_query(&mut qb, project_id, &params);
    let results = qmgr.pool.fetch_all(fetch_events_names_filter).await;
    assert!(results.is_ok());

    // all seed events *except* the two filtered by parent event name != "$pageview" should be present
    let expected_props: Vec<&str> = expected_event_props_all()
        .into_iter()
        .filter(|prop_name| !["attempted_event", "$screen_width"].contains(prop_name))
        .collect();
    for row in results.unwrap() {
        let prop_name: String = row.get("name");
        assert!(expected_props.contains(&prop_name.as_str()))
    }
}

// fetch only PropertyParentType::Event records of type "Numeric" (where is_numerical column == true)
async fn query_type_event_is_numerical_filter(qmgr: &Manager, project_id: i32) {
    let mut qb = sqlx::QueryBuilder::new("");

    let params = Params {
        is_numerical: true,
        ..Default::default()
    };

    let count_events_ex_props_filter = qmgr.count_query(&mut qb, project_id, &params);
    let result = qmgr.pool.fetch_one(count_events_ex_props_filter).await;
    assert!(result.is_ok());

    let total_count: i64 = result.unwrap().get(0);
    let expected_event_rows: i64 = 2;
    assert_eq!(expected_event_rows, total_count);

    let mut qb = sqlx::QueryBuilder::new("");
    let fetch_events_ex_props_filter =
        qmgr.property_definitions_query(&mut qb, project_id, &params);
    let results = qmgr.pool.fetch_all(fetch_events_ex_props_filter).await;
    assert!(results.is_ok());

    // should only return PropertyParentType::Event records of property_type="Numeric"
    for row in results.unwrap() {
        let prop_type: String = row.get("property_type");
        assert!(prop_type == "Numeric");
    }
}

// fetch only PropertyParentType::Event records where the property is a feature flag
async fn query_type_event_is_feature_flag_filter(qmgr: &Manager, project_id: i32) {
    let mut qb = sqlx::QueryBuilder::new("");

    let params = Params {
        is_feature_flag: Some(true),
        ..Default::default()
    };

    let count_events_ex_props_filter = qmgr.count_query(&mut qb, project_id, &params);
    let result = qmgr.pool.fetch_one(count_events_ex_props_filter).await;
    assert!(result.is_ok());

    let total_count: i64 = result.unwrap().get(0);
    let expected_event_rows: i64 = 1;
    assert_eq!(expected_event_rows, total_count);

    let mut qb = sqlx::QueryBuilder::new("");
    let fetch_events_ex_props_filter =
        qmgr.property_definitions_query(&mut qb, project_id, &params);
    let results = qmgr.pool.fetch_all(fetch_events_ex_props_filter).await;
    assert!(results.is_ok());

    // should only return PropertyParentType::Event records of property_type="Numeric"
    for row in results.unwrap() {
        let prop_type: String = row.get("name");
        assert!(prop_type == "$feature/foo-bar-baz");
    }
}

// fetch all PropertyParentType::Event records that are *not* feature flag props
async fn query_type_event_is_not_feature_flag_filter(qmgr: &Manager, project_id: i32) {
    let mut qb = sqlx::QueryBuilder::new("");

    let params = Params {
        is_feature_flag: Some(false),
        ..Default::default()
    };

    let count_events_names_filter = qmgr.count_query(&mut qb, project_id, &params);
    let result = qmgr.pool.fetch_one(count_events_names_filter).await;
    assert!(result.is_ok());

    let total_count: i64 = result.unwrap().get(0);
    let expected_event_rows: i64 = 8;
    assert_eq!(expected_event_rows, total_count);

    let mut qb = sqlx::QueryBuilder::new("");
    let fetch_events_names_filter = qmgr.property_definitions_query(&mut qb, project_id, &params);
    let results = qmgr.pool.fetch_all(fetch_events_names_filter).await;
    assert!(results.is_ok());

    // all seed events *except* the two filtered by parent event name != "$pageview" should be present
    let expected_props: Vec<&str> = expected_event_props_all()
        .into_iter()
        .filter(|prop_name| !["$feature/foo-bar-baz"].contains(prop_name))
        .collect();
    for row in results.unwrap() {
        let prop_name: String = row.get("name");
        assert!(expected_props.contains(&prop_name.as_str()))
    }
}

// the property names of all PropertyParentType::Event rows
fn expected_event_props_all() -> [&'static str; 9] {
    [
        "user_email",
        "utm_source",
        "$time",
        "$sent_at",
        "attempted_event_type",
        "$screen_width",
        "session_timeout_ms",
        "$dead_clicks_enabled_server_side",
        "$feature/foo-bar-baz",
    ]
}

async fn bootstrap_seed_data(test_pool: PgPool) -> Result<(), sqlx::Error> {
    // posthog_propertydefinition: (id, name, project_id, team_id, is_numerical, type, property_type, group_type_index)
    let pd_rows = [
        // PropertyParentType::Event
        (Uuid::now_v7(), "user_email", 1, 1, false, 1, "String", -1),
        (Uuid::now_v7(), "utm_source", 1, 1, false, 1, "String", -1),
        (Uuid::now_v7(), "$time", 1, 1, false, 1, "DateTime", -1),
        (Uuid::now_v7(), "$sent_at", 1, 1, false, 1, "DateTime", -1),
        (
            Uuid::now_v7(),
            "attempted_event_type",
            1,
            1,
            true,
            1,
            "Numeric",
            -1,
        ),
        (
            Uuid::now_v7(),
            "$screen_width",
            1,
            1,
            true,
            1,
            "Numeric",
            -1,
        ),
        (
            Uuid::now_v7(),
            "session_timeout_ms",
            1,
            1,
            false,
            1,
            "Duration",
            -1,
        ),
        (
            Uuid::now_v7(),
            "$dead_clicks_enabled_server_side",
            1,
            1,
            false,
            1,
            "Boolean",
            -1,
        ),
        // feature flag (filterable w/query param)
        (
            Uuid::now_v7(),
            "$feature/foo-bar-baz",
            1,
            1,
            false,
            1,
            "Boolean",
            -1,
        ),
        // PropertyParentType::Person
        (
            Uuid::now_v7(),
            "$feature_enrollment/artificial-hog",
            1,
            1,
            false,
            2,
            "Boolean",
            -1,
        ),
        (
            Uuid::now_v7(),
            "$survey_dismissed/abc123",
            1,
            1,
            false,
            2,
            "Boolean",
            -1,
        ),
        (Uuid::now_v7(), "company_type", 1, 1, false, 2, "String", -1),
        (Uuid::now_v7(), "$os_version", 1, 1, false, 2, "String", -1),
        (Uuid::now_v7(), "created_at", 1, 1, false, 2, "DateTime", -1),
        (Uuid::now_v7(), "hire_date", 1, 1, false, 2, "DateTime", -1),
        // query param "latest" filter will apply to these (eliminates "initial" props)
        (
            Uuid::now_v7(),
            "$initial_geoip_postal_code",
            1,
            1,
            true,
            2,
            "Numeric",
            -1,
        ),
        (
            Uuid::now_v7(),
            "$initial_geoip_longitude",
            1,
            1,
            true,
            2,
            "Numeric",
            -1,
        ),
        // PropertyParentType::Group (1 for each valid property_type and group_type_index)
        (Uuid::now_v7(), "instance_name", 1, 1, false, 3, "String", 0),
        (Uuid::now_v7(), "project_name", 1, 1, false, 3, "String", 1),
        (Uuid::now_v7(), "timezone", 1, 1, false, 3, "String", 2),
        (Uuid::now_v7(), "city", 1, 1, false, 3, "String", 3),
        (
            Uuid::now_v7(),
            "integration_id",
            1,
            1,
            false,
            3,
            "String",
            4,
        ),
        (
            Uuid::now_v7(),
            "total_registrations",
            1,
            1,
            true,
            3,
            "Numeric",
            0,
        ),
        (
            Uuid::now_v7(),
            "web_events_count_in_period",
            1,
            1,
            true,
            3,
            "Numeric",
            1,
        ),
        (
            Uuid::now_v7(),
            "group_types_total",
            1,
            1,
            true,
            3,
            "Numeric",
            2,
        ),
        (Uuid::now_v7(), "min_age", 1, 1, true, 3, "Numeric", 3),
        (Uuid::now_v7(), "PlanValue", 1, 1, true, 3, "Numeric", 4),
        (Uuid::now_v7(), "signup_date", 1, 1, false, 3, "DateTime", 0),
        (
            Uuid::now_v7(),
            "last_recorded_date",
            1,
            1,
            false,
            3,
            "DateTime",
            1,
        ),
        (
            Uuid::now_v7(),
            "group_createdAt",
            1,
            1,
            false,
            3,
            "DateTime",
            2,
        ),
        (
            Uuid::now_v7(),
            "subscription_end",
            1,
            1,
            false,
            3,
            "DateTime",
            3,
        ),
        (
            Uuid::now_v7(),
            "subscription_next_refresh",
            1,
            1,
            false,
            3,
            "DateTime",
            4,
        ),
        (
            Uuid::now_v7(),
            "ingested_event",
            1,
            1,
            false,
            3,
            "Boolean",
            0,
        ),
        (
            Uuid::now_v7(),
            "isIssueRiskSet",
            1,
            1,
            false,
            3,
            "Boolean",
            1,
        ),
        (
            Uuid::now_v7(),
            "features.supplier360.products.1.enabled",
            1,
            1,
            false,
            3,
            "Boolean",
            2,
        ),
        (
            Uuid::now_v7(),
            "is_project_demo",
            1,
            1,
            false,
            3,
            "Boolean",
            3,
        ),
        (
            Uuid::now_v7(),
            "subscription_is_trial",
            1,
            1,
            false,
            3,
            "Boolean",
            4,
        ),
        // NOTE: some event flavors are not represented in the test seeds (yet!)
        // - no records of type PropertyParentType::Session in the prod DB
        // - no records in the prod DB of property_type "Duration"
    ];

    for row in pd_rows.iter() {
        let mut args = PgArguments::default();
        args.add(row.0).unwrap();
        args.add(row.1).unwrap();
        args.add(row.2).unwrap();
        args.add(row.3).unwrap();
        args.add(row.4).unwrap();
        args.add(row.5).unwrap();
        args.add(row.6).unwrap();
        args.add(row.7).unwrap();

        sqlx::query_with(
            r#"
            INSERT INTO posthog_propertydefinition
                (id, name, project_id, team_id, is_numerical, "type", property_type, group_type_index)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        "#,
            args,
        )
        .execute(&test_pool)
        .await?;
    }

    // tie back event props "property" field to posthog_userdefinition rows
    // of type PropertyParentType::Event defined above
    let ep_rows = [
        // id, event, property, team_id, project_id
        (101, "$pageview", "user_email", 1, 1),
        (102, "$pageview", "utm_source", 1, 1),
        (103, "$pageview", "$time", 1, 1),
        (104, "$pageview", "$sent_at", 1, 1),
        (105, "$other_event", "attempted_event_type", 1, 1), // won't be returned in event_names=$pageview filtered queries
        (106, "$other_event", "$screen_width", 1, 1), // won't be returned in event_names=$pageview filtered queries
        (107, "$pageview", "session_timeout_ms", 1, 1),
        (108, "$pageview", "$dead_clicks_enabled_server_side", 1, 1),
        (109, "$pageview", "$feature/foo-bar-baz", 1, 1),
    ];

    for row in ep_rows.iter() {
        let mut args = PgArguments::default();
        args.add(row.0).unwrap();
        args.add(row.1).unwrap();
        args.add(row.2).unwrap();
        args.add(row.3).unwrap();
        args.add(row.4).unwrap();

        sqlx::query_with(
            r#"
            INSERT INTO posthog_eventproperty
                (id, event, property, team_id, project_id)
                VALUES ($1, $2, $3, $4, $5)
        "#,
            args,
        )
        .execute(&test_pool)
        .await?;
    }

    // enterprise prop defs rows are a bit different - these mostly serve to join in metadata
    // on popsthog_propertydefinition rows we defined above, so we seed using those rows
    for (ndx, row) in pd_rows.iter().enumerate() {
        // for now, only assign joinable enterprise prop rows for
        // PropertyParentType(s) of Event and Person
        if row.5 > 2 {
            continue;
        }
        let mut args = PgArguments::default();
        args.add(row.0).unwrap();
        args.add("a fine property indeed").unwrap();
        args.add(Utc::now()).unwrap();
        args.add(ndx as i64).unwrap();
        if ndx % 2 == 0 {
            args.add(true).unwrap();
            args.add(Some(Utc::now())).unwrap();
            args.add(Some(ndx as i64)).unwrap();
            args.add(Some(vec!["foo", "bar"])).unwrap();
        } else {
            args.add(false).unwrap();
            args.add(None::<DateTime<Utc>>).unwrap();
            args.add(None::<i64>).unwrap();
            args.add(None::<Vec<&str>>).unwrap();
        }

        sqlx::query_with(
            r#"
            INSERT INTO ee_enterprisepropertydefinition
                (propertydefinition_ptr_id, description, updated_at, updated_by_id, verified, verified_at, verified_by_id, tags)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        "#,
            args,
        )
        .execute(&test_pool)
        .await?;
    }

    Ok(())
}
