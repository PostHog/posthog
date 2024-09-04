use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use super::{deserialize_datetime, serialize_datetime};

#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
#[serde(rename_all = "lowercase")]
pub enum Source {
    Hoghooks,
    Cyclotron,
}

#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Success,
    Failure,
    Unknown,
}

#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
pub struct AppMetric2 {
    pub team_id: u32,
    #[serde(
        serialize_with = "serialize_datetime",
        deserialize_with = "deserialize_datetime"
    )]
    pub timestamp: DateTime<Utc>,
    pub app_source: Source,
    pub app_source_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub instance_id: Option<String>,
    pub metric_kind: Kind,
    pub metric_name: String,
    pub count: u32,
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
