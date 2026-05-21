use serde::ser::{Serialize, Serializer};

pub trait IngestableEvent: serde::de::DeserializeOwned + Send + Sync + 'static {
    fn team_id(&self) -> i64;
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

#[derive(Debug, Clone, Copy, Hash, Eq, PartialEq)]
pub enum PropertyType {
    Event,
    Person,
    Group(u8),
}

impl Serialize for PropertyType {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            PropertyType::Event => serializer.serialize_str("event"),
            PropertyType::Person => serializer.serialize_str("person"),
            PropertyType::Group(n) => serializer.serialize_str(&format!("group_{n}")),
        }
    }
}
