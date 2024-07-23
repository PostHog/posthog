use chrono::{DateTime, Utc};
use serde::{Deserialize, Deserializer, Serialize, Serializer};

use super::{deserialize_datetime, serialize_datetime};

#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
pub enum Source {
    Hoghooks,
}

#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
pub enum Kind {
    Success,
    Failure,
}

#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
pub struct AppMetric2 {
    pub team_id: u32,
    #[serde(
        serialize_with = "serialize_datetime",
        deserialize_with = "deserialize_datetime"
    )]
    pub timestamp: DateTime<Utc>,
    #[serde(
        serialize_with = "serialize_source",
        deserialize_with = "deserialize_source"
    )]
    pub app_source: Source,
    pub app_source_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub instance_id: Option<String>,
    #[serde(
        serialize_with = "serialize_kind",
        deserialize_with = "deserialize_kind"
    )]
    pub metric_kind: Kind,
    pub metric_name: String,
    pub count: u32,
}

fn serialize_source<S>(source: &Source, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    let category_str = match source {
        Source::Hoghooks => "hoghooks",
    };
    serializer.serialize_str(category_str)
}

fn deserialize_source<'de, D>(deserializer: D) -> Result<Source, D::Error>
where
    D: Deserializer<'de>,
{
    let s: String = Deserialize::deserialize(deserializer)?;

    let source = match &s[..] {
        "hoghooks" => Source::Hoghooks,
        _ => return Err(serde::de::Error::unknown_variant(&s, &["hoghooks"])),
    };

    Ok(source)
}

fn serialize_kind<S>(kind: &Kind, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    let category_str = match kind {
        Kind::Success => "success",
        Kind::Failure => "failure",
    };
    serializer.serialize_str(category_str)
}

fn deserialize_kind<'de, D>(deserializer: D) -> Result<Kind, D::Error>
where
    D: Deserializer<'de>,
{
    let s: String = Deserialize::deserialize(deserializer)?;

    let kind = match &s[..] {
        "success" => Kind::Success,
        "failure" => Kind::Failure,
        _ => {
            return Err(serde::de::Error::unknown_variant(
                &s,
                &["success", "failure"],
            ))
        }
    };

    Ok(kind)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_app_metric2_serialization() {
        use chrono::prelude::*;

        let app_metric = AppMetric2 {
            team_id: 123,
            timestamp: Utc.with_ymd_and_hms(2023, 12, 14, 12, 2, 0).unwrap(),
            app_source: Source::Hoghooks,
            app_source_id: "hog-function-1".to_owned(),
            instance_id: Some("hash".to_owned()),
            metric_kind: Kind::Success,
            metric_name: "fetch".to_owned(),
            count: 456,
        };

        let serialized_json = serde_json::to_string(&app_metric).unwrap();

        let expected_json = r#"{"team_id":123,"timestamp":"2023-12-14 12:02:00","app_source":"hoghooks","app_source_id":"hog-function-1","instance_id":"hash","metric_kind":"success","metric_name":"fetch","count":456}"#;

        assert_eq!(serialized_json, expected_json);
    }
}
