use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::Value;

use crate::api::errors::FlagError;
use crate::flags::flag_models::FlagFilters;

/// Mirrors Python's `detect_config_format` (products/feature_flags/backend/facade/config.py):
/// an absent discriminator or numeric 1 selects v1, everything else (including 2) is a
/// format this service does not evaluate.
fn is_v1_version(version: Option<&Value>) -> bool {
    match version {
        None => true,
        // JSON booleans are not `Value::Number`, so `true` cannot read as 1 here.
        Some(Value::Number(number)) => number.as_f64() == Some(1.0),
        Some(_) => false,
    }
}

impl FlagFilters {
    pub(crate) fn is_v1(&self) -> bool {
        is_v1_version(self.extra.get("version"))
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

pub(crate) fn decode_filters(value: Value) -> Result<FlagFilters, serde_json::Error> {
    // An object is required even when the discriminator is absent.
    let Value::Object(document) = value else {
        return Err(serde::de::Error::custom("expected a filters object"));
    };
    if is_v1_version(document.get("version")) {
        serde_json::from_value(Value::Object(document))
    } else {
        Ok(FlagFilters {
            // Keep the document opaque: v1-looking fields may have unrelated types.
            // The passthrough map also accounts for these bytes in the prepared cache.
            extra: document,
            ..Default::default()
        })
    }
}

pub(crate) fn deserialize_filters<'de, D>(deserializer: D) -> Result<FlagFilters, D::Error>
where
    D: Deserializer<'de>,
{
    decode_filters(Value::deserialize(deserializer)?).map_err(serde::de::Error::custom)
}

/// The single place a `FlagFilters` turns back into stored JSON: the derived `Serialize`
/// impl flattens `extra`, which for an opaque non-v1 document would emit the typed fields
/// twice. Serialize through here, not through the struct.
pub(crate) fn serialize_filters<S>(filters: &FlagFilters, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    if filters.is_v1() {
        filters.serialize(serializer)
    } else {
        filters.extra.serialize(serializer)
    }
}

#[cfg(test)]
mod tests;
