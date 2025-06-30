use std::collections::HashMap;
use std::sync::Arc;

use chrono::Utc;
use rand::Rng;
use serde_json::{json, Value};
use sqlx::PgPool;

use property_defs_rs::{
    config::Config,
    types::{Event, GroupType, PropertyParentType, Update},
    update_cache::Cache,
    v2_batch_ingestion::process_batch,
};

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_simple_batch_write(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();
    let cache: Arc<Cache> = Arc::new(Cache::new(config.cache_capacity));
    let updates = gen_test_event_updates("$pageview", 100, None);
    // should decompose into 1 event def, 100 event props, 100 prop defs (of event type)
    assert_eq!(updates.len(), 201);

    process_batch(&config, cache, &db, updates).await;

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
    let _unused = sqlx::query!(
        r#"
        INSERT INTO posthog_grouptypemapping (id, group_type, group_type_index, team_id, project_id)
            VALUES(1, 'Organization', 1, 111, 111)
    "#
    )
    .execute(&db)
    .await;

    let config = Config::init_with_defaults().unwrap();
    let cache: Arc<Cache> = Arc::new(Cache::new(config.cache_capacity));
    let mut updates =
        gen_test_event_updates("$groupidentify", 100, Some(PropertyParentType::Group));
    // should decompose into 1 group event def, 100 prop defs (of group type), 100 event props
    assert_eq!(updates.len(), 201);

    // TODO(eli): quick hack - until we refacor the group type hydration on AppContext,
    // we need to manually do this prior to passing to process_batch for the test
    // to be realistic to prod behavior.
    updates.iter_mut().for_each({
        |u: &mut Update| {
            if let Update::Property(group_prop) = u {
                if group_prop.event_type == PropertyParentType::Group {
                    if let Some(GroupType::Unresolved(group_name)) = &group_prop.group_type_index {
                        group_prop.group_type_index =
                            Some(GroupType::Resolved(group_name.clone(), 1))
                    }
                }
            }
        }
    });
    process_batch(&config, cache, &db, updates).await;

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
    let cache: Arc<Cache> = Arc::new(Cache::new(config.cache_capacity));
    let updates =
        gen_test_event_updates("event_with_person", 100, Some(PropertyParentType::Person));
    // should decompose into 1 event def, 100 event props, 100 prop defs (50 $set, 50 $set_once props)
    assert_eq!(updates.len(), 201);

    process_batch(&config, cache, &db, updates).await;

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
