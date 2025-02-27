use std::{fmt, hash::Hash, str::FromStr};

use chrono::{DateTime, Duration, DurationRound, RoundingError, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sqlx::{Executor, Postgres};
use tracing::warn;
use uuid::Uuid;

use crate::metrics_consts::{EVENTS_SKIPPED, UPDATES_ISSUED, UPDATES_SKIPPED};

// We skip updates for events we generate
pub const EVENTS_WITHOUT_PROPERTIES: [&str; 1] = ["$$plugin_metrics"];

// These properties have special meaning, and are ignored
pub const SKIP_PROPERTIES: [&str; 9] = [
    "$set",
    "$set_once",
    "$unset",
    "$group_0",
    "$group_1",
    "$group_2",
    "$group_3",
    "$group_4",
    "$groups",
];

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, PartialOrd, Ord)]
pub enum PropertyParentType {
    Event = 1,
    Person = 2,
    Group = 3,
    Session = 4,
}

impl From<PropertyParentType> for i32 {
    fn from(parent_type: PropertyParentType) -> i32 {
        match parent_type {
            PropertyParentType::Event => 1,
            PropertyParentType::Person => 2,
            PropertyParentType::Group => 3,
            PropertyParentType::Session => 4,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq, PartialOrd, Ord)]
pub enum PropertyValueType {
    DateTime,
    String,
    Numeric,
    Boolean,
    Duration, // Unused, but exists.
}

impl fmt::Display for PropertyValueType {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            PropertyValueType::DateTime => write!(f, "DateTime"),
            PropertyValueType::String => write!(f, "String"),
            PropertyValueType::Numeric => write!(f, "Numeric"),
            PropertyValueType::Boolean => write!(f, "Boolean"),
            PropertyValueType::Duration => write!(f, "Duration"),
        }
    }
}

// The grouptypemapping table uses i32's, but we get group types by name, so we have to resolve them before DB writes, sigh
#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub enum GroupType {
    Unresolved(String),
    Resolved(String, i32),
}

