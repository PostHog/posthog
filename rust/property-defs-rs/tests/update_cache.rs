use std::sync::Arc;

use chrono::Utc;
use property_defs_rs::{
    batch_ingestion::PropertyDefinitionsBatch,
    types::{
        EventDefinition, EventProperty, GroupType, PropertyDefinition, PropertyParentType,
        PropertyValueType, Update,
    },
    update_cache::Cache,
};

#[test]
fn test_cache_insertions() {
    let cache = Cache::new(10, 10, 10);

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
    let cache = Cache::new(10, 10, 10);

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

fn make_group_prop_def(group_type_index: Option<GroupType>) -> Update {
    Update::Property(PropertyDefinition {
        team_id: 1,
        project_id: 1,
        name: String::from("company_name"),
        is_numerical: false,
        property_type: Some(PropertyValueType::String),
        event_type: PropertyParentType::Group,
        group_type_index,
        property_type_format: None,
        query_usage_30_day: None,
        volume_30_day: None,
    })
}

#[test]
fn test_resolved_group_prop_cannot_remove_unresolved_cache_entry() {
    let cache = Cache::new(10, 10, 10);

    let unresolved = make_group_prop_def(Some(GroupType::Unresolved("company".into())));
    cache.insert(unresolved.clone());
    assert!(cache.contains_key(&unresolved));

    // Simulates what uncache_batch used to do: try to remove the resolved
    // form. This fails because derived Eq distinguishes the variants.
    let resolved = make_group_prop_def(Some(GroupType::Resolved("company".into(), 2)));
    cache.remove(&resolved);
    assert!(
        cache.contains_key(&unresolved),
        "stale entry should still be cached"
    );
}

#[test]
fn test_uncache_batch_evicts_unresolved_entry_for_group_prop() {
    let cache = Arc::new(Cache::new(10, 10, 10));

    // Producer inserts the unresolved form (before resolution happens)
    let unresolved = make_group_prop_def(Some(GroupType::Unresolved("company".into())));
    cache.insert(unresolved.clone());
    assert!(cache.contains_key(&unresolved));

    // Consumer resolves the group type, then append adds it to the batch
    let resolved_pd = PropertyDefinition {
        team_id: 1,
        project_id: 1,
        name: "company_name".into(),
        is_numerical: false,
        property_type: Some(PropertyValueType::String),
        event_type: PropertyParentType::Group,
        group_type_index: Some(GroupType::Resolved("company".into(), 2)),
        property_type_format: None,
        query_usage_30_day: None,
        volume_30_day: None,
    };
    let mut batch = PropertyDefinitionsBatch::new(10);
    batch.append(resolved_pd);

    // Simulate batch write failure: uncache_batch should evict the
    // original unresolved entry so the update can be retried
    batch.uncache_batch(&cache);
    assert!(
        !cache.contains_key(&unresolved),
        "entry should be uncached after batch failure"
    );
}
