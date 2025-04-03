use std::collections::HashMap;
use std::sync::Arc;

use chrono::Utc;
use quick_cache::sync::Cache as InMemoryCache;
use rand::Rng;
use serde_json::{json, Value};
use sqlx::PgPool;

use property_defs_rs::{
    cache::{LayeredCache, NoOpCache, SecondaryCache},
    config::Config,
    types::{Event, PropertyParentType, Update, EventProperty},
    v2_batch_ingestion::process_batch_v2,
};

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_simple_batch_write(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();
    let memory = Arc::new(InMemoryCache::new(config.cache_capacity));
    let secondary = SecondaryCache::NoOp(NoOpCache::new());
    let layered_cache = Arc::new(LayeredCache::new(memory, secondary));
    let updates = gen_test_event_updates("$pageview", 100, None);
    // should decompose into 1 event def, 100 event props, 100 prop defs (of event type)
    assert_eq!(updates.len(), 201);

    process_batch_v2(&config, layered_cache, &db, updates).await;

    // fetch results and ensure they landed correctly
    let event_def_name: String = sqlx::query_scalar!(r#"SELECT name from posthog_eventdefinition"#)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(String::from("$pageview"), event_def_name);

    let prop_defs_count: Option<i64> =
        sqlx::query_scalar!(r#"SELECT count(*) from posthog_propertydefinition"#)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(Some(100), prop_defs_count);

    let event_props_count: Option<i64> =
        sqlx::query_scalar!(r#"SELECT count(*) from posthog_eventproperty"#)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(Some(100), event_props_count);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_group_batch_write(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();
    let memory = Arc::new(InMemoryCache::new(config.cache_capacity));
    let secondary = SecondaryCache::NoOp(NoOpCache::new());
    let layered_cache = Arc::new(LayeredCache::new(memory, secondary));
    let updates = gen_test_event_updates("$groupidentify", 100, Some(PropertyParentType::Group));
    // should decompose into 1 group event def, 100 prop defs (of group type), 100 event props
    assert_eq!(updates.len(), 201);

    process_batch_v2(&config, layered_cache, &db, updates).await;

    // fetch results and ensure they landed correctly
    let event_def_name: String = sqlx::query_scalar!(r#"SELECT name from posthog_eventdefinition"#)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(String::from("$groupidentify"), event_def_name);

    let prop_defs_count: Option<i64> =
        sqlx::query_scalar!(r#"SELECT count(*) from posthog_propertydefinition WHERE type = 3"#)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(Some(100), prop_defs_count);

    let event_props_count: Option<i64> =
        sqlx::query_scalar!(r#"SELECT count(*) from posthog_eventproperty"#)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(Some(100), event_props_count);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_person_batch_write(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();
    let memory = Arc::new(InMemoryCache::new(config.cache_capacity));
    let secondary = SecondaryCache::NoOp(NoOpCache::new());
    let layered_cache = Arc::new(LayeredCache::new(memory, secondary));
    let updates =
        gen_test_event_updates("event_with_person", 100, Some(PropertyParentType::Person));
    // should decompose into 1 event def, 100 event props, 100 prop defs (50 $set, 50 $set_once props)
    assert_eq!(updates.len(), 201);

    process_batch_v2(&config, layered_cache, &db, updates).await;

    // fetch results and ensure they landed correctly
    let event_def_name: String = sqlx::query_scalar!(r#"SELECT name from posthog_eventdefinition"#)
        .fetch_one(&db)
        .await
        .unwrap();
    assert_eq!(String::from("event_with_person"), event_def_name);

    let prop_defs_count: Option<i64> =
        sqlx::query_scalar!(r#"SELECT count(*) from posthog_propertydefinition WHERE type = 2"#)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(Some(100), prop_defs_count);

    let event_props_count: Option<i64> =
        sqlx::query_scalar!(r#"SELECT count(*) from posthog_eventproperty"#)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(Some(100), event_props_count);
}

fn gen_test_event_updates(
    event_name: &'static str,
    num_props: usize,
    prop_type: Option<PropertyParentType>,
) -> Vec<Update> {
    let prop_kvs = (0..num_props)
        .map(gen_test_prop_key_value)
        .collect::<Vec<(String, Value)>>();

    // let's be *just* realistic enough to exercise we're decomposing the Event properly in unit tests
    let mut properties = HashMap::<String, Value>::new();
    match prop_type {
        Some(PropertyParentType::Person) => {
            let mut set_props = HashMap::<String, Value>::new();
            let mut set_once_props = HashMap::<String, Value>::new();

            // split the total props between $set and $set_once buckets.
            // these will be flattened back into a single unique group of props
            // during parsing into Update records
            for kv in prop_kvs.iter().enumerate() {
                if kv.0 % 2 == 0 {
                    set_props.insert(kv.1 .0.clone(), kv.1 .1.clone());
                } else {
                    set_once_props.insert(kv.1 .0.clone(), kv.1 .1.clone());
                }
            }
            properties.insert(String::from("$set"), json!(set_props));
            properties.insert(String::from("$set_once"), json!(set_once_props));
        }
        Some(PropertyParentType::Group) => {
            let mut group_props = HashMap::<String, Value>::new();
            for kv in prop_kvs {
                group_props.insert(kv.0, kv.1);
            }
            properties.insert(
                String::from("$group_type"),
                Value::String(String::from("Organization")),
            );
            properties.insert(String::from("$group_set"), json!(group_props));
        }
        _ => {
            // generate flat list of "vanilla" event props
            for kv in prop_kvs {
                properties.insert(kv.0, kv.1);
            }
        }
    }

    let properties = json!(properties).to_string();

    let event = json!({
        "team_id": 111,
        "project_id": 111,
        "event": event_name,
        "properties": properties,
    });

    serde_json::from_value::<Event>(event)
        .unwrap()
        .into_updates(10000)
}

fn gen_test_prop_key_value(ndx: usize) -> (String, Value) {
    use rand::seq::SliceRandom;

    match [0, 1, 2, 3].choose(&mut rand::thread_rng()) {
        // String
        Some(&0) => (
            format!("str_prop_{}", ndx),
            Value::String(format!("value_{}", ndx)),
        ),

        // Boolean
        Some(&1) => (format!("bool_prop_{}", ndx), Value::Bool(true)),

        // Numeric
        Some(&2) => (
            format!("numeric_prop_{}", ndx),
            json!(rand::thread_rng().gen_range(0..1000)),
        ),

        // DateTime
        Some(&3) => (
            format!("datetime_prop_{}", ndx),
            Value::String(Utc::now().to_rfc3339()),
        ),

        // skipping Duration as it's unused for now
        _ => panic!("not reachable"),
    }
}

#[sqlx::test]
async fn test_process_batch_v2() -> sqlx::Result<()> {
    let pool = sqlx::postgres::PgPool::connect("postgres://localhost/test").await?;
    let config = Config::init_with_defaults().unwrap();
    let memory = Arc::new(InMemoryCache::new(1000));
    let secondary = SecondaryCache::NoOp(NoOpCache::new());
    let layered_cache = Arc::new(LayeredCache::new(memory, secondary));

    let updates = vec![
        Update::EventProperty(EventProperty {
            team_id: 1,
            project_id: 1,
            event: "test".to_string(),
            property: "prop_1".to_string(),
        }),
        Update::EventProperty(EventProperty {
            team_id: 1,
            project_id: 1,
            event: "test".to_string(),
            property: "prop_2".to_string(),
        }),
    ];

    process_batch_v2(&config, layered_cache, &pool, updates).await;

    Ok(())
}

#[sqlx::test]
async fn test_process_batch_v2_large() -> sqlx::Result<()> {
    let pool = sqlx::postgres::PgPool::connect("postgres://localhost/test").await?;
    let config = Config::init_with_defaults().unwrap();
    let memory = Arc::new(InMemoryCache::new(10000));
    let secondary = SecondaryCache::NoOp(NoOpCache::new());
    let layered_cache = Arc::new(LayeredCache::new(memory, secondary));

    let updates: Vec<Update> = (0..1000)
        .map(|i| Update::EventProperty(EventProperty {
            team_id: 1,
            project_id: 1,
            event: "test".to_string(),
            property: format!("prop_{}", i),
        }))
        .collect();

    process_batch_v2(&config, layered_cache, &pool, updates).await;

    Ok(())
}
