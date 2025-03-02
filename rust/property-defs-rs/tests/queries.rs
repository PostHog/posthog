use property_defs_rs::api::v1::query::Manager;

use chrono::{DateTime, Utc};
use serde_json::json;
use sqlx::{postgres::PgArguments, Arguments, PgPool};
use uuid::Uuid;

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_simple_events_query(test_pool: PgPool) {
    // seed the test DB
    bootstrap_seed_data(test_pool.clone()).await.unwrap();

    // run some raw prop defs queries with various parameters
    // and assert expected rows are returned
    let _qmgr = Manager::new(test_pool.clone());

    // TODO: sanity check count and props queries; explore corner cases in other tests later :)
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
                (id, name, project_id, team_id, is_numerical, type, property_type, group_type_index)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        "#,
            args,
        )
        .execute(&test_pool)
        .await?;
    }

    // inject these into enterprise prop defs as "updated_by" and "verified_by" for realism
    let user_rows = [
        // id (PK), uuid, first_name, last_name, email, is_email_verified, distinct_id, temporary_token, hedgehog_config, role_at_organization
        (
            111,
            Uuid::now_v7(),
            "John",
            "Keister",
            "jk@example.com",
            true,
            Uuid::now_v7(),
            Uuid::now_v7(),
            json!(
                r#"{"skin": "default", "color": "purple", "enabled": false, "accessories": ["eyepatch", "xmas_scarf", "graduation"], "use_as_profile": false, "walking_enabled": true, "controls_enabled": true, "party_mode_enabled": true, "interactions_enabled": true}
"#
            ),
            "founder",
        ),
        (
            222,
            Uuid::now_v7(),
            "Nancy",
            "Guppy",
            "ng@example.com",
            true,
            Uuid::now_v7(),
            Uuid::now_v7(),
            json!(
                r#"{"skin": "spiderhog", "color": null, "enabled": false, "accessories": [], "use_as_profile": false, "walking_enabled": true, "controls_enabled": true, "party_mode_enabled": false, "interactions_enabled": true}"#
            ),
            "founder",
        ),
    ];

    for (ndx, row) in user_rows.iter().enumerate() {
        let mut args = PgArguments::default();
        args.add(row.0).unwrap();
        args.add(row.1).unwrap();
        args.add(format!("password_{}", ndx)).unwrap(); // password NOT NULL
        args.add(row.2).unwrap();
        args.add(row.3).unwrap();
        args.add(false).unwrap(); // is_staff NOT NULL
        args.add(true).unwrap(); // is_active NOT NULL
        args.add(row.4).unwrap();
        args.add(row.5).unwrap();
        args.add(row.6).unwrap();
        args.add(row.7).unwrap();
        args.add(&row.8).unwrap();
        args.add(row.9).unwrap();
        args.add(json!("{}")).unwrap(); // events_column_config NOT NULL
        args.add(Utc::now()).unwrap(); // date_joined NOT NULL

        sqlx::query_with(
            r#"
            INSERT INTO posthog_user
                (id, uuid, password, first_name, last_name, is_staff, is_active, email,
                 is_email_verified, distinct_id, temporary_token, hedgehog_config,
                 role_at_organization, events_column_config, date_joined)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
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
        (105, "$pageview", "attempted_event_type", 1, 1),
        (106, "$pageview", "$screen_width", 1, 1),
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
        args.add(&user_rows[0].0).unwrap();
        if ndx % 2 == 0 {
            args.add(true).unwrap();
            args.add(Some(Utc::now())).unwrap();
            args.add(Some(&user_rows[1].0)).unwrap();
            args.add(Some(vec!["foo", "bar"])).unwrap();
        } else {
            args.add(false).unwrap();
            args.add(None::<DateTime<Utc>>).unwrap();
            args.add(None::<String>).unwrap();
            args.add(None::<Vec<&str>>).unwrap();
        }

        sqlx::query_with(
            r#"
            INSERT INTO
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
