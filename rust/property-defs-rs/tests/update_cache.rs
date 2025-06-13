use chrono::Utc;
use property_defs_rs::{
    types::{
        EventDefinition, EventProperty, PropertyDefinition, PropertyParentType, PropertyValueType,
        Update,
    },
    update_cache::Cache,
};

#[test]
fn test_cache_insertions() {
    let cache = Cache::new(10);

    let evt_def = Update::Event(EventDefinition {
        name: String::from("foobar"),
        team_id: 1,
        project_id: 1,
        last_seen_at: Utc::now(),
    });
    cache.insert(evt_def.clone());

    let evt_prop = Update::EventProperty(EventProperty {
        event: String::from("foo"),
        property: String::from("bar"),
        team_id: 1,
        project_id: 1,
    });
    cache.insert(evt_prop.clone());

    let prop_def = Update::Property(PropertyDefinition {
        team_id: 1,
        project_id: 1,
        name: String::from("baz_count"),
        is_numerical: true,
        property_type: Some(PropertyValueType::Numeric),
        event_type: PropertyParentType::Event,
        group_type_index: None,
        property_type_format: None,
        query_usage_30_day: None,
        volume_30_day: None,
    });
    cache.insert(prop_def.clone());

    assert!(cache.contains_key(&evt_def));
    assert!(cache.contains_key(&evt_prop));
    assert!(cache.contains_key(&prop_def));
}

#[test]
fn test_cache_removals() {
    let cache = Cache::new(10);

    let evt_def = Update::Event(EventDefinition {
        name: String::from("foobar"),
        team_id: 1,
        project_id: 1,
        last_seen_at: Utc::now(),
    });
    cache.insert(evt_def.clone());

    let evt_prop = Update::EventProperty(EventProperty {
        event: String::from("foo"),
        property: String::from("bar"),
        team_id: 1,
        project_id: 1,
    });
    cache.insert(evt_prop.clone());

    let prop_def = Update::Property(PropertyDefinition {
        team_id: 1,
        project_id: 1,
        name: String::from("baz_count"),
        is_numerical: true,
        property_type: Some(PropertyValueType::Numeric),
        event_type: PropertyParentType::Event,
        group_type_index: None,
        property_type_format: None,
        query_usage_30_day: None,
        volume_30_day: None,
    });
    cache.insert(prop_def.clone());

    // remove the entries and check
    cache.remove(&evt_def);
    cache.remove(&evt_prop);
    cache.remove(&prop_def);

    assert!(!cache.contains_key(&evt_def));
    assert!(!cache.contains_key(&evt_prop));
    assert!(!cache.contains_key(&prop_def));
}