impl GroupType {
    pub fn resolve(self, index: i32) -> Self {
        match self {
            GroupType::Unresolved(name) => GroupType::Resolved(name, index),
            GroupType::Resolved(name, _) => GroupType::Resolved(name, index),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub struct PropertyDefinition {
    pub team_id: i32,
    pub project_id: i64,
    pub name: String,
    pub is_numerical: bool,
    pub property_type: Option<PropertyValueType>,
    pub event_type: PropertyParentType,
    pub group_type_index: Option<GroupType>,
    pub property_type_format: Option<String>, // Deprecated
    pub volume_30_day: Option<i64>,           // Deprecated
    pub query_usage_30_day: Option<i64>,      // Deprecated
}

#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub struct EventDefinition {
    pub name: String,
    pub team_id: i32,
    pub project_id: i64,
    pub last_seen_at: DateTime<Utc>, // Always floored to our update rate for last_seen, so this Eq derive is safe for deduping
}

// Derived hash since these are keyed on all fields in the DB
#[derive(Clone, Debug, Hash, Eq, PartialEq, PartialOrd, Ord)]
pub struct EventProperty {
    pub team_id: i32,
    pub project_id: i64,
    pub event: String,
    pub property: String,
}

// Represents a generic update, but comparable, allowing us to dedupe and cache updates
#[derive(Clone, Debug, Hash, Eq, PartialEq, PartialOrd, Ord)]
pub enum Update {
    Event(EventDefinition),
    Property(PropertyDefinition),
    EventProperty(EventProperty),
}

impl Update {
    pub async fn issue<'c, E>(&self, executor: E) -> Result<(), sqlx::Error>
    where
        E: Executor<'c, Database = Postgres>,
    {
        match self {
            Update::Event(e) => e.issue(executor).await,
            Update::Property(p) => p.issue(executor).await,
            Update::EventProperty(ep) => ep.issue(executor).await,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Event {
    pub team_id: i32,
    pub project_id: i64,
    pub event: String,
    pub properties: Option<String>,
}

impl From<&Event> for EventDefinition {
    fn from(event: &Event) -> Self {
        EventDefinition {
            name: sanitize_event_name(&event.event),
            team_id: event.team_id,
            project_id: event.project_id,
            last_seen_at: get_floored_last_seen(),
        }
    }
}

impl Event {
    pub fn into_updates(self, skip_threshold: usize) -> Vec<Update> {
        if EVENTS_WITHOUT_PROPERTIES.contains(&self.event.as_str()) {
            metrics::counter!(EVENTS_SKIPPED, &[("reason", "no_properties_event")]).increment(1);
            return vec![];
        }

        if !will_fit_in_postgres_column(&self.event) {
            metrics::counter!(EVENTS_SKIPPED, &[("reason", "name_wont_fit_in_postgres")])
                .increment(1);
            return vec![];
        }

        let team_id = self.team_id;
        let event = self.event.clone();

        let updates = self.into_updates_inner();
        if updates.len() > skip_threshold {
            warn!(
                "Event {} for team {} has more than {} properties, skipping",
                event, team_id, skip_threshold
            );
            metrics::counter!(EVENTS_SKIPPED, &[("reason", "too_many_properties")]).increment(1);
            return vec![];
        }

        updates
    }

    fn into_updates_inner(self) -> Vec<Update> {
        let mut updates = vec![Update::Event(EventDefinition::from(&self))];
        let Some(props) = &self.properties else {
            return updates;
        };

        let Ok(props) = Value::from_str(props) else {
            return updates;
        };

        let Value::Object(props) = props else {
            return updates;
        };

        // If this is a groupidentify event, we ONLY bubble up the group properties
        if self.event == "$groupidentify" {
            let Some(Value::String(group_type)) = props.get("$group_type") else {
                return updates;
            };
            let group_type = GroupType::Unresolved(group_type.clone());

            let Some(group_properties) = props.get("$group_set") else {
                return updates;
            };

            let Value::Object(group_properties) = group_properties else {
                return updates;
            };

            self.get_props_from_object(
                &mut updates,
                group_properties,
                PropertyParentType::Group,
                Some(group_type),
            );
            return updates;
        }

        // Grab the "ordinary" (non-person) event properties
        self.get_props_from_object(&mut updates, &props, PropertyParentType::Event, None);

        // If there are any person properties, also push those into the flat property map.
        if let Some(Value::Object(set_props)) = props.get("$set") {
            self.get_props_from_object(&mut updates, set_props, PropertyParentType::Person, None)
        }
        if let Some(Value::Object(set_once_props)) = props.get("$set_once") {
            self.get_props_from_object(
                &mut updates,
                set_once_props,
                PropertyParentType::Person,
                None,
            )
        }

        updates
    }

    fn get_props_from_object(
        &self,
        updates: &mut Vec<Update>,
        set: &Map<String, Value>,
        parent_type: PropertyParentType,
        group_type: Option<GroupType>,
    ) {
        updates.reserve(set.len() * 2);
        for (key, value) in set {
            if SKIP_PROPERTIES.contains(&key.as_str()) && parent_type == PropertyParentType::Event {
                continue;
            }

            if !will_fit_in_postgres_column(key) {
                metrics::counter!(
                    UPDATES_SKIPPED,
                    &[("reason", "property_name_wont_fit_in_postgres")]
                )
                .increment(2); // We're skipping one EventProperty, and one PropertyDefinition
                continue;
            }

            updates.push(Update::EventProperty(EventProperty {
                team_id: self.team_id,
                project_id: self.project_id,
                event: self.event.clone(),
                property: key.clone(),
            }));

            let property_type = detect_property_type(key, value);
            let is_numerical = matches!(property_type, Some(PropertyValueType::Numeric));

            updates.push(Update::Property(PropertyDefinition {
                team_id: self.team_id,
                project_id: self.project_id,
                name: key.clone(),
                is_numerical,
                property_type,
                event_type: parent_type,
                group_type_index: group_type.clone(),
                property_type_format: None,
                volume_30_day: None,
                query_usage_30_day: None,
            }));
        }
    }
}

fn detect_property_type(key: &str, value: &Value) -> Option<PropertyValueType> {
    // There are a whole set of special cases here, taken from the TS
    if key.starts_with("utm_") {
        // utm_ prefixed properties should always be detected as strings.
        // Sometimes the first value sent looks like a number, event though
        // subsequent values are not. See
        // https://github.com/PostHog/posthog/issues/12529 for more context.
        return Some(PropertyValueType::String);
    }
    if key.starts_with("$feature/") {
        // $feature/ prefixed properties should always be detected as strings.
        // These are feature flag values, and can be boolean or string.
        // Sometimes the first value sent is boolean (because flag isn't enabled) while
        // subsequent values are not. We don't want this to be misunderstood as a boolean.
        return Some(PropertyValueType::String);
    }

    if key == "$feature_flag_response" {
        // $feature_flag_response properties should always be detected as strings.
        // These are feature flag values, and can be boolean or string.
        // Sometimes the first value sent is boolean (because flag isn't enabled) while
        // subsequent values are not. We don't want this to be misunderstood as a boolean.
        return Some(PropertyValueType::String);
    }

    if key.starts_with("$survey_response") {
        // NB: $survey_responses are collected in an interesting way, where the first
        // response is called `$survey_response` and subsequent responses are called
        // `$survey_response_2`, `$survey_response_3`, etc.  So, this check should auto-cast
        // all survey responses to strings, and $survey_response properties should always be detected as strings.
        return Some(PropertyValueType::String);
    }

    match value {
        Value::String(s) => {
            let s = &s.trim();
            if *s == "true" || *s == "false" || *s == "TRUE" || *s == "FALSE" {
                Some(PropertyValueType::Boolean)
            // Try to parse this as an ISO 8601 date, and if we can, use that as the type instead
            } else if DateTime::parse_from_rfc3339(s).is_ok() {
                Some(PropertyValueType::DateTime)
            } else {
                Some(PropertyValueType::String)
            }
        }
        Value::Number(_) => {
            // TODO - this is a divergence from the TS impl - the TS also checks if the contained number is
            // "likely" to be a unix timestamp on the basis of the number of characters. I have mixed feelings about this,
            // so I'm going to leave it as just checking the key for now. This means we're being /less/ strict with datetime
            // detection here than in the TS
            if key.contains("timestamp")
                || key.contains("TIMESTAMP")
                || key.contains("time")
                || key.contains("TIME")
            {
                Some(PropertyValueType::DateTime)
            } else {
                Some(PropertyValueType::Numeric)
            }
        }
        Value::Bool(_) => Some(PropertyValueType::Boolean),
        _ => None,
    }
}

fn sanitize_event_name(event_name: &str) -> String {
    event_name.replace('\u{0000}', "\u{FFFD}")
}

// These hash impls correspond to DB uniqueness constraints, pulled from the TS
impl Hash for PropertyDefinition {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.team_id.hash(state);
        self.name.hash(state);
        self.event_type.hash(state);
        self.group_type_index.hash(state);
    }
}

impl Hash for EventDefinition {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.team_id.hash(state);
        self.name.hash(state);
        self.last_seen_at.hash(state)
    }
}

// Ensure group type hashes identically regardless of whether it's resolved or not. Note that if
// someone changes the name associated with a group type, all subsequent events will hash differently
// because of this, but that seems fine - it just means a few extra DB ops issued, we index on the i32
// at write time anyway
impl Hash for GroupType {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        match self {
            GroupType::Unresolved(name) => name.hash(state),
            GroupType::Resolved(name, _) => name.hash(state),
        }
    }
}

// We round last seen to the nearest hour. Unwrap is safe here because
// the duration is positive, non-zero, and smaller than time since epoch
pub fn get_floored_last_seen() -> DateTime<Utc> {
    floor_datetime(Utc::now(), Duration::hours(1)).unwrap()
}

fn floor_datetime(dt: DateTime<Utc>, duration: Duration) -> Result<DateTime<Utc>, RoundingError> {
    let rounded = dt.duration_round(duration)?;

    // If we rounded up
    if rounded > dt {
        Ok(rounded - duration)
    } else {
        Ok(rounded)
    }
}

// We impose some limits on some fields for legacy reasons, and drop updates that don't conform to them
pub const DJANGO_MAX_CHARFIELD_LENGTH: usize = 400;
fn will_fit_in_postgres_column(str: &str) -> bool {
    str.len() <= DJANGO_MAX_CHARFIELD_LENGTH / 2
}

// Postgres doesn't like nulls in strings, so we replace them with uFFFD.
// This allocates, so only do it right when hitting the DB. We handle nulls
// in strings just fine.
pub fn sanitize_string(s: String) -> String {
    s.replace('\u{0000}', "\u{FFFD}")
}

// The queries below are pulled more-or-less exactly from the TS impl.

impl EventDefinition {
    pub async fn issue<'c, E>(&self, executor: E) -> Result<(), sqlx::Error>
    where
        E: Executor<'c, Database = Postgres>,
    {
        let res = sqlx::query!(
            r#"
            INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, project_id, last_seen_at, created_at)
            VALUES ($1, $2, NULL, NULL, $3, $4, $5, NOW())
            ON CONFLICT (coalesce(project_id, team_id::bigint), name)
            DO UPDATE SET last_seen_at = $5
        "#,
            Uuid::now_v7(),
            self.name,
            self.team_id,
            self.project_id,
            Utc::now() // We floor the update datetime to the nearest day for cache purposes, but can insert the exact time we see the event
        ).execute(executor).await.map(|_| ());

        metrics::counter!(UPDATES_ISSUED, &[("type", "event_definition")]).increment(1);

        res
    }
}

impl PropertyDefinition {
    pub async fn issue<'c, E>(&self, executor: E) -> Result<(), sqlx::Error>
    where
        E: Executor<'c, Database = Postgres>,
    {
        let group_type_index = match &self.group_type_index {
            Some(GroupType::Resolved(_, i)) => Some(*i as i16),
            Some(GroupType::Unresolved(group_name)) => {
                warn!(
                    "Group type {} not resolved for property definition {} for team {}, skipping update",
                    group_name, self.name, self.team_id
                );
                None
            }
            _ => {
                // We don't have a group type, so we don't have a group type index
                None
            }
        };

        if group_type_index.is_none() && matches!(self.event_type, PropertyParentType::Group) {
            // Some teams/users wildly misuse group-types, and if we fail to issue an update
            // during the transaction (which we do if we don't have a group-type index for a
            // group property), the entire transaction is aborted, so instead we just warn
            // loudly about this (above, and at resolve time), and drop the update.
            return Ok(());
        }

        let res = sqlx::query!(
            r#"
            INSERT INTO posthog_propertydefinition (id, name, type, group_type_index, is_numerical, volume_30_day, query_usage_30_day, team_id, project_id, property_type)
            VALUES ($1, $2, $3, $4, $5, NULL, NULL, $6, $7, $8)
            ON CONFLICT (coalesce(project_id, team_id::bigint), name, type, coalesce(group_type_index, -1))
            DO UPDATE SET property_type=EXCLUDED.property_type WHERE posthog_propertydefinition.property_type IS NULL
        "#,
            Uuid::now_v7(),
            self.name,
            self.event_type as i16,
            group_type_index,
            self.is_numerical,
            self.team_id,
            self.project_id,
            self.property_type.as_ref().map(|t| t.to_string())
        ).execute(executor).await.map(|_| ());

        metrics::counter!(UPDATES_ISSUED, &[("type", "property_definition")]).increment(1);

        res
    }
}

impl EventProperty {
    pub async fn issue<'c, E>(&self, executor: E) -> Result<(), sqlx::Error>
    where
        E: Executor<'c, Database = Postgres>,
    {
        let res = sqlx::query!(
            r#"INSERT INTO posthog_eventproperty (event, property, team_id, project_id) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING"#,
            self.event,
            self.property,
            self.team_id,
            self.project_id
        )
        .execute(executor)
        .await
        .map(|_| ());

        metrics::counter!(UPDATES_ISSUED, &[("type", "event_property")]).increment(1);

        res
    }
}

#[cfg(test)]
mod test {
    use chrono::{Timelike, Utc};
    use serde_json::Value;

