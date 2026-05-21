use serde::{Deserialize, Serialize};

/// Abstracts the fields the worker needs from any consumed message. Lets
/// `worker_loop` be generic over event-shaped inputs (`Event`) and group
/// identify-shaped inputs (`GroupIdentify`) without duplicating the loop.
pub trait IngestableEvent: serde::de::DeserializeOwned + Send + Sync + 'static {
    fn team_id(&self) -> i64;
}

/// One event coming from the `team_event_partitioned_events_json` Kafka topic.
/// The `*_properties` fields are JSON-encoded strings on the wire; we parse
/// them lazily during fan-out.
#[derive(Debug, Clone, Deserialize)]
pub struct Event {
    pub team_id: i64,

    #[serde(default)]
    pub properties: Option<String>,
    #[serde(default)]
    pub person_properties: Option<String>,
}

impl IngestableEvent for Event {
    fn team_id(&self) -> i64 {
        self.team_id
    }
}

/// One message coming from the `clickhouse_groups` Kafka topic, produced by
/// the plugin server every time `$groupidentify` fires. Carries the entire
/// group properties blob for one (team, type, key) combination.
///
/// Because group properties are never denormalized onto the events stream,
/// this topic is the only source of group property values for autocomplete.
#[derive(Debug, Clone, Deserialize)]
pub struct GroupIdentify {
    pub team_id: i64,
    pub group_type_index: u8,
    #[serde(default)]
    pub group_properties: Option<String>,
}

impl IngestableEvent for GroupIdentify {
    fn team_id(&self) -> i64 {
        self.team_id
    }
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
/// Owned so the producer helper can take it by value into rdkafka.
#[derive(Debug, Clone, Serialize)]
pub struct OutputMessage {
    pub team_id: i64,
    pub property_type: String,
    pub property_key: String,
    pub property_value: String,
    pub property_count: u64,
}
