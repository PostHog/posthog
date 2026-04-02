use chrono::Utc;
use property_defs_rs::types::{detect_property_type, get_floored_last_seen, PropertyValueType};
use serde_json::{Number, Value};

#[test]
fn test_date_flooring() {
    use chrono::Timelike;

    let now = Utc::now();
    let rounded = get_floored_last_seen();

    // Time should be rounded to the nearest hour
    assert_eq!(rounded.minute(), 0);
    assert_eq!(rounded.second(), 0);
    assert_eq!(rounded.nanosecond(), 0);
    assert!(rounded <= now);

    // The difference between now and rounded should be less than 1 hour
    assert!(now - rounded < chrono::Duration::hours(1));
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
