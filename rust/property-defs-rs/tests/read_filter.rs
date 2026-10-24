use std::sync::Arc;
use std::time::Duration;

use chrono::{Duration as ChronoDuration, Utc};
use sqlx::PgPool;

use property_defs_rs::{
    batch_ingestion::{
        process_batch, EventDefinitionsBatch, EventPropertiesBatch, PropertyDefinitionsBatch,
    },
    config::Config,
    read_filter::{filter_event_definitions, filter_event_properties, filter_property_definitions},
    types::{
        EventDefinition, EventProperty, PropertyDefinition, PropertyParentType, PropertyValueType,
        Update,
    },
    update_cache::Cache,
};

fn test_lifecycle_handle() -> lifecycle::Handle {
    let mut manager = lifecycle::Manager::builder("test").build();
    manager.register("consumer", lifecycle::ComponentOptions::new())
}

const TEAM: i32 = 111;
const PROJECT: i64 = 111;
const BUDGET: Duration = Duration::from_secs(5);

fn event_prop(property: &str) -> EventProperty {
    EventProperty {
        team_id: TEAM,
        project_id: PROJECT,
        event: "$pageview".to_string(),
        property: property.to_string(),
    }
}

fn prop_def(name: &str, property_type: Option<PropertyValueType>) -> PropertyDefinition {
    PropertyDefinition {
        team_id: TEAM,
        project_id: PROJECT,
        name: name.to_string(),
        is_numerical: matches!(property_type, Some(PropertyValueType::Numeric)),
        property_type,
        event_type: PropertyParentType::Event,
        group_type_index: None,
    }
}

async fn seed(db: &PgPool, batch: Vec<Update>) {
    let config = Config::init_with_defaults().unwrap();
    let cache = Arc::new(Cache::new(1000, 1000, 1000));
    process_batch(&config, cache, db, None, batch, &test_lifecycle_handle()).await;
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_filter_drops_existing_event_properties(db: PgPool) {
    seed(
        &db,
        vec![
            Update::EventProperty(event_prop("plan")),
            Update::EventProperty(event_prop("browser")),
        ],
    )
    .await;

    let mut batch = EventPropertiesBatch::new(10);
    batch.append(event_prop("plan"));
    batch.append(event_prop("fresh"));
    batch.append(event_prop("browser"));

    filter_event_properties(&db, &mut batch, BUDGET).await;

    assert_eq!(batch.len(), 1, "only the unknown row survives the filter");
    assert_eq!(batch.property_names, vec!["fresh".to_string()]);
}

// A row is dropped only when the stored last_seen_at is already inside the
// incoming row's floor period; older rows and unknown names still reach the writer.
#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_filter_drops_event_definitions_seen_this_period(db: PgPool) {
    let now = Utc::now();
    for (name, last_seen) in [("current", now), ("stale", now - ChronoDuration::hours(2))] {
        sqlx::query(
            "INSERT INTO posthog_eventdefinition (id, name, team_id, project_id, last_seen_at, created_at)
             VALUES (gen_random_uuid(), $1, $2, $3, $4, $4)",
        )
        .bind(name)
        .bind(TEAM)
        .bind(PROJECT)
        .bind(last_seen)
        .execute(&db)
        .await
        .unwrap();
    }

    let period_start = now - ChronoDuration::minutes(30);
    let mut batch = EventDefinitionsBatch::new(10);
    for name in ["current", "stale", "fresh"] {
        batch.append(EventDefinition {
            name: name.to_string(),
            team_id: TEAM,
            project_id: PROJECT,
            last_seen_at: period_start,
        });
    }

    filter_event_definitions(&db, &mut batch, BUDGET).await;

    assert_eq!(batch.names, vec!["stale".to_string(), "fresh".to_string()]);
}

// The filter mirrors the upsert's DO UPDATE guard: an existing row is dropped
// unless it is untyped and the incoming update carries a type.
#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_filter_keeps_new_rows_and_type_upgrades(db: PgPool) {
    seed(
        &db,
        vec![
            Update::Property(prop_def("plan", Some(PropertyValueType::String))),
            Update::Property(prop_def("misc", None)),
        ],
    )
    .await;

    let cache = Cache::new(1000, 1000, 1000);
    let mut batch = PropertyDefinitionsBatch::new(10);
    batch.append(prop_def("plan", Some(PropertyValueType::String)));
    batch.append(prop_def("plan", Some(PropertyValueType::DateTime)));
    batch.append(prop_def("misc", None));
    batch.append(prop_def("misc", Some(PropertyValueType::Boolean)));
    batch.append(prop_def("fresh", None));

    filter_property_definitions(&db, &cache, &mut batch, BUDGET).await;

    assert_eq!(
        batch.names,
        vec!["misc".to_string(), "fresh".to_string()],
        "kept: the untyped-to-typed upgrade and the unknown row"
    );

    // Dropped typed rows refresh the cache with the stored type, so both
    // variants of "plan" now hit in memory instead of re-probing the reader.
    assert!(cache.contains_key(&Update::Property(prop_def(
        "plan",
        Some(PropertyValueType::DateTime)
    ))));
    assert!(cache.contains_key(&Update::Property(prop_def("plan", None))));
}

// End to end through process_batch: with the read pool set, a repeated batch
// still lands its genuinely new row.
#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_process_batch_with_read_pool_writes_new_rows(db: PgPool) {
    seed(&db, vec![Update::EventProperty(event_prop("plan"))]).await;

    let config = Config::init_with_defaults().unwrap();
    let cache = Arc::new(Cache::new(1000, 1000, 1000));
    let batch = vec![
        Update::EventProperty(event_prop("plan")),
        Update::EventProperty(event_prop("fresh")),
    ];
    process_batch(
        &config,
        cache,
        &db,
        Some(db.clone()),
        batch,
        &test_lifecycle_handle(),
    )
    .await;

    let count: i64 = sqlx::query_scalar(
        "SELECT count(*) FROM posthog_eventproperty WHERE property IN ('plan', 'fresh')",
    )
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(
        count, 2,
        "the new row must persist alongside the seeded one"
    );
}
