use chrono::Utc;
use property_defs_rs::types::{
    detect_property_type, floor_last_seen, last_seen_jitter_seed, Event, PropertyValueType, Update,
    DEFAULT_EVENTDEF_LAST_SEEN_FLOOR_SECS, MAX_EVENTDEF_LAST_SEEN_FLOOR_SECS,
};
use rstest::rstest;
use serde_json::{json, Map, Number, Value};

// The floored value is a dedup key, so what matters is which window it identifies, not that it
// lands on a round clock boundary (per-identity jitter means it usually won't). It must stay in
// (now - period, now]: a future value would defeat the write path's
// `last_seen_at < EXCLUDED.last_seen_at` guard, and one a full period old would re-issue the
// definition's write early.
#[rstest]
#[case(3600)]
#[case(86400)]
fn test_floor_last_seen_lands_in_the_current_window(#[case] period_secs: i64) {
    let now = Utc::now();

    for seed in [0, 1, 12345, u64::MAX] {
        let floored = floor_last_seen(now, period_secs, seed);
        assert!(floored <= now, "seed {seed} produced a future timestamp");
        assert!(
            now - floored < chrono::Duration::seconds(period_secs),
            "seed {seed} produced a timestamp a full period old"
        );
        assert_eq!(floored.timestamp_subsec_nanos(), 0);
    }
}

// The whole point of the period is that it reaches the dedup key: EventDefinition's Hash and Eq
// both cover last_seen_at. Asserting hourly != daily keys here would be wrong, because the daily
// window start is always also an hourly window start (3600 divides 86400 and both offsets are the
// seed mod 3600), so the two keys legitimately coincide for one hour of every day. Instead,
// compute the expected window independently and bracket Utc::now(): this can never false-fail,
// and if the period stops reaching floor_last_seen it fails whenever the default and requested
// windows differ, which is 23 of every 24 hours.
#[test]
fn test_flooring_period_reaches_the_event_definition_dedup_key() {
    const DAILY: i64 = 86400;

    let event = || Event {
        team_id: 111,
        project_id: 111,
        event: "$pageview".to_string(),
        properties: None,
    };

    let def_of = |updates: Vec<Update>| match updates.into_iter().next().unwrap() {
        Update::Event(ed) => ed,
        other => panic!("expected an event definition first, got {other:?}"),
    };

    let before = Utc::now();
    let daily = def_of(event().into_updates_with(10_000, DAILY));
    let defaulted = def_of(event().into_updates(10_000));
    let after = Utc::now();

    let seed = last_seen_jitter_seed(111, "$pageview");
    assert!(
        daily.last_seen_at == floor_last_seen(before, DAILY, seed)
            || daily.last_seen_at == floor_last_seen(after, DAILY, seed),
        "the explicit period must reach floor_last_seen, got {}",
        daily.last_seen_at
    );
    assert!(
        defaulted.last_seen_at
            == floor_last_seen(before, DEFAULT_EVENTDEF_LAST_SEEN_FLOOR_SECS, seed)
            || defaulted.last_seen_at
                == floor_last_seen(after, DEFAULT_EVENTDEF_LAST_SEEN_FLOOR_SECS, seed),
        "into_updates must floor at the documented default period, got {}",
        defaulted.last_seen_at
    );
}

// Jitter has to be a pure function of the identity: every pod computes it independently, and if
// they disagree the same definition gets written once per pod per period instead of once.
#[test]
fn test_jitter_seed_is_stable_and_identity_scoped() {
    assert_eq!(
        last_seen_jitter_seed(111, "$pageview"),
        last_seen_jitter_seed(111, "$pageview")
    );
    assert_ne!(
        last_seen_jitter_seed(111, "$pageview"),
        last_seen_jitter_seed(112, "$pageview")
    );
    assert_ne!(
        last_seen_jitter_seed(111, "$pageview"),
        last_seen_jitter_seed(111, "$identify")
    );
}

