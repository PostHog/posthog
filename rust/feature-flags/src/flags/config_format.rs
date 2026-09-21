use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::value::RawValue;
use serde_json::{Map, Value};
use std::sync::Arc;

use crate::api::errors::FlagError;
use crate::flags::config_v2;
use crate::flags::flag_models::FlagFilters;
use crate::metrics::consts::FLAG_V2_PARSE_COUNTER;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ConfigFormat {
    V1,
    V2,
    Unsupported,
}

impl ConfigFormat {
    fn from_number(number: Option<f64>) -> Self {
        match number {
            Some(1.0) => Self::V1,
            Some(2.0) => Self::V2,
            _ => Self::Unsupported,
        }
    }
}

fn config_format(version: Option<&Value>) -> ConfigFormat {
    version.map_or(ConfigFormat::V1, |value| {
        ConfigFormat::from_number(value.as_f64())
    })
}

struct FilterDocument<const BUILD_DOCUMENT: bool> {
    format: ConfigFormat,
    document: Map<String, Value>,
}

impl<'de, const BUILD_DOCUMENT: bool> Deserialize<'de> for FilterDocument<BUILD_DOCUMENT> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct DocumentVisitor<const BUILD_DOCUMENT: bool>;
        impl<'de, const BUILD_DOCUMENT: bool> serde::de::Visitor<'de> for DocumentVisitor<BUILD_DOCUMENT> {
            type Value = FilterDocument<BUILD_DOCUMENT>;

            fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                formatter.write_str("a filters object")
            }

            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut map: A,
            ) -> Result<Self::Value, A::Error> {
                let mut format = ConfigFormat::V1;
                let mut document = Map::new();
                while let Some(key) = map.next_key::<String>()? {
                    if key == "version" {
                        let raw: &RawValue = map.next_value()?;
                        // Python rounds JSON numbers correctly; serde's default Value
                        // parser can round a nearby non-1 discriminator to 1 instead.
                        format = ConfigFormat::from_number(raw.get().parse::<f64>().ok());
                        if BUILD_DOCUMENT {
                            let mut version =
                                serde_json::from_str(raw.get()).unwrap_or(Value::Null);
                            // Keep is_v1's Value-based check consistent with raw-token
                            // dispatch. serialize_filters also writes this normalized
                            // discriminator back to the cache.
                            if format == ConfigFormat::V1 && version.as_f64() != Some(1.0) {
                                version = serde_json::json!(1.0);
                            }
                            document.insert(key, version);
                        }
                    } else if BUILD_DOCUMENT {
                        document.insert(key, map.next_value()?);
                    } else {
                        map.next_value::<serde::de::IgnoredAny>()?;
                    }
                }
                Ok(FilterDocument { format, document })
            }
        }
        // Require an object: derived Deserialize also accepts positional arrays
        // and would interpret [2] as a non-v1 document with version 2.
        deserializer.deserialize_map(DocumentVisitor::<BUILD_DOCUMENT>)
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
    let (format, document) = match serde_json::from_str::<FilterDocument<true>>(raw.get()) {
        Ok(decoded) => (decoded.format, Ok(decoded.document)),
        Err(error) => {
            // An unrepresentable number must stay a per-flag v2 failure. Only
            // failed Value reads need another scan to recover the discriminator.
            let probe = serde_json::from_str::<FilterDocument<false>>(raw.get())?;
            (probe.format, Err(error))
        }
    };
    if format == ConfigFormat::V1 {
        serde_json::from_value(Value::Object(document?))
    } else {
        let parsed_v2 = (format == ConfigFormat::V2).then(|| {
            config_v2::validate_raw_document(&raw)?;
            let document = document.map_err(|_| config_v2::ParseError::Malformed("filters"))?;
            config_v2::Config::parse(&document)
        });
        if let Some(parsed) = &parsed_v2 {
            let outcome = match parsed {
                Ok(_) => "success",
                Err(config_v2::ParseError::Malformed(_)) => "malformed",
                Err(config_v2::ParseError::Unsupported(_)) => "unsupported",
                Err(config_v2::ParseError::LimitExceeded(_)) => "limit_exceeded",
            };
            metrics::counter!(FLAG_V2_PARSE_COUNTER, "outcome" => outcome).increment(1);
        }
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
