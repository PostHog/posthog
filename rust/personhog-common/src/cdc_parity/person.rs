//! Person rows, the `clickhouse_person` shape both the Node Postgres path and
//! the changelog relay produce: folded to the newest version per person, as
//! a ReplacingMergeTree keeps it, and compared by content.

use std::borrow::Cow;
use std::collections::hash_map::DefaultHasher;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::hash::Hasher;

use serde::Deserialize;
use serde_json::{Map, Value};
use uuid::Uuid;

use super::decode::{parse_uuid, DecodeError};
use super::feed::PersonKey;

const PERSON_ROW: &str = "person row";

#[derive(Debug, Clone, PartialEq)]
pub struct PersonRow {
    pub team_id: i64,
    pub uuid: Uuid,
    pub version: i64,
    pub is_deleted: bool,
    pub is_identified: bool,
    /// ClickHouse's second precision text, the same on both feeds.
    pub created_at: String,
    pub properties: Map<String, Value>,
}

impl PersonRow {
    /// `properties` is a JSON document inside the JSON row.
    pub fn decode(payload: &[u8]) -> Result<Self, DecodeError> {
        let value: Value = serde_json::from_slice(payload).map_err(|source| DecodeError::Json {
            what: PERSON_ROW,
            source,
        })?;
        let missing = |field: &'static str| DecodeError::MissingField {
            what: PERSON_ROW,
            field,
        };
        let flag = |field: &'static str| match value[field].as_u64() {
            Some(0) => Ok(false),
            Some(1) => Ok(true),
            _ => Err(DecodeError::PersonFlag {
                field,
                value: value[field].clone(),
            }),
        };
        let properties = value["properties"]
            .as_str()
            .ok_or_else(|| missing("a properties string"))?;
        let properties = match serde_json::from_str(properties) {
            Ok(Value::Object(properties)) => properties,
            _ => return Err(DecodeError::Properties),
        };
        Ok(Self {
            team_id: value["team_id"]
                .as_i64()
                .ok_or_else(|| missing("an integer team_id"))?,
            uuid: parse_uuid(&value["id"]).ok_or_else(|| missing("a person uuid"))?,
            version: value["version"]
                .as_i64()
                .ok_or_else(|| missing("an integer version"))?,
            is_deleted: flag("is_deleted")?,
            is_identified: flag("is_identified")?,
            created_at: value["created_at"]
                .as_str()
                .ok_or_else(|| missing("a created_at"))?
                .to_string(),
            properties,
        })
    }

    /// Reads the key alone. The properties document stays an unparsed
    /// string, so a row outside a sample costs a fraction of `decode`.
    pub fn decode_key(payload: &[u8]) -> Result<PersonKey, DecodeError> {
        let fields: KeyFields<'_> =
            serde_json::from_slice(payload).map_err(|source| DecodeError::Json {
                what: PERSON_ROW,
                source,
            })?;
        let uuid = Uuid::parse_str(&fields.id).map_err(|_| DecodeError::MissingField {
            what: PERSON_ROW,
            field: "a person uuid",
        })?;
        Ok(PersonKey::new(fields.team_id, uuid))
    }

    pub fn key(&self) -> PersonKey {
        PersonKey::new(self.team_id, self.uuid)
    }
}

#[derive(Deserialize)]
struct KeyFields<'a> {
    team_id: i64,
    #[serde(borrow)]
    id: Cow<'a, str>,
}

/// What a feed holds for one person. Properties are kept as a hash per top
/// level key, so a held row costs little and a mismatch can still name the
/// keys that differ. The version only orders rows; it counts writes, which
/// the two backends batch differently, so it is never compared across feeds.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PersonSnapshot {
    pub version: i64,
    pub is_deleted: bool,
    pub is_identified: bool,
    pub created_at: String,
    pub properties: BTreeMap<String, u64>,
}

