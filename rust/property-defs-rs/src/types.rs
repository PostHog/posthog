use std::{borrow::Cow, fmt, hash::Hash, str::FromStr, sync::LazyLock};

use chrono::{DateTime, Utc};
use regex::Regex;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{Map, Value};
use tracing::warn;

use crate::metrics_consts::{EVENTS_SKIPPED, UPDATES_SKIPPED};

// Custom deserializer that can handle both string and integer values
fn deserialize_string_or_i32<'de, D>(deserializer: D) -> Result<i32, D::Error>
where
    D: Deserializer<'de>,
{
    use serde::de;

    #[derive(Deserialize)]
    #[serde(untagged)]
    enum StringOrInt {
        String(String),
        Int(i32),
    }

    match StringOrInt::deserialize(deserializer)? {
        StringOrInt::String(s) => s
            .parse::<i32>()
            .map_err(|e| de::Error::custom(format!("Failed to parse string as i32: {e}"))),
        StringOrInt::Int(i) => Ok(i),
    }
}

// Custom deserializer that can handle both string and integer values for i64
fn deserialize_string_or_i64<'de, D>(deserializer: D) -> Result<i64, D::Error>
where
    D: Deserializer<'de>,
{
    use serde::de;

    #[derive(Deserialize)]
    #[serde(untagged)]
    enum StringOrInt {
        String(String),
        Int(i64),
    }

    match StringOrInt::deserialize(deserializer)? {
        StringOrInt::String(s) => s
            .parse::<i64>()
            .map_err(|e| de::Error::custom(format!("Failed to parse string as i64: {e}"))),
        StringOrInt::Int(i) => Ok(i),
    }
}

// We skip updates for events we generate
pub const EVENTS_WITHOUT_PROPERTIES: [&str; 1] = ["$$plugin_metrics"];

pub const SIX_MONTHS_AGO_SECS: u64 = 15768000;
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

// Property key prefixes that should NOT generate posthog_eventproperty rows.
// Feature flags are appended as $feature/<key> on nearly every event by posthog-js,
// so the (event_name × flag_key) cross product dominates eventproperty cardinality
// without providing useful per-event scoping (flags are global). The corresponding
// PropertyDefinition rows ARE still written so flags remain discoverable.
// $feature_enrollment/ is usually a person property; it's included defensively for the
// rare cases it arrives as a top-level event property, and carries little cardinality weight.
pub const SKIP_EVENT_PROPERTY_PREFIXES: [&str; 2] = ["$feature/", "$feature_enrollment/"];

const DATETIME_PROPERTY_NAME_KEYWORDS: [&str; 7] = [
    "time",
    "timestamp",
    "date",
    "_at",
    "-at",
    "createdat",
    "updatedat",
];

// TRICKY: the pattern below is a best-effort attempt to classify likely DateTime properties by
// a string prefix of their value. While this doesn't enforce compliance to standard formats,
// it does represent a pretty strong indication of the user's intent, for the purposes of
// *property definition capture only* especially when a bad decision "locks" the property name
// to the wrong type. Try it here: https://rustexp.lpil.uk/ and review the unit tests.
// Also notable: post-capture, PostHog displays timestamps in a variety formats:
// https://github.com/PostHog/posthog/blob/master/posthog/models/property_definition.py#L18-L30
static DATETIME_PREFIX_REGEX: LazyLock<Regex> = LazyLock::new(|| {
    regex::Regex::new(
        r#"^(([0-9]{4}[/-][0-2][0-9][/-][0-3][0-9])|([0-2][0-9][/-][0-3][0-9][/-][0-9]{4}))([ T][0-2][0-9]:[0-6][0-9]:[0-6][0-9].*)?$"#
    ).unwrap()
});

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, PartialOrd, Ord, Deserialize, Serialize)]
pub enum PropertyParentType {
    Event = 1,
    Person = 2,
    Group = 3,
    Session = 4,
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
#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord, Deserialize, Serialize)]
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