// This is the test that guards the reason jitter exists. Un-jittered, every key in the fleet rolls
// over at the same instant, so a coarse period dumps a period's worth of definition writes into
// the moments after the boundary. Spreading window starts across the period turns that burst into
// a steady trickle.
#[test]
fn test_jitter_spreads_window_starts_across_the_period() {
    const PERIOD: i64 = 86400;
    const BUCKETS: i64 = 24;

    let now = Utc::now();
    let mut occupied = std::collections::HashSet::new();
    for team_id in 0..2000 {
        let seed = last_seen_jitter_seed(team_id, "$pageview");
        let age = now.timestamp() - floor_last_seen(now, PERIOD, seed).timestamp();
        occupied.insert(age / (PERIOD / BUCKETS));
    }

    assert_eq!(
        occupied.len() as i64,
        BUCKETS,
        "expected window starts in all {BUCKETS} sub-ranges of the period, got {occupied:?}"
    );
}

// Advancing by exactly one period must advance the window by exactly one period, for every
// identity. An off-by-one here re-issues writes twice per period, or skips one entirely.
#[test]
fn test_window_advances_by_exactly_one_period() {
    const PERIOD: i64 = 86400;
    let now = Utc::now();

    for team_id in 0..50 {
        let seed = last_seen_jitter_seed(team_id, "$pageview");
        let first = floor_last_seen(now, PERIOD, seed);
        let next = floor_last_seen(now + chrono::Duration::seconds(PERIOD), PERIOD, seed);
        assert_eq!(
            (next - first).num_seconds(),
            PERIOD,
            "team {team_id} did not advance by exactly one period"
        );
    }
}

// "No flooring" must not be expressible: an unfloored last_seen_at makes every event a unique
// dedup key, so the cache filters nothing and the full event stream reaches
// posthog_eventdefinition as row updates. Startup validation rejects a non-positive config
// value loudly; this pins the function-level backstop that clamps to the default instead of
// dividing by zero or passing the value through.
#[rstest]
#[case(0)]
#[case(-1)]
fn test_non_positive_period_floors_at_the_default(#[case] period_secs: i64) {
    let now = Utc::now();
    assert_eq!(
        floor_last_seen(now, period_secs, 12345),
        floor_last_seen(now, DEFAULT_EVENTDEF_LAST_SEEN_FLOOR_SECS, 12345)
    );
}

// The same hazard from the other end. An uncapped period lets the jitter offset push bucket_start
// outside chrono's representable range, and the resulting fallback hands back an unfloored `now` —
// a unique dedup key per event, which is exactly the write amplification flooring exists to stop.
#[rstest]
#[case(MAX_EVENTDEF_LAST_SEEN_FLOOR_SECS + 1)]
#[case(i64::MAX)]
fn test_oversized_period_floors_at_the_maximum(#[case] period_secs: i64) {
    let now = Utc::now();

    for seed in [0, 12345, u64::MAX] {
        let floored = floor_last_seen(now, period_secs, seed);
        assert_eq!(
            floored,
            floor_last_seen(now, MAX_EVENTDEF_LAST_SEEN_FLOOR_SECS, seed),
            "seed {seed} did not clamp to the maximum period"
        );
        assert!(
            floored <= now && (now - floored).num_seconds() < MAX_EVENTDEF_LAST_SEEN_FLOOR_SECS,
            "seed {seed} floored outside the current window"
        );
    }
}