    use crate::types::{detect_property_type, get_floored_last_seen, PropertyValueType};

    #[test]
    fn test_date_flooring() {
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
    fn test_rfc3339_timestamp_detection() {
        // Test RFC 3339 timestamp detection for string values
        assert_eq!(
            detect_property_type(
                "random_property",
                &Value::String("2023-12-13T15:45:30Z".to_string())
            ),
            Some(PropertyValueType::DateTime)
        );

        assert_eq!(
            detect_property_type(
                "random_property",
                &Value::String("2023-12-13T15:45:30.123Z".to_string())
            ),
            Some(PropertyValueType::DateTime)
        );

        assert_eq!(
            detect_property_type(
                "random_property",
                &Value::String("2023-12-13T15:45:30+00:00".to_string())
            ),
            Some(PropertyValueType::DateTime)
        );

        assert_eq!(
            detect_property_type(
                "random_property",
                &Value::String("2023-12-13T15:45:30-07:00".to_string())
            ),
            Some(PropertyValueType::DateTime)
        );

        // Test invalid timestamp formats (should be detected as String)
        assert_eq!(
            detect_property_type("random_property", &Value::String("2023-12-13".to_string())),
            Some(PropertyValueType::String)
        );

        assert_eq!(
            detect_property_type("random_property", &Value::String("15:45:30".to_string())),
            Some(PropertyValueType::String)
        );

        assert_eq!(
            detect_property_type("random_property", &Value::String("not a date".to_string())),
            Some(PropertyValueType::String)
        );

        // Test property name-based detection for numeric values (should be DateTime)
        assert_eq!(
            detect_property_type(
                "timestamp",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::DateTime)
        );

        assert_eq!(
            detect_property_type(
                "created_time",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::DateTime)
        );

        assert_eq!(
            detect_property_type(
                "sent_at",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::Numeric)
        );

        // Test property name-based detection for string values (should NOT be DateTime)
        assert_eq!(
            detect_property_type("timestamp", &Value::String("any value".to_string())),
            Some(PropertyValueType::String)
        );

        assert_eq!(
            detect_property_type("created_time", &Value::String("any value".to_string())),
            Some(PropertyValueType::String)
        );

        assert_eq!(
            detect_property_type("sent_at", &Value::String("any value".to_string())),
            Some(PropertyValueType::String)
        );
    }

    #[test]
    fn test_property_name_based_detection() {
        // Test all timestamp-related keywords for numeric values

        // Test "timestamp" in different positions and cases
        assert_eq!(
            detect_property_type(
                "timestamp",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::DateTime)
        );
        assert_eq!(
            detect_property_type(
                "TIMESTAMP",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::DateTime)
        );
        assert_eq!(
            detect_property_type(
                "user_timestamp",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::DateTime)
        );
        assert_eq!(
            detect_property_type(
                "user_TIMESTAMP",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::DateTime)
        );
        assert_eq!(
            detect_property_type(
                "timestampValue",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::DateTime)
        );

        // Test "time" in different positions and cases
        assert_eq!(
            detect_property_type("time", &Value::Number(serde_json::Number::from(1639400730))),
            Some(PropertyValueType::DateTime)
        );
        assert_eq!(
            detect_property_type("TIME", &Value::Number(serde_json::Number::from(1639400730))),
            Some(PropertyValueType::DateTime)
        );
        assert_eq!(
            detect_property_type(
                "created_time",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::DateTime)
        );
        assert_eq!(
            detect_property_type(
                "created_TIME",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::DateTime)
        );
        assert_eq!(
            detect_property_type(
                "timeValue",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::DateTime)
        );

        // Test non-matching property names (should be Numeric)
        assert_eq!(
            detect_property_type("count", &Value::Number(serde_json::Number::from(42))),
            Some(PropertyValueType::Numeric)
        );
        assert_eq!(
            detect_property_type("amount", &Value::Number(serde_json::Number::from(100))),
            Some(PropertyValueType::Numeric)
        );
        assert_eq!(
            detect_property_type(
                "sent_at",
                &Value::Number(serde_json::Number::from(1639400730))
            ),
            Some(PropertyValueType::Numeric)
        );

        // Verify that string values are never detected as DateTime based on property name
        assert_eq!(
            detect_property_type("timestamp", &Value::String("not a date".to_string())),
            Some(PropertyValueType::String)
        );
        assert_eq!(
            detect_property_type("TIMESTAMP", &Value::String("not a date".to_string())),
            Some(PropertyValueType::String)
        );
        assert_eq!(
            detect_property_type("time", &Value::String("not a date".to_string())),
            Some(PropertyValueType::String)
        );
        assert_eq!(
            detect_property_type("TIME", &Value::String("not a date".to_string())),
            Some(PropertyValueType::String)
        );
    }
}
