use anyhow::Error;
use chrono::Utc;
use common_types::{CapturedEvent, InternallyCapturedEvent, RawEvent};
use serde_json::Value;
use uuid::Uuid;

use super::TransformContext;

pub fn captured_parse_fn(
    context: TransformContext,
    event_transform: impl Fn(RawEvent) -> Result<Option<RawEvent>, Error>,
) -> impl Fn(RawEvent) -> Result<Option<InternallyCapturedEvent>, Error> {
    move |raw| {
        let Some(mut raw) = event_transform(raw)? else {
            return Ok(None);
        };

        //TODO - HACK: relevant customer specifically asked for this, but it's not right in the general case
        raw.map_property("organization_id", try_parse_to_num);

        raw.properties.insert(
            "$import_job_id".to_string(),
            Value::String(context.job_id.to_string()),
        );

        let raw = raw;

        let Some(distinct_id) = raw.extract_distinct_id() else {
            return Err(Error::msg("No distinct_id found"));
        };
        // We'll respect the events uuid if ones set
        let uuid = raw.uuid.unwrap_or_else(Uuid::now_v7);
        // Grab the events timestamp, or make one up
        let timestamp = get_timestamp(&raw);

        // Only return the event if import_events is enabled
        if context.import_events {
            let inner = CapturedEvent {
                uuid,
                distinct_id,
                ip: "127.0.0.1".to_string(),
                data: serde_json::to_string(&raw)?,
                now: timestamp,
                sent_at: None, // We don't know when it was sent at, since it's a historical import
                token: context.token.clone(),
                is_cookieless_mode: false,
            };

            Ok(Some(InternallyCapturedEvent {
                team_id: context.team_id,
                inner,
            }))
        } else {
            Ok(None)
        }
    }
}

// We use the events timestamp value, if it has one, otherwise we use the current time
fn get_timestamp(event: &RawEvent) -> String {
    match &event.timestamp {
        Some(timestamp) => timestamp.clone(),
        None => Utc::now().to_rfc3339(),
    }
}

fn try_parse_to_num(value: Value) -> Value {
    match value {
        Value::String(s) => {
            // The options for a Number are u64m i64 or f64
            if let Ok(n) = s.parse::<u64>() {
                Value::from(n)
            } else if let Ok(n) = s.parse::<i64>() {
                Value::from(n)
            } else if let Ok(n) = s.parse::<f64>() {
                Value::from(n)
            } else {
                Value::from(s)
            }
        }
        _ => value,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::HashMap;

    fn identity_transform(event: RawEvent) -> Result<Option<RawEvent>, Error> {
        Ok(Some(event))
    }

    #[test]
    fn test_job_id_in_captured_event() {
        let test_job_id = Uuid::now_v7();

        let mut properties = HashMap::new();
        properties.insert("test_prop".to_string(), json!("test_value"));

        let raw_event = RawEvent {
            token: Some("test_token".to_string()),
            distinct_id: Some(Value::String("user123".to_string())),
            uuid: Some(Uuid::now_v7()),
            event: "test_event".to_string(),
            properties,
            timestamp: Some("2023-10-15T14:30:00+00:00".to_string()),
            set: None,
            set_once: None,
            offset: None,
        };

        let context = TransformContext {
            team_id: 123,
            token: "test_token".to_string(),
            job_id: test_job_id,
            identify_cache: std::sync::Arc::new(crate::cache::MockIdentifyCache::new()),
            group_cache: std::sync::Arc::new(crate::cache::MockGroupCache::new()),
            import_events: true,
            generate_identify_events: false,
            generate_group_identify_events: false,
        };

        let parser = captured_parse_fn(context, identity_transform);
        let result = parser(raw_event).unwrap().unwrap();

        assert_eq!(result.team_id, 123);
        assert_eq!(result.inner.distinct_id, "user123");

        let data: RawEvent = serde_json::from_str(&result.inner.data).unwrap();
        assert_eq!(
            data.properties.get("$import_job_id"),
            Some(&json!(test_job_id.to_string()))
        );
        assert_eq!(data.properties.get("test_prop"), Some(&json!("test_value")));
    }
}
