use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::value::RawValue;
use serde_json::Value;
use std::sync::Arc;

use crate::api::errors::FlagError;
use crate::flags::config_v2;
use crate::flags::flag_models::{FeatureFlagRow, FlagFilters};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ConfigFormat {
    V1,
    V2,
    Unsupported,
}

/// Mirrors Python's `detect_config_format` (products/feature_flags/backend/facade/config.py).
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
        self.non_v1.is_none() && is_v1_version(self.extra.get("version"))
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
    // An object is required even when the discriminator is absent.
    let fields: std::collections::BTreeMap<String, &RawValue> = serde_json::from_str(raw.get())
        .map_err(|_| {
            <serde_json::Error as serde::de::Error>::custom("expected a filters object")
        })?;
    let format = match fields.get("version") {
        None => ConfigFormat::V1,
        Some(version) if config_v2::classify_number(version.get(), 1.0) => ConfigFormat::V1,
        Some(version) if config_v2::classify_number(version.get(), 2.0) => ConfigFormat::V2,
        Some(_) => ConfigFormat::Unsupported,
    };
    if format == ConfigFormat::V1 {
        // Keep the existing Value-to-v1 decode, including its numeric behavior.
        serde_json::from_value(serde_json::from_str::<Value>(raw.get())?)
    } else {
        let parsed_v2 = if format == ConfigFormat::V2 {
            Some(
                serde_json::from_str(raw.get())
                    .map_err(|_| config_v2::ParseError::Malformed("filters"))
                    .and_then(|document| config_v2::Config::parse(&document))
                    .and_then(|config| config_v2::validate_raw_percentages(&raw).map(|()| config)),
            )
        } else {
            None
        };
        Ok(FlagFilters {
            non_v1: Some(Arc::new(config_v2::NonV1Config {
                parsed_v2,
                document: raw,
            })),
            ..Default::default()
        })
    }
}

impl std::fmt::Debug for FlagFilters {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if !self.is_v1() {
            // Opaque documents can carry seeds and arbitrary property/metadata values.
            return f
                .debug_struct("FlagFilters")
                .field("non_v1", &self.non_v1)
                .finish_non_exhaustive();
        }
        f.debug_struct("FlagFilters")
            .field("groups", &self.groups)
            .field("multivariate", &self.multivariate)
            .field(
                "aggregation_group_type_index",
                &self.aggregation_group_type_index,
            )
            .field("payloads", &self.payloads)
            .field("feature_enrollment", &self.feature_enrollment)
            .field("holdout", &self.holdout)
            .field("early_exit", &self.early_exit)
            .field("extra", &self.extra)
            .finish()
    }
}

impl<F> std::fmt::Debug for FeatureFlagRow<F> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FeatureFlagRow")
            .field("id", &self.id)
            .field("team_id", &self.team_id)
            .finish_non_exhaustive()
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
