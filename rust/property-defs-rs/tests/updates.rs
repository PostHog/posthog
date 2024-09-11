use chrono::{DateTime, Duration, Utc};
use property_defs_rs::types::{Event, PropertyParentType, PropertyValueType};
use serde_json::json;
use sqlx::PgPool;

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
