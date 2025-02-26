use chrono::{DateTime, Duration, Utc};
use property_defs_rs::types::{Event, PropertyParentType, PropertyValueType};
use serde_json::json;
use sqlx::postgres::PgArguments;
use sqlx::{Arguments, PgPool};
use uuid::Uuid;

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_updates(db: PgPool) {
    let properties = r#"
        {
            "TIMESTAMP": 5424245435435435,
            "some_string": "some_value",
            "some_int": 42,
            "some_float": 3.14,
            "some_bool": true,
            "some_bool_as_string": "true"
        }
    "#;
    let event_src = json!({
        "team_id": 1,
        "project_id": 1,
        "event": "update",
        "properties": properties
    });

    // Test fanout limiting
    let event = serde_json::from_value::<Event>(event_src.clone()).unwrap();
    let updates = event.into_updates(10);
    assert_eq!(updates.len(), 0);

    // Test that the event is correctly split into updates
    let event = serde_json::from_value::<Event>(event_src).unwrap();
    let updates = event.into_updates(1000);
    assert!(updates.len() == 13);

    let before = Utc::now();

    // issue them, and then query the database to see that everthing we expect to exist does
    for update in updates {
        update.issue(&db).await.unwrap();
    }

    assert_eventdefinition_exists(&db, "update", 1, before, Duration::seconds(1))
        .await
        .unwrap();
    assert_propertydefinition_exists(
        &db,
        "TIMESTAMP",
        PropertyParentType::Event,
        false,
        1,
        PropertyValueType::DateTime,
    )
    .await
    .unwrap();
    assert_propertydefinition_exists(
        &db,
        "some_string",
        PropertyParentType::Event,
        false,
        1,
        PropertyValueType::String,
    )
    .await
    .unwrap();
    assert_propertydefinition_exists(
        &db,
        "some_int",
        PropertyParentType::Event,
        true,
        1,
        PropertyValueType::Numeric,
    )
    .await
    .unwrap();
    assert_propertydefinition_exists(
        &db,
        "some_float",
        PropertyParentType::Event,
        true,
        1,
        PropertyValueType::Numeric,
    )
    .await
    .unwrap();
    assert_propertydefinition_exists(
        &db,
        "some_bool",
        PropertyParentType::Event,
        false,
        1,
        PropertyValueType::Boolean,
    )
    .await
    .unwrap();
    assert_propertydefinition_exists(
        &db,
        "some_bool_as_string",
        PropertyParentType::Event,
        false,
        1,
        PropertyValueType::Boolean,
    )
    .await
    .unwrap();
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_update_on_project_id_conflict(db: PgPool) {
    let definition_created_at: DateTime<Utc> = Utc::now() - Duration::days(1);
    let mut args = PgArguments::default();
    args.add(Uuid::now_v7()).unwrap();
    args.add("foo").unwrap();
    args.add(1).unwrap();
    args.add(definition_created_at).unwrap();
    sqlx::query_with(
        r#"
        INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, project_id, last_seen_at, created_at)
        VALUES ($1, $2, NULL, NULL, $3, NULL, $4, $4) -- project_id is NULL! This definition is from before environments
    "#, args
    ).execute(&db).await.unwrap();

    assert_eventdefinition_exists(
        &db,
        "foo",
        1,
        definition_created_at,
        Duration::milliseconds(0),
    )
    .await
    .unwrap();

    let before = Utc::now();
    let event_src = json!({
        "team_id": 3,
        "project_id": 1,
        "event": "foo",
        "properties": "{}"
    });

    let event = serde_json::from_value::<Event>(event_src.clone()).unwrap();
    for update in event.into_updates(10000) {
        update.issue(&db).await.unwrap();
    }

    // The event def we created earlier got updated, even though it has a different `team_id`,
    // because `coalesce(project_id, team_id)` matches
    assert_eventdefinition_exists(&db, "foo", 1, before, Duration::seconds(1))
        .await
        .unwrap();
}

async fn assert_eventdefinition_exists(
    db: &PgPool,
    name: &str,
    team_id: i32,
    before: DateTime<Utc>,
    last_seen_range: Duration,
) -> Result<(), ()> {
    // Event definitions are inserted with a last_seen that's exactly when the insert is done. We check if an entry exists in the
    // database with a last_seen that's in the right range to ensure that the event definition was inserted correctly.
    let after = before + last_seen_range;

    let count: Option<i64> = sqlx::query_scalar(
        r#"
        SELECT COUNT(*)
        FROM posthog_eventdefinition
        WHERE name = $1 AND team_id = $2 AND last_seen_at >= $3 AND last_seen_at <= $4
        "#,
    )
    .bind(name)
    .bind(team_id)
    .bind(before)
    .bind(after)
    .fetch_one(db)
    .await
    .unwrap();

    if count == Some(1) {
        Ok(())
    } else {
        Err(())
    }
}

async fn assert_propertydefinition_exists(
    db: &PgPool,
    name: &str,
    event_type: PropertyParentType,
    is_numerical: bool,
    team_id: i32,
    property_type: PropertyValueType,
) -> Result<(), ()> {
    println!("Checking property definition for {}", name);
    let count: Option<i64> = sqlx::query_scalar(
        r#"
        SELECT COUNT(*)
        FROM posthog_propertydefinition
        WHERE name = $1 AND type = $2 AND is_numerical = $3 AND team_id = $4 AND property_type = $5
        "#,
    )
    .bind(name)
    .bind(event_type as i32)
    .bind(is_numerical)
    .bind(team_id)
    .bind(property_type.to_string())
    .fetch_one(db)
    .await
    .unwrap();

    if count == Some(1) {
        Ok(())
    } else {
        Err(())
    }
}
