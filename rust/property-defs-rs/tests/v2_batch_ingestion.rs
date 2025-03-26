use std::collections::HashMap;
use std::sync::Arc;

use chrono::Utc;
use quick_cache::sync::Cache;
use rand::Rng;
use serde_json::{json, Value};
use sqlx::PgPool;

use property_defs_rs::{
    config::Config,
    process_batch_v2,
    types::{Event, Update},
};
#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_simple_batch_write(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();
    let cache: Arc<Cache<Update, ()>> = Arc::new(Cache::new(config.cache_capacity));
    let updates = gen_test_event_updates("$pageview", 100);
    assert_eq!(updates.len(), 201);

    process_batch_v2(&config, cache, &db, updates).await;

    // fetch results and ensure they landed correctly
    let event_defs_count: u64 =
        sqlx::query_scalar!(r#"SELECT count(*) from posthog_eventdefinition"#);
    assert_eq!(1, event_defs_count);

    let prop_defs_count: u64 =
        sqlx::query_scalar!(r#"SELECT count(*) from posthog_propertydefinition"#);
    assert_eq!(100, prop_defs_count);

    let event_props_count: u64 =
        sqlx::query_scalar!(r#"SELECT count(*) from posthog_eventproperty"#);
    assert_eq!(100, event_props_count);
}

fn gen_test_event_updates(event_name: &'static str, num_props: usize) -> Vec<Update> {
    let prop_kvs = (0..num_props)
        .map(|ndx| gen_test_prop_key_value(ndx))
        .collect::<Vec<(String, Value)>>();

    let mut properties = HashMap::<String, Value>::new();
    for kv in prop_kvs {
        properties.insert(kv.0, kv.1);
    }

    let event = json!({
        "team_id": 111,
        "project_id": 111,
        "event": event_name,
        "properties": properties,
    });

    // each non-person property will generate 1 event_property and 1 property_definition
    // Update, and we add one more for the event_definition Update from the parent
    let limit = (2 * num_props) + 1;

    serde_json::from_value::<Event>(event)
        .unwrap()
        .into_updates(limit)
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
