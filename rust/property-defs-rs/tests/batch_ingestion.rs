use std::collections::HashMap;
use std::sync::Arc;

use chrono::{DateTime, Utc};
use rand::Rng;
use serde_json::{json, Value};
use sqlx::PgPool;

use property_defs_rs::{
    batch_ingestion::process_batch,
    config::Config,
    types::{
        Event, EventDefinition, GroupType, PropertyDefinition, PropertyParentType,
        PropertyValueType, Update,
    },
    update_cache::Cache,
};

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_simple_batch_write(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();
    let cache: Arc<Cache> = Arc::new(Cache::new(
        config.eventdefs_cache_capacity,
        config.eventprops_cache_capacity,
        config.propdefs_cache_capacity,
    ));
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

    let enforcement_mode: String =
        sqlx::query_scalar!(r#"SELECT enforcement_mode from posthog_eventdefinition"#)
            .fetch_one(&db)
            .await
            .unwrap();
    assert_eq!(String::from("allow"), enforcement_mode);

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
    let cache: Arc<Cache> = Arc::new(Cache::new(
        config.eventdefs_cache_capacity,
        config.eventprops_cache_capacity,
        config.propdefs_cache_capacity,
    ));
    let mut updates =
        gen_test_event_updates("$groupidentify", 100, Some(PropertyParentType::Group));
    // should decompose into 1 group event def, 100 prop defs (of group type), 0 event props
    assert_eq!(updates.len(), 101);

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
    assert_eq!(Some(0), event_props_count);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_person_batch_write(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();
    let cache: Arc<Cache> = Arc::new(Cache::new(
        config.eventdefs_cache_capacity,
        config.eventprops_cache_capacity,
        config.propdefs_cache_capacity,
    ));
    let updates =
        gen_test_event_updates("event_with_person", 100, Some(PropertyParentType::Person));
    // should decompose into 1 event def, 0 event props, 100 prop defs (50 $set, 50 $set_once props)
    assert_eq!(updates.len(), 101);

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
    assert_eq!(Some(0), event_props_count);
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
            format!("str_prop_{ndx}"),
            Value::String(format!("value_{ndx}")),
        ),

        // Boolean
        Some(&1) => (format!("bool_prop_{ndx}"), Value::Bool(true)),

        // Numeric
        Some(&2) => (
            format!("numeric_prop_{ndx}"),
            json!(rand::thread_rng().gen_range(0..1000)),
        ),

        // DateTime
        Some(&3) => (
            format!("datetime_prop_{ndx}"),
            Value::String(Utc::now().to_rfc3339()),
        ),

        // skipping Duration as it's unused for now
        _ => panic!("not reachable"),
    }
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_property_definitions_conflict_update(db: PgPool) {
    let config = Config::init_with_defaults().unwrap();
    let cache: Arc<Cache> = Arc::new(Cache::new(
        config.eventdefs_cache_capacity,
        config.eventprops_cache_capacity,
        config.propdefs_cache_capacity,
    ));

    // First, insert a property definition with null type and is_numerical false
    let initial_prop = property_defs_rs::types::PropertyDefinition {
        team_id: 111,
        project_id: 111,
        name: "test_prop".to_string(),
        property_type: None,
        is_numerical: false,
        event_type: PropertyParentType::Event,
        group_type_index: None,
        property_type_format: None,
        volume_30_day: None,
        query_usage_30_day: None,
    };

    let initial_updates = vec![Update::Property(initial_prop)];
    process_batch(&config, cache.clone(), &db, initial_updates).await;

    // Verify initial state
    let initial_row = sqlx::query!(
        r#"SELECT property_type, is_numerical FROM posthog_propertydefinition WHERE name = 'test_prop'"#
    )
    .fetch_one(&db)
    .await
    .unwrap();

    assert_eq!(initial_row.property_type, None);
    assert!(!initial_row.is_numerical);

    // Now insert the same property with a numeric type and is_numerical true
    let updated_prop = property_defs_rs::types::PropertyDefinition {
        team_id: 111,
        project_id: 111,
        name: "test_prop".to_string(),
        property_type: Some(property_defs_rs::types::PropertyValueType::Numeric),
        is_numerical: true,
        event_type: PropertyParentType::Event,
        group_type_index: None,
        property_type_format: None,
        volume_30_day: None,
        query_usage_30_day: None,
    };

    let updated_updates = vec![Update::Property(updated_prop)];
    process_batch(&config, cache, &db, updated_updates).await;

    // Verify both fields were updated
    let updated_row = sqlx::query!(
        r#"SELECT property_type, is_numerical FROM posthog_propertydefinition WHERE name = 'test_prop'"#
    )
    .fetch_one(&db)
    .await
    .unwrap();

    assert_eq!(updated_row.property_type, Some("Numeric".to_string()));
    assert!(updated_row.is_numerical);

    // Verify only one row exists (no duplicate)
    let count: Option<i64> = sqlx::query_scalar!(
        r#"SELECT COUNT(*) FROM posthog_propertydefinition WHERE name = 'test_prop'"#
    )
    .fetch_one(&db)
    .await
    .unwrap();

    assert_eq!(count, Some(1));
}

fn setup_cache(config: &Config) -> Arc<Cache> {
    Arc::new(Cache::new(
        config.eventdefs_cache_capacity,
        config.eventprops_cache_capacity,
        config.propdefs_cache_capacity,
    ))
}

fn prop(
    name: &str,
    property_type: Option<PropertyValueType>,
    is_numerical: bool,
    event_type: PropertyParentType,
) -> Update {
    Update::Property(PropertyDefinition {
        team_id: 111,
        project_id: 111,
        name: name.to_string(),
        property_type,
        is_numerical,
        event_type,
        group_type_index: None,
        property_type_format: None,
        volume_30_day: None,
        query_usage_30_day: None,
    })
}

fn evt(name: &str, last_seen_at: DateTime<Utc>) -> Update {
    Update::Event(EventDefinition {
        name: name.to_string(),
        team_id: 111,
        project_id: 111,
        last_seen_at,
    })
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_property_definitions_dedupe_within_batch(db: PgPool) {
    // A property name repeated within one batch on differing mutable columns shares the ON CONFLICT
    // key. Before the SELECT DISTINCT ON dedup this raised SQLSTATE 21000 and rolled back the *whole*
    // batch - including the unrelated, genuinely-new "current_page" def. All three inputs collapse
    // to two rows and must persist.
    let config = Config::init_with_defaults().unwrap();
    let cache = setup_cache(&config);

    let batch = vec![
        prop("brand", None, false, PropertyParentType::Event),
        prop(
            "brand",
            Some(PropertyValueType::Numeric),
            true,
            PropertyParentType::Event,
        ),
        prop("current_page", None, false, PropertyParentType::Event),
    ];
    process_batch(&config, cache, &db, batch).await;

    let count: Option<i64> = sqlx::query_scalar!(
        r#"SELECT COUNT(*) FROM posthog_propertydefinition WHERE name IN ('brand', 'current_page')"#
    )
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(
        count,
        Some(2),
        "the deduped def and the unrelated new def must both persist"
    );

    // Typed row wins on the collapsed key, mirroring the DO UPDATE.
    let brand = sqlx::query!(
        r#"SELECT property_type, is_numerical FROM posthog_propertydefinition WHERE name = 'brand'"#
    )
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(brand.property_type, Some("Numeric".to_string()));
    assert!(brand.is_numerical);
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_property_definitions_typed_row_wins_regardless_of_order(db: PgPool) {
    // The DISTINCT ON survivor is chosen by ORDER BY, not arrival order: rev_a arrives typed-then-null,
    // rev_b arrives null-then-typed. Both must resolve to the typed row.
    let config = Config::init_with_defaults().unwrap();
    let cache = setup_cache(&config);

    let batch = vec![
        prop(
            "rev_a",
            Some(PropertyValueType::Numeric),
            true,
            PropertyParentType::Event,
        ),
        prop("rev_a", None, false, PropertyParentType::Event),
        prop("rev_b", None, false, PropertyParentType::Event),
        prop(
            "rev_b",
            Some(PropertyValueType::Numeric),
            true,
            PropertyParentType::Event,
        ),
    ];
    process_batch(&config, cache, &db, batch).await;

    for name in ["rev_a", "rev_b"] {
        let row = sqlx::query!(
            r#"SELECT property_type, is_numerical FROM posthog_propertydefinition WHERE name = $1"#,
            name
        )
        .fetch_one(&db)
        .await
        .unwrap();
        assert_eq!(
            row.property_type,
            Some("Numeric".to_string()),
            "{name} should keep the typed row"
        );
        assert!(row.is_numerical, "{name} should keep is_numerical=true");
    }

    let count: Option<i64> = sqlx::query_scalar!(
        r#"SELECT COUNT(*) FROM posthog_propertydefinition WHERE name IN ('rev_a', 'rev_b')"#
    )
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(count, Some(2));
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_property_definitions_keeps_rows_that_differ_on_conflict_key(db: PgPool) {
    // Same name, different parent type => different ON CONFLICT key; dedup must NOT collapse them.
    let config = Config::init_with_defaults().unwrap();
    let cache = setup_cache(&config);

    let batch = vec![
        prop("shared", None, false, PropertyParentType::Event),
        prop("shared", None, false, PropertyParentType::Person),
    ];
    process_batch(&config, cache, &db, batch).await;

    let count: Option<i64> = sqlx::query_scalar!(
        r#"SELECT COUNT(*) FROM posthog_propertydefinition WHERE name = 'shared'"#
    )
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(count, Some(2));
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn test_event_definitions_dedupe_within_batch(db: PgPool) {
    // An event name repeated within one batch shares the ON CONFLICT key; before the dedup this raised
    // SQLSTATE 21000 and rolled back the whole batch, dropping the unrelated "$autocapture" def too.
    let config = Config::init_with_defaults().unwrap();
    let cache = setup_cache(&config);

    // last_seen_at is regenerated server-side to one per-attempt timestamp for every row, so the
    // value passed here doesn't affect which key-duplicate survives; this asserts the dedup itself
    // (no SQLSTATE 21000) and that the unrelated new def survives.
    let now = Utc::now();
    let batch = vec![
        evt("$pageview", now),
        evt("$pageview", now),
        evt("$autocapture", now),
    ];
    process_batch(&config, cache, &db, batch).await;

    let count: Option<i64> = sqlx::query_scalar!(
        r#"SELECT COUNT(*) FROM posthog_eventdefinition WHERE name IN ('$pageview', '$autocapture')"#
    )
    .fetch_one(&db)
    .await
    .unwrap();
    assert_eq!(
        count,
        Some(2),
        "the deduped event def and the unrelated new one must both persist"
    );
}
