use std::sync::{Arc, OnceLock};

use chrono::Utc;
use metrics_util::debugging::{DebugValue, DebuggingRecorder, Snapshotter};
use property_defs_rs::{
    batch_ingestion::PropertyDefinitionsBatch,
    metrics_consts::{CACHE_EVICTIONS, CACHE_HITS, CACHE_MISSES},
    types::{
        EventDefinition, EventProperty, GroupType, PropertyDefinition, PropertyParentType,
        PropertyValueType, Update,
    },
    update_cache::Cache,
};
use rstest::rstest;

// One global recorder per test process. Multiple #[test]s run in parallel, share
// the same recorder, and read counters via labeled lookups against the snapshot.
fn snapshotter() -> &'static Snapshotter {
    static SNAPSHOTTER: OnceLock<Snapshotter> = OnceLock::new();
    SNAPSHOTTER.get_or_init(|| {
        let recorder = DebuggingRecorder::new();
        let s = recorder.snapshotter();
        // ignore install errors: a recorder may already be globally set if
        // multiple test binaries share state in the future
        drop(recorder.install());
        s
    })
}

fn counter_value(metric: &'static str, cache_label: &'static str) -> u64 {
    snapshotter()
        .snapshot()
        .into_vec()
        .into_iter()
        .find(|(key, _, _, _)| {
            key.key().name() == metric
                && key
                    .key()
                    .labels()
                    .any(|l| l.key() == "cache" && l.value() == cache_label)
        })
        .and_then(|(_, _, _, value)| match value {
            DebugValue::Counter(v) => Some(v),
            _ => None,
        })
        .unwrap_or(0)
}

fn make_event_def(name: &str) -> Update {
    Update::Event(EventDefinition {
        name: name.into(),
        team_id: 1,
        project_id: 1,
        last_seen_at: Utc::now(),
    })
}

fn make_event_prop(event: &str, property: &str) -> Update {
    Update::EventProperty(EventProperty {
        event: event.into(),
        property: property.into(),
        team_id: 1,
        project_id: 1,
    })
}

fn make_prop_def(name: &str) -> Update {
    Update::Property(PropertyDefinition {
        team_id: 1,
        project_id: 1,
        name: name.into(),
        is_numerical: true,
        property_type: Some(PropertyValueType::Numeric),
        event_type: PropertyParentType::Event,
        group_type_index: None,
        property_type_format: None,
        query_usage_30_day: None,
        volume_30_day: None,
    })
}

#[test]
fn test_cache_insertions() {
    let cache = Cache::new(10, 10, 10);

    let evt_def = make_event_def("foobar");
    cache.insert(evt_def.clone());

    let evt_prop = make_event_prop("foo", "bar");
    cache.insert(evt_prop.clone());

    let prop_def = make_prop_def("baz_count");
    cache.insert(prop_def.clone());

    assert!(cache.contains_key(&evt_def));
    assert!(cache.contains_key(&evt_prop));
    assert!(cache.contains_key(&prop_def));
}

#[test]
fn test_cache_removals() {
    let cache = Cache::new(10, 10, 10);

    let evt_def = make_event_def("foobar");
    cache.insert(evt_def.clone());

    let evt_prop = make_event_prop("foo", "bar");
    cache.insert(evt_prop.clone());

    let prop_def = make_prop_def("baz_count");
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

// Drives one miss-then-hit through `Cache::contains_key` for a given subcache,
// asserting that the corresponding `prop_defs_cache_misses{cache=label}` and
// `prop_defs_cache_hits{cache=label}` counters advance. We compare deltas
// (post - pre) instead of absolute values because the recorder is shared
// across all tests in the binary and parallel tests touch the same labels.
fn assert_miss_then_hit(label: &'static str, update: Update) {
    let cache = Cache::new(64, 64, 64);

    let pre_miss = counter_value(CACHE_MISSES, label);
    let pre_hit = counter_value(CACHE_HITS, label);

    assert!(!cache.contains_key(&update), "fresh cache should miss");
    cache.insert(update.clone());
    assert!(cache.contains_key(&update), "cached entry should hit");

    let post_miss = counter_value(CACHE_MISSES, label);
    let post_hit = counter_value(CACHE_HITS, label);

    assert!(
        post_miss > pre_miss,
        "{label}: misses did not advance ({pre_miss} -> {post_miss})",
    );
    assert!(
        post_hit > pre_hit,
        "{label}: hits did not advance ({pre_hit} -> {post_hit})",
    );
}

#[rstest]
#[case::eventdefs("eventdefs", make_event_def("hit_miss_eventdefs"))]
#[case::eventprops(
    "eventprops",
    make_event_prop("hit_miss_eventprops_evt", "hit_miss_eventprops_prop")
)]
#[case::propdefs("propdefs", make_prop_def("hit_miss_propdefs"))]
fn test_contains_key_emits_hit_miss_metrics(#[case] label: &'static str, #[case] update: Update) {
    assert_miss_then_hit(label, update);
}

// quick_cache enforces a minimum of 32 items per shard (`sync.rs` ~134:
// `while shard_items_cap < 32 && num_shards > 1 { num_shards /= 2; ... }`),
// so even with `Cache::new(2, 2, 2)` we get a single 32-slot shard per
// subcache. We need >32 distinct inserts to provoke at least one eviction.
#[test]
fn test_overflowing_subcache_emits_eviction_metric() {
    let cache = Cache::new(2, 2, 2);

    let pre = counter_value(CACHE_EVICTIONS, "eventdefs");
    for i in 0..200 {
        cache.insert(make_event_def(&format!("evict_test_evt_{i}")));
    }
    let post = counter_value(CACHE_EVICTIONS, "eventdefs");

    assert!(
        post > pre,
        "eventdefs evictions did not advance ({pre} -> {post}) after overflow",
    );
}
