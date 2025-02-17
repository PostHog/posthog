use serde::{Deserialize, Deserializer};
use uuid::Uuid;

pub fn empty_string_is_none<'de, D>(deserializer: D) -> Result<Option<Uuid>, D::Error>
where
    D: Deserializer<'de>,
{
    let opt = Option::<String>::deserialize(deserializer)?;
    match opt {
        None => Ok(None),
        Some(s) if s.is_empty() => Ok(None),
        Some(s) => Uuid::parse_str(&s)
            .map(Some)
            .map_err(serde::de::Error::custom),
    }
}