    /// Returns the Unresolved form of this group type. The shared dedup cache
    /// always stores entries as Unresolved (inserted by the producer before
    /// resolution), so cache removal after a failed batch write must use this
    /// form to match the original key.
    pub fn as_unresolved(&self) -> Self {
        match self {
            GroupType::Unresolved(_) => self.clone(),
            GroupType::Resolved(name, _) => GroupType::Unresolved(name.clone()),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord, Deserialize, Serialize)]
pub struct PropertyDefinition {
    #[serde(deserialize_with = "deserialize_string_or_i32")]
    pub team_id: i32,
    #[serde(deserialize_with = "deserialize_string_or_i64")]
    pub project_id: i64,
    pub name: String,
    pub is_numerical: bool,
    pub property_type: Option<PropertyValueType>,
    pub event_type: PropertyParentType,
    pub group_type_index: Option<GroupType>,
}

#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord, Deserialize, Serialize)]
pub struct EventDefinition {
    pub name: String,
    #[serde(deserialize_with = "deserialize_string_or_i32")]
    pub team_id: i32,
    #[serde(deserialize_with = "deserialize_string_or_i64")]
    pub project_id: i64,
    // Always floored to EVENTDEF_LAST_SEEN_FLOOR_SECS, so this Eq derive is safe for deduping:
    // two sightings within the same floor period compare equal and collapse to one write.
    pub last_seen_at: DateTime<Utc>,
}

// Derived hash since these are keyed on all fields in the DB
#[derive(Clone, Debug, Hash, Eq, PartialEq, PartialOrd, Ord, Deserialize, Serialize)]
pub struct EventProperty {
    #[serde(deserialize_with = "deserialize_string_or_i32")]
    pub team_id: i32,
    #[serde(deserialize_with = "deserialize_string_or_i64")]
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

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Event {
    #[serde(deserialize_with = "deserialize_string_or_i32")]
    pub team_id: i32,
    #[serde(deserialize_with = "deserialize_string_or_i64")]
    pub project_id: i64,
    pub event: String,
    pub properties: Option<String>,
}

impl Event {
    fn to_event_definition(&self, last_seen_floor_secs: i64) -> EventDefinition {
        let name = sanitize_string(&self.event);
        // Seed on the sanitized name because that is what ends up in the dedup key.
        let jitter_seed = last_seen_jitter_seed(self.team_id, &name);

        EventDefinition {
            last_seen_at: floor_last_seen(Utc::now(), last_seen_floor_secs, jitter_seed),
            name,
            team_id: self.team_id,
            project_id: self.project_id,
        }
    }

    pub fn into_updates(self, skip_threshold: usize) -> Vec<Update> {
        self.into_updates_with(skip_threshold, DEFAULT_EVENTDEF_LAST_SEEN_FLOOR_SECS)
    }

