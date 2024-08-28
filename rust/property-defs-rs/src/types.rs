use std::{fmt, hash::Hash, str::FromStr};

use chrono::{DateTime, Duration, DurationRound, RoundingError, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tracing::warn;
use uuid::Uuid;

use crate::metrics_consts::EVENTS_SKIPPED;

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

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
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

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
pub enum PropertyValueType {
    DateTime,
    String,
    Numeric,
    Boolean,
    Duration,
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
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GroupType {
    Unresolved(String),
    Resolved(String, i32),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PropertyDefinition {
    pub id: Uuid,
    pub team_id: i32,
    pub name: String,
    pub is_numerical: bool,
    pub property_type: Option<PropertyValueType>,
    pub event_type: Option<PropertyParentType>,
    pub group_type_index: Option<GroupType>,
    pub property_type_format: Option<String>, // Deprecated
    pub volume_30_day: Option<i64>,           // Deprecated
    pub query_usage_30_day: Option<i64>,      // Deprecated
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EventDefinition {
    pub id: Uuid,
    pub name: String,
    pub team_id: i32,
    pub last_seen_at: DateTime<Utc>,
}

// Derived hash since these are keyed on all fields in the DB
#[derive(Clone, Debug, Hash, Eq, PartialEq)]
pub struct EventProperty {
    team_id: i32,
    event: String,
    property: String,
}

// Represents a generic update, but comparable, allowing us to dedupe and cache updates
#[derive(Clone, Debug, Hash, Eq, PartialEq)]
pub enum Update {
    Event(EventDefinition),
    Property(PropertyDefinition),
    EventProperty(EventProperty),
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Event {
    pub team_id: i32,
    pub event: String,
    pub properties: Option<String>,
}

impl From<&Event> for EventDefinition {
    fn from(event: &Event) -> Self {
        EventDefinition {
            id: Uuid::now_v7(),
            name: sanitize_event_name(&event.event),
            team_id: event.team_id,
            // We round last seen to the nearest day, as per the TS impl. Unwrap is safe here because we
            // the duration is positive, non-zero, and smaller than time since epoch
            last_seen_at: floor_datetime(Utc::now(), Duration::days(1)).unwrap(),
        }
    }
}

impl Event {
    pub fn into_updates(self, skip_threshold: usize) -> Vec<Update> {
        let team_id = self.team_id;
        let event = self.event.clone();

        let updates = self.into_updates_inner();
        if updates.len() > skip_threshold {
            warn!(
                "Event {} for team {} has more than 10,000 properties, skipping",
                event, team_id
            );
            metrics::counter!(EVENTS_SKIPPED).increment(1);
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

            updates.push(Update::EventProperty(EventProperty {
                team_id: self.team_id,
                event: self.event.clone(),
                property: key.clone(),
            }));

            let property_type = detect_property_type(key, value);
            let is_numerical = matches!(property_type, Some(PropertyValueType::Numeric));

            let def = PropertyDefinition {
                id: Uuid::now_v7(),
                team_id: self.team_id,
                name: key.clone(),
                is_numerical,
                property_type,
                event_type: Some(parent_type),
                group_type_index: group_type.clone(),
                property_type_format: None,
                volume_30_day: None,
                query_usage_30_day: None,
            };
            updates.push(Update::Property(def));
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
            let s = &s.trim().to_lowercase();
            if s == "true" || s == "false" {
                Some(PropertyValueType::Boolean)
            } else {
                // TODO - we should try to auto-detect datetime strings here, but I'm skipping the chunk of regex necessary to do it for v0
                Some(PropertyValueType::String)
            }
        }
        Value::Number(_) => {
            // TODO - this is a divergence from the TS impl - the TS also checks if the contained number is
            // "likely" to be a unix timestamp on the basis of the number of characters. I have mixed feelings about this,
            // so I'm going to leave it as just checking the key for now. This means we're being /less/ strict with datetime
            // detection here than in the TS
            if key.to_lowercase().contains("timestamp") || key.to_lowercase().contains("time") {
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

fn floor_datetime(dt: DateTime<Utc>, duration: Duration) -> Result<DateTime<Utc>, RoundingError> {
    let rounded = dt.duration_round(duration)?;

    // If we rounded up
    if rounded > dt {
        Ok(rounded - duration)
    } else {
        Ok(rounded)
    }
}
