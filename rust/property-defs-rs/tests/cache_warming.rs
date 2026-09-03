use std::sync::Arc;

use sqlx::PgPool;

use property_defs_rs::{
    batch_ingestion::process_batch,
    cache_warming::{warm_team, WarmingLimits},
    config::Config,
    types::{EventProperty, PropertyDefinition, PropertyParentType, PropertyValueType, Update},
    update_cache::Cache,
};

fn test_lifecycle_handle() -> lifecycle::Handle {
    let mut manager = lifecycle::Manager::builder("test").build();
    manager.register("consumer", lifecycle::ComponentOptions::new())
}

const TEAM: i32 = 111;
const PROJECT: i64 = 111;

fn event_prop(event: &str, property: &str) -> Update {
    Update::EventProperty(EventProperty {
        team_id: TEAM,
        project_id: PROJECT,
        event: event.to_string(),
        property: property.to_string(),
    })
}

fn prop(name: &str, property_type: Option<PropertyValueType>) -> Update {
    Update::Property(PropertyDefinition {
        team_id: TEAM,
        project_id: PROJECT,
        name: name.to_string(),
        is_numerical: matches!(property_type, Some(PropertyValueType::Numeric)),
        property_type,
        event_type: PropertyParentType::Event,
        group_type_index: None,
    })
}

fn limits(eventprops: i64, propdefs: i64) -> WarmingLimits {
    WarmingLimits {
        eventprops_per_team: eventprops,
        propdefs_per_team: propdefs,
    }
}

// A warmed cache must answer exactly like the cache of the pod that wrote the
// rows: existing rows are covered (including the type-upgrade semantics of
// property definitions), unknown rows still miss.
#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_warm_team_covers_previously_written_rows(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();
    let writer_cache = Arc::new(Cache::new(1000, 1000, 1000));
    let batch = vec![
        event_prop("$pageview", "plan"),
        event_prop("$pageview", "browser"),
        prop("plan", Some(PropertyValueType::String)),
        prop("misc", None),
    ];
    process_batch(&config, writer_cache, &db, batch, &test_lifecycle_handle()).await;

    let warmed = Cache::new(1000, 1000, 1000);
    let (eventprops, propdefs) = warm_team(&db, &warmed, TEAM, PROJECT, limits(100, 100))
        .await
        .unwrap();
    assert_eq!(eventprops, 2);
    assert_eq!(propdefs, 2);

    assert!(warmed.contains_key(&event_prop("$pageview", "plan")));
    assert!(warmed.contains_key(&event_prop("$pageview", "browser")));
    assert!(!warmed.contains_key(&event_prop("$pageview", "unseen")));

    // A typed stored row can never change again, so both variants are covered.
    assert!(warmed.contains_key(&prop("plan", Some(PropertyValueType::String))));
    assert!(warmed.contains_key(&prop("plan", None)));

    // An untyped stored row covers untyped resends but must let a typed
    // sighting through to fill the NULL type.
    assert!(warmed.contains_key(&prop("misc", None)));
    assert!(!warmed.contains_key(&prop("misc", Some(PropertyValueType::Boolean))));
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_warm_team_respects_per_team_limits(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();
    let writer_cache = Arc::new(Cache::new(1000, 1000, 1000));
    let batch = vec![
        event_prop("$pageview", "a"),
        event_prop("$pageview", "b"),
        event_prop("$pageview", "c"),
        event_prop("$pageview", "d"),
    ];
    process_batch(&config, writer_cache, &db, batch, &test_lifecycle_handle()).await;

    let warmed = Cache::new(1000, 1000, 1000);
    let (eventprops, _) = warm_team(&db, &warmed, TEAM, PROJECT, limits(2, 100))
        .await
        .unwrap();
    assert_eq!(eventprops, 2, "the per-team cap must truncate the warm");
    assert_eq!(warmed.eventprops_len(), 2);
}