impl PersonSnapshot {
    pub fn new(row: &PersonRow, ignored: &HashSet<String>) -> Self {
        Self {
            version: row.version,
            is_deleted: row.is_deleted,
            is_identified: row.is_identified,
            created_at: row.created_at.clone(),
            properties: row
                .properties
                .iter()
                .filter(|(key, _)| !ignored.contains(*key))
                .map(|(key, value)| (key.clone(), value_hash(value)))
                .collect(),
        }
    }

    pub fn differing_keys<'a>(&'a self, other: &'a PersonSnapshot) -> Vec<&'a str> {
        let mut keys: Vec<&str> = self
            .properties
            .keys()
            .chain(other.properties.keys())
            .filter(|key| self.properties.get(*key) != other.properties.get(*key))
            .map(String::as_str)
            .collect();
        keys.sort_unstable();
        keys.dedup();
        keys
    }
}

/// Key order never counts. Numbers count by their f64 value: Node writes
/// properties through JavaScript, which reads `1.0` as `1` and rounds
/// integers past 2^53, so only what both sides can express is compared.
fn value_hash(value: &Value) -> u64 {
    fn write(hasher: &mut DefaultHasher, value: &Value) {
        match value {
            Value::Null => hasher.write_u8(0),
            Value::Bool(b) => {
                hasher.write_u8(1);
                hasher.write_u8(u8::from(*b));
            }
            Value::Number(n) => {
                hasher.write_u8(2);
                let n = n.as_f64().unwrap_or(f64::NAN);
                // -0 and 0 print the same in JavaScript.
                hasher.write_u64(if n == 0.0 { 0 } else { n.to_bits() });
            }
            Value::String(s) => {
                hasher.write_u8(3);
                hasher.write(s.as_bytes());
                hasher.write_u8(0xff);
            }
            Value::Array(items) => {
                hasher.write_u8(4);
                hasher.write_usize(items.len());
                for item in items {
                    write(hasher, item);
                }
            }
            Value::Object(map) => {
                hasher.write_u8(5);
                hasher.write_usize(map.len());
                let mut keys: Vec<&String> = map.keys().collect();
                keys.sort_unstable();
                for key in keys {
                    hasher.write(key.as_bytes());
                    hasher.write_u8(0xff);
                    write(hasher, &map[key]);
                }
            }
        }
    }
    let mut hasher = DefaultHasher::new();
    write(&mut hasher, value);
    hasher.finish()
}

/// A deletion difference outranks a content difference; properties outrank
/// the flags.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PersonOutcome {
    Agree,
    DeletedMismatch,
    PropertiesMismatch,
    IdentifiedMismatch,
    CreatedAtMismatch,
    NodeOnly,
    PersonhogOnly,
}

impl PersonOutcome {
    pub fn label(self) -> &'static str {
        match self {
            PersonOutcome::Agree => "agree",
            PersonOutcome::DeletedMismatch => "deleted_mismatch",
            PersonOutcome::PropertiesMismatch => "properties_mismatch",
            PersonOutcome::IdentifiedMismatch => "identified_mismatch",
            PersonOutcome::CreatedAtMismatch => "created_at_mismatch",
            PersonOutcome::NodeOnly => "node_only",
            PersonOutcome::PersonhogOnly => "personhog_only",
        }
    }
}

/// Two deleted persons agree whatever else their rows carry: each backend
/// writes its own death row, and both empty the properties.
pub fn compare_person(
    node: Option<&PersonSnapshot>,
    personhog: Option<&PersonSnapshot>,
) -> PersonOutcome {
    match (node, personhog) {
        (None, None) => PersonOutcome::Agree,
        (Some(_), None) => PersonOutcome::NodeOnly,
        (None, Some(_)) => PersonOutcome::PersonhogOnly,
        (Some(node), Some(personhog)) => {
            if node.is_deleted != personhog.is_deleted {
                PersonOutcome::DeletedMismatch
            } else if node.is_deleted {
                PersonOutcome::Agree
            } else if node.properties != personhog.properties {
                PersonOutcome::PropertiesMismatch
            } else if node.is_identified != personhog.is_identified {
                PersonOutcome::IdentifiedMismatch
            } else if node.created_at != personhog.created_at {
                PersonOutcome::CreatedAtMismatch
            } else {
                PersonOutcome::Agree
            }
        }
    }
}

