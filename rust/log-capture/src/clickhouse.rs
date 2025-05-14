use ::time::OffsetDateTime;
use anyhow::{Context, Result};
use clickhouse::Client;
use opentelemetry_proto::tonic::common::v1::{AnyValue, InstrumentationScope, KeyValue};
use opentelemetry_proto::tonic::logs::v1::LogRecord;
use serde_json::{json, Value as JsonValue};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tracing::{error, info};
use uuid::Uuid;

use crate::config::Config;

pub struct ClickHouseWriter {
    client: Client,
}

impl ClickHouseWriter {
    pub async fn new(config: Arc<Config>) -> Result<Self> {
        let client = Client::default()
            .with_url(config.clickhouse_url.clone())
            .with_database(config.clickhouse_database.clone())
            .with_user(config.clickhouse_user.clone())
            .with_password(config.clickhouse_password.clone());

        // Verify connection
        client
            .query("SELECT 1")
            .execute()
            .await
            .context("Failed to connect to ClickHouse")?;

        info!(
            "Successfully connected to ClickHouse at {}",
            config.clickhouse_url
        );

        Ok(Self { client })
    }

    pub async fn insert_log(
        &self,
        team_id: i64,
        log_record: &LogRecord,
        resource_str: &str,
        scope: Option<&InstrumentationScope>,
    ) -> Result<()> {
        // Extract body
        let body = match &log_record.body {
            Some(body) => match &body.value {
                Some(value) => match value {
                    opentelemetry_proto::tonic::common::v1::any_value::Value::StringValue(s) => {
                        s.clone()
                    }
                    _ => format!("{:?}", value),
                },
                None => "".to_string(),
            },
            None => "".to_string(),
        };

        // Extract severity text
        let severity_text = log_record.severity_text.clone();

        // Attributes as JSON
        let attributes_json = attributes_to_json(&log_record.attributes);

        // Get scope name or empty string
        let instrumentation_scope = match scope {
            Some(s) => format!("{}@{}", s.name, s.version),
            None => "".to_string(),
        };

        // Extract event name if present
        let event_name = extract_event_name(&log_record.attributes);

        // Trace/span IDs
        let trace_id = bytes_to_uuid(&log_record.trace_id).unwrap_or_else(Uuid::new_v4);
        let span_id = bytes_to_uuid(&log_record.span_id).unwrap_or_else(Uuid::new_v4);

        // Trace flags
        let trace_flags = log_record.flags as u8;

        // FormatGenerate query with parameters
        let query = format!(
            "INSERT INTO logs (uuid, team_id, trace_id, span_id, trace_flags, timestamp, \
             body, attributes, severity_text, severity_number, resource, instrumentation_scope, event_name) \
             VALUES ('{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}')",
            Uuid::new_v4(),
            team_id,
            trace_id,
            span_id,
            trace_flags,
            log_record.time_unix_nano,
            escape_string(&body),
            escape_string(&attributes_json),
            escape_string(&severity_text),
            log_record.severity_number as u8,
            escape_string(resource_str),
            escape_string(&instrumentation_scope),
            escape_string(&event_name)
        );

        // Execute the query
        match self.client.query(&query).execute().await {
            Ok(_) => Ok(()),
            Err(e) => {
                error!("Failed to insert log into ClickHouse: {:?}", e);
                Err(anyhow::anyhow!("Failed to insert log: {}", e))
            }
        }
    }
}

fn escape_string(s: &str) -> String {
    s.replace('\'', "''")
}

fn extract_event_name(attributes: &[KeyValue]) -> String {
    for attr in attributes {
        if attr.key == "event.name" {
            if let Some(value) = &attr.value {
                if let Some(value_enum) = &value.value {
                    match value_enum {
                        opentelemetry_proto::tonic::common::v1::any_value::Value::StringValue(
                            s,
                        ) => return s.clone(),
                        _ => {}
                    }
                }
            }
        }
    }
    "".to_string()
}

fn bytes_to_uuid(bytes: &[u8]) -> Option<Uuid> {
    if bytes.len() == 16 {
        let mut uuid_bytes = [0; 16];
        uuid_bytes.copy_from_slice(bytes);
        Some(Uuid::from_bytes(uuid_bytes))
    } else {
        None
    }
}

fn nanoseconds_to_datetime(nanos: u64) -> OffsetDateTime {
    let seconds = (nanos / 1_000_000_000) as i64;
    let nanoseconds = (nanos % 1_000_000_000) as u32;

    match OffsetDateTime::from_unix_timestamp(seconds) {
        Ok(datetime) => datetime.replace_nanosecond(nanoseconds).unwrap_or(datetime),
        Err(_) => OffsetDateTime::now_utc(),
    }
}

fn attributes_to_json(attributes: &[KeyValue]) -> String {
    let mut map = HashMap::new();

    for attr in attributes {
        if let Some(value) = &attr.value {
            let json_value = any_value_to_json(value);
            map.insert(attr.key.clone(), json_value);
        }
    }

    serde_json::to_string(&map).unwrap_or_else(|_| "{}".to_string())
}

fn any_value_to_json(value: &AnyValue) -> JsonValue {
    match &value.value {
        Some(value_enum) => match value_enum {
            opentelemetry_proto::tonic::common::v1::any_value::Value::StringValue(s) => json!(s),
            opentelemetry_proto::tonic::common::v1::any_value::Value::BoolValue(b) => json!(b),
            opentelemetry_proto::tonic::common::v1::any_value::Value::IntValue(i) => json!(i),
            opentelemetry_proto::tonic::common::v1::any_value::Value::DoubleValue(d) => json!(d),
            opentelemetry_proto::tonic::common::v1::any_value::Value::ArrayValue(arr) => {
                json!(arr.values.iter().map(any_value_to_json).collect::<Vec<_>>())
            }
            opentelemetry_proto::tonic::common::v1::any_value::Value::KvlistValue(kvlist) => {
                let mut map = HashMap::new();
                for kv in &kvlist.values {
                    if let Some(v) = &kv.value {
                        map.insert(kv.key.clone(), any_value_to_json(v));
                    }
                }
                json!(map)
            }
            opentelemetry_proto::tonic::common::v1::any_value::Value::BytesValue(b) => {
                json!(base64::encode(b))
            }
        },
        None => json!(null),
    }
}
