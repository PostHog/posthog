//! Types related to HTTP payload handling

use serde::{Deserialize, Deserializer};
use time::OffsetDateTime;
use tracing::debug;

#[derive(Default, Clone, Copy, PartialEq, Eq, Debug)]
pub enum Compression {
    #[default]
    Unsupported,
    Gzip,
    LZString,
    Base64,
}

// implement Deserialize directly on the enum so
// Axum form and URL query parsing don't fail upstream
// of handler code
impl<'de> Deserialize<'de> for Compression {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value =
            String::deserialize(deserializer).unwrap_or("deserialization_error".to_string());

        let result = match value.to_lowercase().as_str() {
            "gzip" | "gzip-js" => Compression::Gzip,
            "lz64" | "lz-string" => Compression::LZString,
            "base64" | "b64" => Compression::Base64,
            "deserialization_error" => {
                debug!("compression value did not deserialize");
                Compression::Unsupported
            }
            _ => {
                debug!("unsupported compression value: {}", value);
                Compression::Unsupported
            }
        };

        Ok(result)
    }
}

impl std::fmt::Display for Compression {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Compression::Gzip => write!(f, "gzip"),
            Compression::LZString => write!(f, "lz64"),
            Compression::Base64 => write!(f, "base64"),
            Compression::Unsupported => write!(f, "unsupported"),
        }
    }
}

#[derive(Deserialize, Default)]
pub struct EventQuery {
    pub compression: Option<Compression>,

    // legacy GET requests can include data as query param
    pub data: Option<String>,

    #[serde(alias = "ver")]
    pub lib_version: Option<String>,

    #[serde(alias = "_")]
    pub sent_at: Option<i64>,

    // If true, return 204 No Content on success
    #[serde(default, deserialize_with = "deserialize_beacon")]
    pub beacon: bool,
}

fn deserialize_beacon<'de, D>(deserializer: D) -> Result<bool, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value: Option<i32> = Option::deserialize(deserializer)?;
    let result = value.is_some_and(|v| v == 1);
    Ok(result)
}

impl EventQuery {
    /// Returns the parsed value of the sent_at timestamp if present in the query params.
    /// We only support the format sent by recent posthog-js versions, in milliseconds integer.
    /// Values in seconds integer (older SDKs) will be ignored.
    pub fn sent_at(&self) -> Option<OffsetDateTime> {
        if let Some(value) = self.sent_at {
            let value_nanos: i128 = i128::from(value) * 1_000_000; // Assuming the value is in milliseconds, latest posthog-js releases
            if let Ok(sent_at) = OffsetDateTime::from_unix_timestamp_nanos(value_nanos) {
                if sent_at.year() > 2020 {
                    // Could be lower if the input is in seconds
                    return Some(sent_at);
                }
            }
        }
        None
    }
}

// Some SDKs like posthog-js-lite can include metadata in the POST body
#[derive(Deserialize, Default)]
pub struct EventFormData {
    pub data: Option<String>,
    pub compression: Option<Compression>,
    #[serde(alias = "ver")]
    pub lib_version: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compression_deserialization_gzip() {
        let json = r#""gzip""#;
        let compression: Compression = serde_json::from_str(json).unwrap();
        assert_eq!(compression, Compression::Gzip);

        let json = r#""gzip-js""#;
        let compression: Compression = serde_json::from_str(json).unwrap();
        assert_eq!(compression, Compression::Gzip);
    }

    #[test]
    fn test_compression_deserialization_lz64() {
        let json = r#""lz64""#;
        let compression: Compression = serde_json::from_str(json).unwrap();
        assert_eq!(compression, Compression::LZString);

        let json = r#""lz-string""#;
        let compression: Compression = serde_json::from_str(json).unwrap();
        assert_eq!(compression, Compression::LZString);
    }

    #[test]
    fn test_compression_deserialization_base64() {
        let json = r#""base64""#;
        let compression: Compression = serde_json::from_str(json).unwrap();
        assert_eq!(compression, Compression::Base64);

        let json = r#""b64""#;
        let compression: Compression = serde_json::from_str(json).unwrap();
        assert_eq!(compression, Compression::Base64);
    }

    #[test]
    fn test_compression_deserialization_unsupported() {
        let json = r#""unknown""#;
        let compression: Compression = serde_json::from_str(json).unwrap();
        assert_eq!(compression, Compression::Unsupported);
    }

    #[test]
    fn test_compression_display() {
        assert_eq!(Compression::Gzip.to_string(), "gzip");
        assert_eq!(Compression::LZString.to_string(), "lz64");
        assert_eq!(Compression::Base64.to_string(), "base64");
        assert_eq!(Compression::Unsupported.to_string(), "unsupported");
    }

    #[test]
    fn test_event_query_sent_at_milliseconds() {
        let query = EventQuery {
            sent_at: Some(1704067200000), // 2024-01-01 00:00:00 UTC in milliseconds
            ..Default::default()
        };

        let sent_at = query.sent_at();
        assert!(sent_at.is_some());

        let dt = sent_at.unwrap();
        assert!(dt.year() > 2020);
    }

    #[test]
    fn test_event_query_sent_at_seconds_ignored() {
        let query = EventQuery {
            sent_at: Some(1704067200), // In seconds (too old when interpreted as millis)
            ..Default::default()
        };

        let sent_at = query.sent_at();
        assert!(sent_at.is_none()); // Should be None because year would be < 2020
    }

    #[test]
    fn test_event_query_beacon_deserialization() {
        let json = r#"{"beacon":1}"#;
        let query: EventQuery = serde_json::from_str(json).unwrap();
        assert!(query.beacon);

        let json = r#"{"beacon":0}"#;
        let query: EventQuery = serde_json::from_str(json).unwrap();
        assert!(!query.beacon);

        let json = r#"{}"#;
        let query: EventQuery = serde_json::from_str(json).unwrap();
        assert!(!query.beacon);
    }

    #[test]
    fn test_event_form_data_alias() {
        // Test that "ver" is aliased to "lib_version"
        let json = r#"{"ver":"1.2.3"}"#;
        let form: EventFormData = serde_json::from_str(json).unwrap();
        assert_eq!(form.lib_version, Some("1.2.3".to_string()));

        // Test normal field name
        let json = r#"{"lib_version":"1.2.3"}"#;
        let form: EventFormData = serde_json::from_str(json).unwrap();
        assert_eq!(form.lib_version, Some("1.2.3".to_string()));
    }
}
