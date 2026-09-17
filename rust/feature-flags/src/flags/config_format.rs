use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::value::RawValue;
use serde_json::Value;
use std::sync::Arc;

use crate::api::errors::FlagError;
use crate::flags::config_v2;
use crate::flags::flag_models::FlagFilters;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ConfigFormat {
    V1,
    V2,
    Unsupported,
}

// Python's cache producer decodes JSON numbers before emitting the service cache.
// Dispatch must use that same binary64 value on the PostgreSQL fallback path.
fn config_format(version: Option<&Value>) -> ConfigFormat {
    match version {
        None => ConfigFormat::V1,
        Some(Value::Number(number)) => match number.as_f64() {
            Some(1.0) => ConfigFormat::V1,
            Some(2.0) => ConfigFormat::V2,
            _ => ConfigFormat::Unsupported,
        },
        Some(_) => ConfigFormat::Unsupported,
    }
}

impl FlagFilters {
    pub(crate) fn is_v1(&self) -> bool {
        self.non_v1.is_none() && config_format(self.extra.get("version")) == ConfigFormat::V1
    }

    pub(crate) fn require_v1(&self) -> Result<(), FlagError> {
        if self.is_v1() {
            Ok(())
        } else {
            Err(FlagError::flag_data_parsing(
                "unsupported feature flag configuration format",
            ))
        }
    }
}

#[cfg(test)]
pub(crate) fn decode_filters(value: Value) -> Result<FlagFilters, serde_json::Error> {
    decode_raw_filters(serde_json::value::to_raw_value(&value)?)
}

pub(crate) fn decode_raw_filters(raw: Box<RawValue>) -> Result<FlagFilters, serde_json::Error> {
    let document = serde_json::from_str::<Value>(raw.get());
    let format = match &document {
        Ok(Value::Object(fields)) => config_format(fields.get("version")),
        Ok(_) => return Err(serde::de::Error::custom("expected a filters object")),
        Err(_) => {
            // An overflowing v2 value must remain a per-flag error, not a wrapper error.
            let fields: std::collections::BTreeMap<String, &RawValue> =
                serde_json::from_str(raw.get())?;
            let version = fields
                .get("version")
                .and_then(|value| serde_json::from_str::<Value>(value.get()).ok());
            if fields.contains_key("version") && version.is_none() {
                ConfigFormat::Unsupported
            } else {
                config_format(version.as_ref())
            }
        }
    };
    if format == ConfigFormat::V1 {
        serde_json::from_value(document?)
    } else {
        let parsed_v2 = (format == ConfigFormat::V2).then(|| {
            config_v2::validate_raw_document(&raw)?;
            let document = document.map_err(|_| config_v2::ParseError::Malformed("filters"))?;
            config_v2::Config::parse(document.as_object().unwrap())
        });
        Ok(FlagFilters {
            non_v1: Some(Arc::new(config_v2::NonV1Config {
                parsed_v2,
                document: raw,
            })),
            ..Default::default()
        })
    }
}

pub(crate) fn deserialize_filters<'de, D>(deserializer: D) -> Result<FlagFilters, D::Error>
where
    D: Deserializer<'de>,
{
    decode_raw_filters(Box::<RawValue>::deserialize(deserializer)?)
        .map_err(serde::de::Error::custom)
}

/// Derived serialization adds v1 fields to opaque documents. Stored JSON must use
/// the retained raw document, or the passthrough map for manually constructed filters.
pub(crate) fn serialize_filters<S>(filters: &FlagFilters, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    if let Some(config) = &filters.non_v1 {
        config.document.serialize(serializer)
    } else if filters.is_v1() {
        filters.serialize(serializer)
    } else {
        filters.extra.serialize(serializer)
    }
}

#[cfg(test)]
mod tests;