#[test]
fn test_property_timestamp_detection() {
    // regardless of keys containing timestamp tokens or not, string values
    // with an obvious attempt at a timestamp will be classified DateTimes
    assert_eq!(
        detect_property_type(
            "random_property",
            &Value::from("2025-03-11T09:48:12.863948+00:00")
        ),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("2023-12-13T15:45:30Z")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("2023-12-13T15:45:30.123Z")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("2023-12-13T15:45:30+00:00")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("2023-12-13T15:45:30-07:00")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("2023/12/13 15:45:30Z")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("2023/12/13 15:45:30")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("12-13-2023 15:45:30-07:00")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("12/13/2023 15:45:30-07")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("2023/12/13 15:45:30")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("2023-12-13 15:45:30")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("12/13/2023T15:45:30")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("2023-13-12T15:45:30")),
        Some(PropertyValueType::DateTime)
    );

    // date fragments that show user intent this is a DateTime are accepted
    assert_eq!(
        detect_property_type("random_property", &Value::from("2023-12-13")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("2023/12/13")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("12-13-2023")),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type("random_property", &Value::from("12/13/2023")),
        Some(PropertyValueType::DateTime)
    );

    // Test property name-based detection for numeric values (should be DateTime)
    assert_eq!(
        detect_property_type(
            "time",
            &Value::Number(Number::from(Utc::now().timestamp_millis() as u64 / 1000u64))
        ),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type(
            "timestamp",
            &Value::Number(Number::from(Utc::now().timestamp_millis() as u64 / 1000u64))
        ),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type(
            "TIMESTAMP",
            &Value::Number(Number::from(Utc::now().timestamp_millis() as u64 / 1000u64))
        ),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type(
            "created_time",
            &Value::Number(Number::from(Utc::now().timestamp_millis() as u64 / 1000u64))
        ),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type(
            "sent_at",
            &Value::Number(Number::from(Utc::now().timestamp_millis() as u64 / 1000u64))
        ),
        Some(PropertyValueType::DateTime)
    );

    // timestamp values with no obvious time token in key will be classified as DateTime
    assert_eq!(
        detect_property_type(
            "random_property_has_datetime_value",
            &Value::Number(Number::from(Utc::now().timestamp_millis() as u64 / 1000u64))
        ),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type(
            "updatedAt",
            &Value::Number(Number::from(Utc::now().timestamp_millis() as u64 / 1000u64))
        ),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type(
            "last-seen-at",
            &Value::Number(Number::from(Utc::now().timestamp_millis() as u64 / 1000u64))
        ),
        Some(PropertyValueType::DateTime)
    );

    assert_eq!(
        detect_property_type(
            "sent_date",
            &Value::Number(Number::from(Utc::now().timestamp_millis() as u64 / 1000u64))
        ),
        Some(PropertyValueType::DateTime)
    );
}

