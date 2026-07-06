use serde::de::{self, Deserialize, Deserializer};
use serde::ser::{Serialize, Serializer};

pub trait IngestableEvent: serde::de::DeserializeOwned + Send + Sync + 'static {
    fn team_id(&self) -> i64;

    fn decode(payload: &[u8]) -> Result<Self, serde_json::Error> {
        serde_json::from_slice(payload)
    }
}

#[derive(Debug, Clone, serde::Deserialize)]
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

#[derive(Debug, Clone, serde::Deserialize)]
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

#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub struct TupleKey {
    pub team_id: i64,
    pub property_type: PropertyType,
    pub property_key: String,
    pub property_value: String,
}

impl TupleKey {
    pub fn approx_bytes(&self) -> usize {
        std::mem::size_of::<Self>() + self.property_key.len() + self.property_value.len()
    }
}

#[derive(Debug, Clone, Copy, Hash, Eq, PartialEq)]
pub enum PropertyType {
    Event,
    Person,
    Group(u8),
}

impl PropertyType {
    pub fn as_kafka_key_segment(&self) -> String {
        match self {
            PropertyType::Event => "event".to_string(),
            PropertyType::Person => "person".to_string(),
            PropertyType::Group(n) => format!("group_{n}"),
        }
    }
}

impl Serialize for PropertyType {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.as_kafka_key_segment())
    }
}

impl<'de> Deserialize<'de> for PropertyType {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let s: &str = Deserialize::deserialize(deserializer)?;
        match s {
            "event" => Ok(PropertyType::Event),
            "person" => Ok(PropertyType::Person),
            other => {
                let n: u8 = other
                    .strip_prefix("group_")
                    .ok_or_else(|| de::Error::custom(format!("invalid property_type: {other}")))?
                    .parse()
                    .map_err(|_| {
                        de::Error::custom(format!("invalid group property_type: {other}"))
                    })?;
                Ok(PropertyType::Group(n))
            }
        }
    }
}

/// Wire format of records on the intermediate topic. Mirrors `Outgoing` in
/// `producer.rs` so a stage-1 produce round-trips to a stage-2 consume.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct PropertyValueMessage {
    pub team_id: i64,
    pub property_type: PropertyType,
    pub property_key: String,
    pub property_value: String,
    pub property_count: u64,
}

impl IngestableEvent for PropertyValueMessage {
    fn team_id(&self) -> i64 {
        self.team_id
    }

    // Intermediate-topic records may be compact binary (magic-prefixed) or
    // JSON, depending on the producer's configured wire format.
    fn decode(payload: &[u8]) -> Result<Self, serde_json::Error> {
        if payload.starts_with(&crate::wire::MAGIC) {
            return crate::wire::decode(payload).map_err(de::Error::custom);
        }
        serde_json::from_slice(payload)
    }
}
