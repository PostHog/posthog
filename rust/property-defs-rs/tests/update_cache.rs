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
    let cache = Cache::new(10, 10);

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
    let cache = Cache::new(10, 10);

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

#[test]
fn test_batch_cache_insertions() {
    let cache = Cache::new(300, 10);

    let mut evt_defs = vec![];
    let mut evt_props = vec![];
    let mut prop_defs = vec![];

    for counter in 1..=100 {
        evt_defs.push(Update::Event(EventDefinition {
            name: format!("event def {}", counter),
            team_id: 1,
            project_id: 1,
            last_seen_at: Utc::now(),
        }));

        evt_props.push(Update::EventProperty(EventProperty {
            event: format!("event def {}", counter),
            property: format!("prop def {}", counter),
            team_id: 1,
            project_id: 1,
        }));

        prop_defs.push(Update::Property(PropertyDefinition {
            team_id: 1,
            project_id: 1,
            name: format!("prop def {}", counter),
            is_numerical: true,
            property_type: Some(PropertyValueType::Numeric),
            event_type: PropertyParentType::Event,
            group_type_index: None,
            property_type_format: None,
            query_usage_30_day: None,
            volume_30_day: None,
        }));
    }

    assert!(cache.is_empty());
    cache.insert_batch(&evt_defs);
    assert!(!cache.is_empty());
    assert!(cache.len() == 100);

    cache.insert_batch(&evt_props);
    assert!(cache.len() == 200);

    cache.insert_batch(&prop_defs);
    assert!(cache.len() == 300);
}

#[test]
fn test_batch_cache_removals() {
    let cache = Cache::new(300, 10);

    let mut evt_defs = vec![];
    let mut evt_props = vec![];
    let mut prop_defs = vec![];

    for counter in 1..=100 {
        evt_defs.push(Update::Event(EventDefinition {
            name: format!("event def {}", counter),
            team_id: 1,
            project_id: 1,
            last_seen_at: Utc::now(),
        }));

        evt_props.push(Update::EventProperty(EventProperty {
            event: format!("event def {}", counter),
            property: format!("event prop {}", counter),
            team_id: 1,
            project_id: 1,
        }));

        prop_defs.push(Update::Property(PropertyDefinition {
            team_id: 1,
            project_id: 1,
            name: format!("prop def {}", counter),
            is_numerical: true,
            property_type: Some(PropertyValueType::Numeric),
            event_type: PropertyParentType::Event,
            group_type_index: None,
            property_type_format: None,
            query_usage_30_day: None,
            volume_30_day: None,
        }));
    }

    cache.insert_batch(&evt_defs);
    cache.insert_batch(&evt_props);
    cache.insert_batch(&prop_defs);

    assert!(cache.len() == 300);

    cache.remove_batch(&evt_defs);
    assert!(cache.len() == 200);

    cache.remove_batch(&evt_props);
    assert!(cache.len() == 100);

    cache.remove_batch(&prop_defs);
    assert!(cache.is_empty());
}