#[test]
fn test_property_timestamp_rejections() {
    // non *date* time string values will be rejected even with timestamp tokens in keys
    assert_eq!(
        detect_property_type("timestamp", &Value::from("15:45:30")),
        Some(PropertyValueType::String)
    );

    assert_eq!(
        detect_property_type("signup_date", &Value::from("not a date")),
        Some(PropertyValueType::String)
    );

    assert_eq!(
        detect_property_type("created_at", &Value::from("not a date")),
        Some(PropertyValueType::String)
    );

    // obviously non-timestamp values will not be classified DateTime on key tokens alone
    assert_eq!(
        detect_property_type("timestamp", &Value::from("any value")),
        Some(PropertyValueType::String)
    );

    assert_eq!(
        detect_property_type("created_time", &Value::from("any value")),
        Some(PropertyValueType::String)
    );

    assert_eq!(
        detect_property_type("sent_at", &Value::from("any value")),
        Some(PropertyValueType::String)
    );

    assert_eq!(
        detect_property_type("date_of_purchase", &Value::from("any value")),
        Some(PropertyValueType::String)
    );

    assert_eq!(
        detect_property_type(
            "signup_date",
            &Value::from("not a date but classified due to trigger tokens in key")
        ),
        Some(PropertyValueType::String)
    );

    // boolean values will be classified property even with timestamp tokens in key
    assert_eq!(
        detect_property_type("signup_date", &Value::from("true")),
        Some(PropertyValueType::Boolean)
    );

    assert_eq!(
        detect_property_type("timestamp", &Value::from("false")),
        Some(PropertyValueType::Boolean)
    );

    assert_eq!(
        detect_property_type("updatedAt", &Value::from("true")),
        Some(PropertyValueType::Boolean)
    );

    assert_eq!(
        detect_property_type("posthog_is_awesome", &Value::from("FALSE")),
        Some(PropertyValueType::Boolean)
    );

    // even with timestamp tokens in the key, a UNIX stamp older than
    // (now - 6 months) will not classify as DateTime
    assert_eq!(
        detect_property_type("timestamp", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("TIMESTAMP", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("user_timestamp", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("user_TIMESTAMP", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("timestampValue", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("time", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("TIME", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("created_time", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("created_at", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("createdAt", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("updated_at", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("created_TIME", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("timeValue", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("sent-at", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("updated-at", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    assert_eq!(
        detect_property_type("was_detected_at", &Value::Number(Number::from(1639400730))),
        Some(PropertyValueType::Numeric)
    );

    // without a keyword in the property key, even recent, valid
    // UNIX timestamp values will be classified as Numeric
    assert_eq!(
        detect_property_type(
            "hedgehogs_enumerated",
            &Value::Number(Number::from(Utc::now().timestamp_millis() as u64 / 1000u64))
        ),
        Some(PropertyValueType::Numeric)
    );
    assert_eq!(
        detect_property_type(
            "thyme_stamp",
            &Value::Number(Number::from(Utc::now().timestamp_millis() as u64 / 1000u64))
        ),
        Some(PropertyValueType::Numeric)
    );

    // obvious cases on Numerics will also classify properly
    assert_eq!(
        detect_property_type("count", &Value::Number(Number::from(42))),
        Some(PropertyValueType::Numeric)
    );
    assert_eq!(
        detect_property_type("amount", &Value::Number(Number::from(100))),
        Some(PropertyValueType::Numeric)
    );
}

#[test]
fn test_initial_utm_properties_always_string() {
    // $initial_utm_* properties are the SDK's "initial" variants of utm_*
    // and must always be classified as String, regardless of value.
    // See https://github.com/PostHog/posthog/issues/12529
    let cases: Vec<(&str, Value)> = vec![
        // datetime-looking values that would otherwise be classified as DateTime
        (
            "$initial_utm_campaign",
            Value::from("2025-03-11T09:48:12.863948+00:00"),
        ),
        ("$initial_utm_source", Value::from("2023-12-13")),
        ("$initial_utm_medium", Value::from("2023-12-13T15:45:30Z")),
        // numeric values
        ("$initial_utm_content", Value::Number(Number::from(12345))),
        ("$initial_utm_term", Value::Number(Number::from(42))),
        // boolean-like string values
        ("$initial_utm_campaign", Value::from("true")),
        // actual boolean values
        ("$initial_utm_source", Value::Bool(true)),
        // normal string values
        ("$initial_utm_campaign", Value::from("summer_sale")),
        ("$initial_utm_source", Value::from("google")),
        ("$initial_utm_medium", Value::from("cpc")),
        ("$initial_utm_content", Value::from("banner_ad")),
        ("$initial_utm_term", Value::from("running+shoes")),
    ];

    for (key, value) in cases {
        assert_eq!(
            detect_property_type(key, &value),
            Some(PropertyValueType::String),
            "expected String for key={key}, value={value}"
        );
    }
}

#[test]
fn test_bare_utm_properties_still_string() {
    // bare utm_* properties must still be classified as String
    let cases: Vec<(&str, Value)> = vec![
        (
            "utm_source",
            Value::from("2025-03-11T09:48:12.863948+00:00"),
        ),
        ("utm_campaign", Value::Number(Number::from(12345))),
        ("utm_medium", Value::from("true")),
        ("utm_content", Value::from("google")),
    ];

    for (key, value) in cases {
        assert_eq!(
            detect_property_type(key, &value),
            Some(PropertyValueType::String),
            "expected String for key={key}, value={value}"
        );
    }
}

// Case normalization is what makes each special-case branch in detect_property_type match. Only
// the DATETIME-keyword branch had mixed-case coverage before (the "TIMESTAMP" assertion in
// test_property_timestamp_detection); the utm, feature-flag and survey cases are all spelled
// lowercase everywhere else. Each case here pairs a mixed-case key with a lowercase twin and a
// value that would classify differently if the key were left as-is, so dropping the conversion
// fails this instead of silently mistyping properties. The last case is non-ASCII, covering the
// owning fallback rather than the borrow.
#[rstest]
#[case(
    "UTM_Source",
    "utm_source",
    Value::Number(Number::from(12345)),
    PropertyValueType::String
)]
#[case(
    "$Initial_UTM_Campaign",
    "$initial_utm_campaign",
    Value::from("2023-12-13"),
    PropertyValueType::String
)]
#[case(
    "$FEATURE/My-Flag",
    "$feature/my-flag",
    Value::Bool(true),
    PropertyValueType::String
)]
#[case(
    "$Feature_Flag_Response",
    "$feature_flag_response",
    Value::Bool(true),
    PropertyValueType::String
)]
#[case(
    "$Survey_Response_2",
    "$survey_response_2",
    Value::Number(Number::from(7)),
    PropertyValueType::String
)]
// A numeric value only reads as a timestamp when the key carries a DATETIME keyword, so this is
// the case where normalizing "_At" to "_at" is the whole decision. The epoch is computed rather
// than fixed because the value-side check only accepts the last six months.
#[case(
    "Created_At",
    "created_at",
    Value::Number(Number::from(Utc::now().timestamp())),
    PropertyValueType::DateTime
)]
#[case(
    "UTM_Sourceǅ",
    "utm_sourceǅ",
    Value::Number(Number::from(12345)),
    PropertyValueType::String
)]
fn test_property_type_detection_normalizes_key_case(
    #[case] mixed_case: &str,
    #[case] lower_case: &str,
    #[case] value: Value,
    #[case] expected: PropertyValueType,
) {
    assert_eq!(
        detect_property_type(mixed_case, &value),
        Some(expected.clone()),
        "expected {expected:?} for mixed-case key={mixed_case}, value={value}"
    );
    assert_eq!(
        detect_property_type(lower_case, &value),
        Some(expected.clone()),
        "expected {expected:?} for lowercase key={lower_case}, value={value}"
    );
}

#[test]
fn test_property_keys_are_sanitized_of_null_bytes() {
    // Property keys with embedded null bytes must be sanitized before reaching Postgres,
    // otherwise the INSERT fails with 22021 (invalid_text_representation) and burns the
    // 3-retry batch. We mirror the existing sanitize on event names.
    let event = Event {
        team_id: 1,
        project_id: 1,
        event: "$pageview".to_string(),
        properties: Some(r#"{"clean_key":"v","key\u0000with\u0000nulls":"v"}"#.to_string()),
    };

    let updates = event.into_updates(1000);

    // Expect: 1 EventDefinition + 2 EventProperty + 2 PropertyDefinition = 5 updates
    assert_eq!(
        updates.len(),
        5,
        "all keys should produce updates: {updates:?}"
    );

    let replacement_char = '\u{FFFD}';

    let mut saw_sanitized_event_property = false;
    let mut saw_sanitized_property_definition = false;

    for update in &updates {
        match update {
            Update::EventProperty(ep) => {
                assert!(
                    !ep.property.contains('\u{0000}'),
                    "EventProperty.property must not contain null bytes: {:?}",
                    ep.property
                );
                if ep.property.contains(replacement_char) {
                    saw_sanitized_event_property = true;
                }
            }
            Update::Property(pd) => {
                assert!(
                    !pd.name.contains('\u{0000}'),
                    "PropertyDefinition.name must not contain null bytes: {:?}",
                    pd.name
                );
                if pd.name.contains(replacement_char) {
                    saw_sanitized_property_definition = true;
                }
            }
            Update::Event(_) => {}
        }
    }

    assert!(
        saw_sanitized_event_property,
        "expected at least one EventProperty with the sanitized key: {updates:?}"
    );
    assert!(
        saw_sanitized_property_definition,
        "expected at least one PropertyDefinition with the sanitized name: {updates:?}"
    );
}

#[test]
fn test_event_properties_only_emitted_for_event_parent_type() {
    let props = json!({
        "url": "https://example.com",
        "count": 42,
        "$set": {
            "email": "test@example.com",
            "name": "Test User"
        }
    });
    let event = Event {
        team_id: 1,
        project_id: 1,
        event: "my_event".to_string(),
        properties: Some(props.to_string()),
    };

    let updates = event.into_updates(1000);

    let event_property_keys: Vec<&str> = updates
        .iter()
        .filter_map(|u| match u {
            Update::EventProperty(ep) => Some(ep.property.as_str()),
            _ => None,
        })
        .collect();

    // Only top-level event properties should produce EventProperty updates;
    // $set is in SKIP_PROPERTIES so it's excluded from event-type processing
    assert!(
        event_property_keys.contains(&"url"),
        "expected EventProperty for top-level 'url': {event_property_keys:?}"
    );
    assert!(
        event_property_keys.contains(&"count"),
        "expected EventProperty for top-level 'count': {event_property_keys:?}"
    );
    assert_eq!(
        event_property_keys.len(),
        2,
        "expected exactly 2 EventProperty updates (url + count), got: {event_property_keys:?}"
    );
    // Person properties from $set must NOT produce EventProperty rows
    assert!(
        !event_property_keys.contains(&"email"),
        "person property 'email' must not appear in EventProperty: {event_property_keys:?}"
    );
    assert!(
        !event_property_keys.contains(&"name"),
        "person property 'name' must not appear in EventProperty: {event_property_keys:?}"
    );

    // But person properties should still produce PropertyDefinition updates
    let prop_def_names: Vec<&str> = updates
        .iter()
        .filter_map(|u| match u {
            Update::Property(pd) => Some(pd.name.as_str()),
            _ => None,
        })
        .collect();
    assert!(
        prop_def_names.contains(&"email"),
        "expected PropertyDefinition for person property 'email': {prop_def_names:?}"
    );
    assert!(
        prop_def_names.contains(&"name"),
        "expected PropertyDefinition for person property 'name': {prop_def_names:?}"
    );
}

#[test]
fn test_groupidentify_emits_zero_event_properties() {
    let props = json!({
        "$group_type": "company",
        "$group_key": "posthog",
        "$group_set": {
            "name": "PostHog",
            "industry": "Analytics"
        }
    });
    let event = Event {
        team_id: 1,
        project_id: 1,
        event: "$groupidentify".to_string(),
        properties: Some(props.to_string()),
    };

    let updates = event.into_updates(1000);

    let event_property_count = updates
        .iter()
        .filter(|u| matches!(u, Update::EventProperty(_)))
        .count();

    assert_eq!(
        event_property_count, 0,
        "expected zero EventProperty updates for $groupidentify, got {event_property_count}: {updates:?}"
    );

    // Group properties should still produce PropertyDefinition updates
    let prop_def_names: Vec<&str> = updates
        .iter()
        .filter_map(|u| match u {
            Update::Property(pd) => Some(pd.name.as_str()),
            _ => None,
        })
        .collect();
    assert!(
        prop_def_names.contains(&"name"),
        "expected PropertyDefinition for group property 'name': {prop_def_names:?}"
    );
    assert!(
        prop_def_names.contains(&"industry"),
        "expected PropertyDefinition for group property 'industry': {prop_def_names:?}"
    );
}

#[test]
fn test_plain_event_properties_still_emitted() {
    let props = json!({
        "page": "/home",
        "referrer": "https://google.com"
    });
    let event = Event {
        team_id: 1,
        project_id: 1,
        event: "$pageview".to_string(),
        properties: Some(props.to_string()),
    };

    let updates = event.into_updates(1000);

    let event_property_keys: Vec<&str> = updates
        .iter()
        .filter_map(|u| match u {
            Update::EventProperty(ep) => Some(ep.property.as_str()),
            _ => None,
        })
        .collect();

    assert_eq!(
        event_property_keys.len(),
        2,
        "expected exactly 2 EventProperty updates: {event_property_keys:?}"
    );
    assert!(event_property_keys.contains(&"page"));
    assert!(event_property_keys.contains(&"referrer"));
}

#[rstest]
#[case("$feature/", "$feature/my-flag")]
#[case("$feature_enrollment/", "$feature_enrollment/enrolled-flag")]
fn test_feature_flag_properties_skip_event_property_but_keep_property_definition(
    #[case] prefix: &str,
    #[case] flagged_key: &str,
) {
    let mut props_map = Map::new();
    props_map.insert("page".to_string(), json!("/home"));
    props_map.insert("$active_feature_flags".to_string(), json!(["my-flag"]));
    props_map.insert(flagged_key.to_string(), json!(true));

    let event = Event {
        team_id: 1,
        project_id: 1,
        event: "$pageview".to_string(),
        properties: Some(Value::Object(props_map).to_string()),
    };

    let updates = event.into_updates(1000);

    let event_property_keys: Vec<&str> = updates
        .iter()
        .filter_map(|u| match u {
            Update::EventProperty(ep) => Some(ep.property.as_str()),
            _ => None,
        })
        .collect();

    assert!(
        !event_property_keys.iter().any(|k| k.starts_with(prefix)),
        "{prefix}* must not appear in EventProperty: {event_property_keys:?}"
    );

    assert!(
        event_property_keys.contains(&"page"),
        "expected EventProperty for 'page': {event_property_keys:?}"
    );
    assert!(
        event_property_keys.contains(&"$active_feature_flags"),
        "expected EventProperty for '$active_feature_flags': {event_property_keys:?}"
    );

    let prop_def_names: Vec<&str> = updates
        .iter()
        .filter_map(|u| match u {
            Update::Property(pd) => Some(pd.name.as_str()),
            _ => None,
        })
        .collect();
    assert!(
        prop_def_names.contains(&flagged_key),
        "expected PropertyDefinition for '{flagged_key}': {prop_def_names:?}"
    );
}