    /// As `into_updates`, but with an explicit flooring period for the event-definition dedup
    /// key. See `floor_last_seen` for what the period controls.
    pub fn into_updates_with(
        self,
        skip_threshold: usize,
        last_seen_floor_secs: i64,
    ) -> Vec<Update> {
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

        let updates = self.into_updates_inner(last_seen_floor_secs);
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

    fn into_updates_inner(self, last_seen_floor_secs: i64) -> Vec<Update> {
        let mut updates = vec![Update::Event(
            self.to_event_definition(last_seen_floor_secs),
        )];
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
                let skipped = if parent_type == PropertyParentType::Event {
                    2 // EventProperty + PropertyDefinition
                } else {
                    1 // PropertyDefinition only
                };
                metrics::counter!(
                    UPDATES_SKIPPED,
                    &[("reason", "property_name_wont_fit_in_postgres")]
                )
                .increment(skipped);
                continue;
            }

            // posthog_eventproperty only tracks which properties appear on which events —
            // person, group, and session properties have no meaningful event association
            // and no read path consumes those rows.
            if parent_type == PropertyParentType::Event {
                if SKIP_EVENT_PROPERTY_PREFIXES
                    .iter()
                    .any(|prefix| key.starts_with(prefix))
                {
                    metrics::counter!(
                        UPDATES_SKIPPED,
                        &[("reason", "feature_flag_event_property")]
                    )
                    .increment(1);
                } else {
                    updates.push(Update::EventProperty(EventProperty {
                        team_id: self.team_id,
                        project_id: self.project_id,
                        event: sanitize_string(&self.event),
                        property: sanitize_string(key),
                    }));
                }
            }

            let property_type = detect_property_type(key, value);
            let is_numerical = matches!(property_type, Some(PropertyValueType::Numeric));

            updates.push(Update::Property(PropertyDefinition {
                team_id: self.team_id,
                project_id: self.project_id,
                name: sanitize_string(key),
                is_numerical,
                property_type,
                event_type: parent_type,
                group_type_index: group_type.clone(),
            }));
        }
    }
}

pub fn detect_property_type(key: &str, value: &Value) -> Option<PropertyValueType> {
    // This runs for every property of every event, so the allocation matters. Borrow when the key
    // is already lowercase ASCII, which is effectively all real traffic. The ASCII gate is what
    // makes the borrow equivalent to an unconditional `to_lowercase()`: over ASCII with no
    // uppercase bytes, Unicode lowercasing is the identity, so no case analysis of the patterns
    // below is needed to see that the result is unchanged. Gating on `char::is_uppercase` instead
    // would reach the same answers, but only because every pattern below is an ASCII literal;
    // that argument has to be redone whenever a pattern changes, and it costs a char decode plus
    // a Unicode property lookup per character rather than a byte scan.
    let lowered: Cow<str> = if key.is_ascii() && !key.bytes().any(|b| b.is_ascii_uppercase()) {
        Cow::Borrowed(key)
    } else {
        Cow::Owned(key.to_lowercase())
    };
    let key: &str = &lowered;

    // There are a whole set of special cases here, taken from the TS
    if key.starts_with("utm_") || key.starts_with("$initial_utm_") {
        // utm_ prefixed properties should always be detected as strings.
        // Sometimes the first value sent looks like a number, event though
        // subsequent values are not. See
        // https://github.com/PostHog/posthog/issues/12529 for more context.
        // $initial_utm_* properties are the "initial" variants set by the SDK
        // and must follow the same rule.
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

    if detect_timestamp_property_by_key_and_value(key, value) {
        return Some(PropertyValueType::DateTime);
    }

    // OK, attempt to classify prop type on value alone
    match value {
        Value::String(s) => {
            let s = &s.trim();
            if *s == "true" || *s == "false" || *s == "TRUE" || *s == "FALSE" {
                Some(PropertyValueType::Boolean)
            // Try to parse this as an ISO 8601 date, and if we can, use that as the type instead
            } else if is_likely_date_string(s) {
                Some(PropertyValueType::DateTime)
            } else {
                Some(PropertyValueType::String)
            }
        }

        Value::Number(_) => Some(PropertyValueType::Numeric),

        Value::Bool(_) => Some(PropertyValueType::Boolean),

        _ => None,
    }
}

fn detect_timestamp_property_by_key_and_value(key: &str, value: &Value) -> bool {
    if DATETIME_PROPERTY_NAME_KEYWORDS
        .iter()
        .any(|kw| key.contains(*kw))
    {
        return match value {
            Value::String(s) if is_likely_date_string(s) => true,
            Value::Number(n) if is_likely_unix_timestamp(n) => true,
            _ => false,
        };
    }

    false
}

fn is_likely_date_string(s: &str) -> bool {
    if DateTime::parse_from_rfc3339(s).is_ok() || DateTime::parse_from_rfc2822(s).is_ok() {
        return true;
    }

    if DATETIME_PREFIX_REGEX.is_match(s) {
        return true;
    }

    false
}

// frought with peril if folks are pushing big(ish) numbers into event prop values...
fn is_likely_unix_timestamp(n: &serde_json::Number) -> bool {
    if let Some(value) = n.as_u64() {
        // we could go more conservative here, but you get the idea
        let threshold: u64 = (Utc::now().timestamp_millis() as u64 / 1000u64) - SIX_MONTHS_AGO_SECS;
        if value >= threshold {
            return true;
        }
    }

    false
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

// An event definition's `last_seen_at` participates in its Hash and Eq, so flooring it is what
// bounds how often we re-issue the definition's write: one per (team, name) per period, per pod.
// The value itself never reaches Postgres — the write path binds a fresh Utc::now() per attempt —
// so a coarser period trades a staler stored last_seen_at for proportionally fewer writes.
pub const DEFAULT_EVENTDEF_LAST_SEEN_FLOOR_SECS: i64 = 3600;

// Upper bound on the period, 30 days. Nothing operational wants a window this coarse — the cap
// exists so the jitter offset stays small enough that the bucket arithmetic below cannot overflow
// or leave chrono's representable range, which is what makes its fallback unreachable.
pub const MAX_EVENTDEF_LAST_SEEN_FLOOR_SECS: i64 = 30 * 24 * 3600;

/// Start of the current `period_secs` window containing `now`, offset per identity by
/// `jitter_seed` so that different identities roll over at different points in the period.
///
/// Without the offset every pod rotates every key at the same wall-clock instant, so each rollover
/// makes the entire active keyspace writable at once. That is tolerable hourly and decidedly not
/// at coarser periods, where a day's worth of definition writes would land in the minutes after
/// the boundary, on a table that already struggles to keep autovacuum ahead of its dead tuples.
///
/// The result always falls in `(now - period, now]`, matching un-jittered flooring, so it can
/// never produce a future timestamp.
///
/// The period is clamped into `1..=MAX_EVENTDEF_LAST_SEEN_FLOOR_SECS`, with a non-positive value
/// treated as `DEFAULT_EVENTDEF_LAST_SEEN_FLOOR_SECS`. Both ends of that clamp guard the same
/// failure: an unfloored `last_seen_at` is unique per event, so the dedup cache filters nothing
/// and the full event stream reaches `posthog_eventdefinition` as row updates. A non-positive
/// period would produce that directly; an unbounded one would produce it via the fallback below,
/// since a large enough offset pushes `bucket_start` outside chrono's range. Config validation at
/// startup rejects out-of-range values loudly; this clamp backstops callers that bypass `Config`.
///
/// With the period capped, `offset` stays under a month of seconds, so `shifted` cannot overflow
/// and `bucket_start` stays within a month of `now` — `from_timestamp` therefore cannot fail and
/// the `unwrap_or` never fires.
pub fn floor_last_seen(now: DateTime<Utc>, period_secs: i64, jitter_seed: u64) -> DateTime<Utc> {
    let period_secs = if period_secs > 0 {
        period_secs.min(MAX_EVENTDEF_LAST_SEEN_FLOOR_SECS)
    } else {
        DEFAULT_EVENTDEF_LAST_SEEN_FLOOR_SECS
    };

    let offset = (jitter_seed % period_secs as u64) as i64;
    let shifted = now.timestamp() + offset;
    let bucket_start = shifted.div_euclid(period_secs) * period_secs - offset;

    DateTime::from_timestamp(bucket_start, 0).unwrap_or(now)
}

/// Stable per-identity hash used to spread definition rollovers across the flooring period.
///
/// Hand-rolled FNV-1a rather than a standard library or `ahash` hasher because the offset has to
/// be identical on every pod, across restarts, and across dependency upgrades. `DefaultHasher` and
/// `ahash`'s default state are randomized per process, and any change to the hash shifts every
/// key's boundary at once, which is the synchronized rewrite the offset exists to prevent.
pub fn last_seen_jitter_seed(team_id: i32, name: &str) -> u64 {
    const FNV_OFFSET_BASIS: u64 = 0xcbf2_9ce4_8422_2325;
    const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;

    let mut hash = FNV_OFFSET_BASIS;
    for byte in team_id.to_le_bytes().iter().chain(name.as_bytes()) {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(FNV_PRIME);
    }
    hash
}

// We impose some limits on some fields for legacy reasons, and drop updates that don't conform to them
pub const DJANGO_MAX_CHARFIELD_LENGTH: usize = 400;
fn will_fit_in_postgres_column(str: &str) -> bool {
    str.len() <= DJANGO_MAX_CHARFIELD_LENGTH / 2
}

// Postgres doesn't like nulls in strings, so we replace them with uFFFD.
// This allocates, so only do it right when hitting the DB. We handle nulls
// in strings just fine.
pub fn sanitize_string(s: &str) -> String {
    s.replace('\u{0000}', "\u{FFFD}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn as_unresolved_is_noop_for_unresolved() {
        let gt = GroupType::Unresolved("company".into());
        assert_eq!(gt.as_unresolved(), GroupType::Unresolved("company".into()));
    }

    #[test]
    fn as_unresolved_strips_resolved_index() {
        let gt = GroupType::Resolved("company".into(), 2);
        assert_eq!(gt.as_unresolved(), GroupType::Unresolved("company".into()));
    }
}
