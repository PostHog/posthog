use serde::{Deserialize, Serialize};

/// One event coming from the `team_event_partitioned_events_json` Kafka topic.
/// The `*_properties` fields are JSON-encoded strings on the wire; we parse
/// them lazily during fan-out.
#[derive(Debug, Clone, Deserialize)]
pub struct Event {
    pub team_id: i64,

    #[serde(default)]
    pub created_at: Option<String>,
    #[serde(default)]
    pub timestamp: Option<String>,

    #[serde(default)]
    pub properties: Option<String>,
    #[serde(default)]
    pub person_properties: Option<String>,

    #[serde(default)]
    pub group0_properties: Option<String>,
    #[serde(default)]
    pub group1_properties: Option<String>,
    #[serde(default)]
    pub group2_properties: Option<String>,
    #[serde(default)]
    pub group3_properties: Option<String>,
    #[serde(default)]
    pub group4_properties: Option<String>,
}

/// The shape of one stored property-value tuple. Used both as the hashmap key
/// for in-memory aggregation and (with a `property_count` added) as the
/// outgoing Kafka payload.
#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub struct TupleKey {
    pub team_id: i64,
    pub property_type: PropertyType,
    pub property_key: String,
    pub property_value: String,
}

/// Property type that the storage table partitions on. The string forms map
/// 1:1 to the values written into `posthog.property_values.property_type`.
#[derive(Debug, Clone, Copy, Hash, Eq, PartialEq)]
pub enum PropertyType {
    Event,
    Person,
    Group0,
    Group1,
    Group2,
    Group3,
    Group4,
}

impl PropertyType {
    pub fn as_str(&self) -> &'static str {
        match self {
            PropertyType::Event => "event",
            PropertyType::Person => "person",
            PropertyType::Group0 => "group_0",
            PropertyType::Group1 => "group_1",
            PropertyType::Group2 => "group_2",
            PropertyType::Group3 => "group_3",
            PropertyType::Group4 => "group_4",
        }
    }
}

/// One outgoing message produced to `clickhouse_property_values` per unique
/// tuple per flush window. The CH Kafka engine table parses this as JSONEachRow.
#[derive(Debug, Clone, Serialize)]
pub struct OutputMessage<'a> {
    pub team_id: i64,
    pub property_type: &'a str,
    pub property_key: &'a str,
    pub property_value: &'a str,
    pub property_count: u64,
}