#[derive(Debug, Default)]
pub struct PersonFeed {
    latest: HashMap<PersonKey, PersonSnapshot>,
}

impl PersonFeed {
    /// Keeps the newest version, the first arrival among equal ones. True
    /// when a different row arrives at the version held: the feed
    /// contradicting itself.
    pub fn observe(&mut self, row: &PersonRow, ignored: &HashSet<String>) -> bool {
        let snapshot = PersonSnapshot::new(row, ignored);
        match self.latest.get_mut(&row.key()) {
            Some(held) if held.version > snapshot.version => false,
            Some(held) if held.version == snapshot.version => *held != snapshot,
            Some(held) => {
                *held = snapshot;
                false
            }
            None => {
                self.latest.insert(row.key(), snapshot);
                false
            }
        }
    }

    pub fn get(&self, key: &PersonKey) -> Option<&PersonSnapshot> {
        self.latest.get(key)
    }

    pub fn remove(&mut self, key: &PersonKey) {
        self.latest.remove(key);
    }

    pub fn len(&self) -> usize {
        self.latest.len()
    }

    pub fn is_empty(&self) -> bool {
        self.latest.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const UUID: &str = "00000000-0000-0000-0000-000000000001";

    fn payload(properties: &str, extra: &str) -> String {
        format!(
            r#"{{"id":"{UUID}","created_at":"2023-11-14 22:13:20","properties":{properties},"team_id":5,"is_identified":1,"is_deleted":0,"version":3,"last_seen_at":null{extra}}}"#,
            properties = serde_json::to_string(properties).unwrap(),
        )
    }

    fn row(properties: &str, extra: &str) -> PersonRow {
        PersonRow::decode(payload(properties, extra).as_bytes()).unwrap()
    }

    fn snapshot(properties: &str) -> PersonSnapshot {
        PersonSnapshot::new(&row(properties, ""), &HashSet::new())
    }

    #[test]
    fn a_node_shaped_row_decodes() {
        let row = row(r#"{"email":"a@example.com"}"#, "");
        assert_eq!(row.key(), PersonKey::new(5, Uuid::parse_str(UUID).unwrap()));
        let payload = payload(r#"{"email":"a@example.com"}"#, "");
        assert_eq!(
            PersonRow::decode_key(payload.as_bytes()).unwrap(),
            row.key()
        );
        assert_eq!(row.version, 3);
        assert!(row.is_identified && !row.is_deleted);
        assert_eq!(row.created_at, "2023-11-14 22:13:20");
        assert_eq!(row.properties["email"], "a@example.com");
    }

    #[test]
    fn rows_a_consumer_would_misread_do_not_decode() {
        let cases = [
            (
                "properties not an object",
                r#"{"id":"00000000-0000-0000-0000-000000000001","created_at":"x","properties":"[1]","team_id":5,"is_identified":1,"is_deleted":0,"version":3}"#,
            ),
            (
                "is_deleted out of range",
                r#"{"id":"00000000-0000-0000-0000-000000000001","created_at":"x","properties":"{}","team_id":5,"is_identified":1,"is_deleted":2,"version":3}"#,
            ),
            (
                "no uuid",
                r#"{"id":"nope","created_at":"x","properties":"{}","team_id":5,"is_identified":1,"is_deleted":0,"version":3}"#,
            ),
        ];
        for (name, payload) in cases {
            assert!(PersonRow::decode(payload.as_bytes()).is_err(), "{name}");
        }
    }

    #[test]
    fn properties_compare_by_what_both_backends_can_express() {
        let cases = [
            (
                "key order",
                r#"{"a":1,"b":{"x":1,"y":2}}"#,
                r#"{"b":{"y":2,"x":1},"a":1}"#,
                true,
            ),
            ("1 against 1.0", r#"{"a":1}"#, r#"{"a":1.0}"#, true),
            (
                "past 2^53",
                r#"{"a":12345678901234567890}"#,
                r#"{"a":12345678901234567000}"#,
                true,
            ),
            ("different values", r#"{"a":1}"#, r#"{"a":2}"#, false),
            (
                "a string against a number",
                r#"{"a":"1"}"#,
                r#"{"a":1}"#,
                false,
            ),
            ("a missing key", r#"{"a":1}"#, r#"{"a":1,"b":null}"#, false),
        ];
        for (name, left, right, equal) in cases {
            assert_eq!(snapshot(left) == snapshot(right), equal, "{name}");
        }
    }

    #[test]
    fn person_comparison_decision_table() {
        let live = snapshot(r#"{"a":1}"#);
        let other_props = snapshot(r#"{"a":2}"#);
        let anonymous = PersonSnapshot {
            is_identified: false,
            ..live.clone()
        };
        let later_created = PersonSnapshot {
            created_at: "2023-11-14 22:13:21".to_string(),
            ..live.clone()
        };
        let deleted = PersonSnapshot {
            is_deleted: true,
            properties: BTreeMap::new(),
            ..live.clone()
        };
        let deleted_elsewhere = PersonSnapshot {
            is_identified: false,
            version: 9,
            ..deleted.clone()
        };
        let cases = [
            ("both absent", None, None, PersonOutcome::Agree),
            (
                "same content, other versions",
                Some(&live),
                Some(&PersonSnapshot {
                    version: 7,
                    ..live.clone()
                }),
                PersonOutcome::Agree,
            ),
            ("node only", Some(&live), None, PersonOutcome::NodeOnly),
            (
                "personhog only",
                None,
                Some(&live),
                PersonOutcome::PersonhogOnly,
            ),
            (
                "one deleted",
                Some(&live),
                Some(&deleted),
                PersonOutcome::DeletedMismatch,
            ),
            (
                "both deleted, other flags",
                Some(&deleted),
                Some(&deleted_elsewhere),
                PersonOutcome::Agree,
            ),
            (
                "properties",
                Some(&live),
                Some(&other_props),
                PersonOutcome::PropertiesMismatch,
            ),
            (
                "is_identified",
                Some(&live),
                Some(&anonymous),
                PersonOutcome::IdentifiedMismatch,
            ),
            (
                "created_at",
                Some(&live),
                Some(&later_created),
                PersonOutcome::CreatedAtMismatch,
            ),
        ];
        for (name, node, personhog, outcome) in cases {
            assert_eq!(compare_person(node, personhog), outcome, "{name}");
        }
    }

    #[test]
    fn ignored_keys_never_count_and_differing_keys_name_the_rest() {
        let ignored = HashSet::from(["$creator_event_uuid".to_string()]);
        let node = PersonSnapshot::new(
            &row(r#"{"$creator_event_uuid":"x","a":1,"b":1}"#, ""),
            &ignored,
        );
        let personhog = PersonSnapshot::new(
            &row(r#"{"$creator_event_uuid":"y","a":1,"c":1}"#, ""),
            &ignored,
        );
        assert_eq!(node.differing_keys(&personhog), vec!["b", "c"]);
    }

    #[test]
    fn a_feed_keeps_the_newest_row_and_flags_a_contradiction_at_one_version() {
        let mut feed = PersonFeed::default();
        let none = HashSet::new();
        let v3 = row(r#"{"a":1}"#, "");
        let v4 = PersonRow {
            version: 4,
            properties: row(r#"{"a":2}"#, "").properties,
            ..v3.clone()
        };
        let v3_other = PersonRow {
            properties: row(r#"{"a":3}"#, "").properties,
            ..v3.clone()
        };
        assert!(!feed.observe(&v3, &none));
        assert!(!feed.observe(&v4, &none));
        assert!(!feed.observe(&v3_other, &none));
        assert_eq!(feed.get(&v3.key()).unwrap().version, 4);
        assert!(feed.observe(
            &PersonRow {
                version: 4,
                ..v3_other
            },
            &none
        ));
    }
}
