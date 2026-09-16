use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::Value;

use crate::api::errors::FlagError;
use crate::flags::flag_models::FlagFilters;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ConfigFormat {
    V1,
    V2,
    Unsupported,
}

impl ConfigFormat {
    fn from_version(version: Option<&Value>) -> Self {
        match version {
            None => Self::V1,
            Some(Value::Number(number)) => match number.as_f64() {
                Some(1.0) => Self::V1,
                Some(2.0) => Self::V2,
                _ => Self::Unsupported,
            },
            Some(_) => Self::Unsupported,
        }
    }
}

impl FlagFilters {
    pub(crate) fn config_format(&self) -> ConfigFormat {
        ConfigFormat::from_version(self.extra.get("version"))
    }

    pub(crate) fn is_v1(&self) -> bool {
        self.config_format() == ConfigFormat::V1
    }

    pub(crate) fn require_v1(&self) -> Result<(), FlagError> {
        match self.config_format() {
            ConfigFormat::V1 => Ok(()),
            ConfigFormat::V2 | ConfigFormat::Unsupported => Err(FlagError::flag_data_parsing(
                "unsupported feature flag configuration format",
            )),
        }
    }
}

pub(crate) fn decode_filters(value: Value) -> Result<FlagFilters, serde_json::Error> {
    // An object is required even when the discriminator is absent.
    let Value::Object(document) = value else {
        return Err(serde::de::Error::custom("expected a filters object"));
    };
    match ConfigFormat::from_version(document.get("version")) {
        ConfigFormat::V1 => serde_json::from_value(Value::Object(document)),
        ConfigFormat::V2 | ConfigFormat::Unsupported => Ok(FlagFilters {
            // Keep the document opaque: v1-looking fields may have unrelated types.
            // The passthrough map also accounts for these bytes in the prepared cache.
            extra: document,
            ..Default::default()
        }),
    }
}

pub(crate) fn deserialize_filters<'de, D>(deserializer: D) -> Result<FlagFilters, D::Error>
where
    D: Deserializer<'de>,
{
    decode_filters(Value::deserialize(deserializer)?).map_err(serde::de::Error::custom)
}

pub(crate) fn serialize_filters<S>(filters: &FlagFilters, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    match filters.config_format() {
        ConfigFormat::V1 => filters.serialize(serializer),
        ConfigFormat::V2 | ConfigFormat::Unsupported => filters.extra.serialize(serializer),
    }
}

#[cfg(test)]
mod tests;
