use std::ops::Range;

use chrono::{DateTime, Datelike, SecondsFormat, Utc};
use serde::Serialize;
use thiserror::Error;
use usage_ingestion_proto::usage_ingestion::v1::{BillingUsageMode, BillingUsageRecord};
use uuid::Uuid;

const CLICKHOUSE_DATETIME64_YEARS: Range<i32> = 1900..2300;
const MAX_IDENTIFIER_LENGTH: usize = 200;
const MAX_DIMENSIONS: usize = 50;
const MAX_DIMENSION_LENGTH: usize = 500;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ValidationError {
    #[error("{0} must not be empty")]
    Empty(&'static str),
    #[error("{0} exceeds the maximum length")]
    TooLong(&'static str),
    #[error("team_id must be positive")]
    InvalidTeamId,
    #[error("quantity must be non-negative")]
    InvalidQuantity,
    #[error("delta quantity must be positive")]
    InvalidDeltaQuantity,
    #[error("version must be positive")]
    InvalidVersion,
    #[error(
        "event_timestamp_ms must be milliseconds since the epoch, between years 1900 and 2300"
    )]
    InvalidTimestamp,
    #[error("mode must be delta or snapshot")]
    InvalidMode,
    #[error("organization_id must be a UUID")]
    InvalidOrganizationId,
    #[error("too many dimensions")]
    TooManyDimensions,
    #[error("dimension keys and values must not exceed the maximum length")]
    InvalidDimension,
}

#[derive(Debug, Serialize)]
pub struct KafkaBillingUsageRecord {
    pub schema_version: u8,
    pub record_id: String,
    pub producer_id: String,
    pub team_id: i64,
    pub organization_id: Uuid,
    pub usage_key: String,
    pub mode: String,
    pub unit: String,
    pub quantity: i64,
    pub version: u64,
    pub event_timestamp: String,
    pub inserted_at: String,
    pub source_ref: String,
    pub user_id: String,
    pub variant: String,
    pub dimensions: std::collections::HashMap<String, String>,
}

impl KafkaBillingUsageRecord {
    pub fn from_proto(
        record: BillingUsageRecord,
        organization_id: Uuid,
        inserted_at: DateTime<Utc>,
    ) -> Result<Self, ValidationError> {
        validate_identifier("record_id", &record.record_id)?;
        validate_identifier("producer_id", &record.producer_id)?;
        validate_identifier("usage_key", &record.usage_key)?;
        validate_identifier("unit", &record.unit)?;
        if record.team_id <= 0 {
            return Err(ValidationError::InvalidTeamId);
        }
        if record.quantity < 0 {
            return Err(ValidationError::InvalidQuantity);
        }
        if record.version == 0 {
            return Err(ValidationError::InvalidVersion);
        }
        if record.dimensions.len() > MAX_DIMENSIONS {
            return Err(ValidationError::TooManyDimensions);
        }
        if record.dimensions.iter().any(|(key, value)| {
            key.is_empty() || key.len() > MAX_DIMENSION_LENGTH || value.len() > MAX_DIMENSION_LENGTH
        }) {
            return Err(ValidationError::InvalidDimension);
        }

        let mode = BillingUsageMode::try_from(record.mode).map_err(|_| ValidationError::InvalidMode)?;
        let mode = match mode {
            BillingUsageMode::Delta if record.quantity == 0 => {
                return Err(ValidationError::InvalidDeltaQuantity)
            }
            BillingUsageMode::Delta => "delta",
            BillingUsageMode::Snapshot => "snapshot",
            BillingUsageMode::Unspecified => return Err(ValidationError::InvalidMode),
        };
        if let Some(value) = record.organization_id.as_deref() {
            Uuid::parse_str(value).map_err(|_| ValidationError::InvalidOrganizationId)?;
        }
        // Outside DateTime64's range the Kafka engine table cannot parse the row, and
        // with no kafka_skip_broken_messages that stalls every record behind it.
        let event_timestamp = DateTime::from_timestamp_millis(record.event_timestamp_ms)
            .filter(|value| CLICKHOUSE_DATETIME64_YEARS.contains(&value.year()))
            .ok_or(ValidationError::InvalidTimestamp)?;

        Ok(Self {
            schema_version: 1,
            record_id: record.record_id,
            producer_id: record.producer_id,
            team_id: record.team_id,
            organization_id,
            usage_key: record.usage_key,
            mode: mode.to_string(),
            unit: record.unit,
            quantity: record.quantity,
            version: record.version,
            event_timestamp: event_timestamp.to_rfc3339_opts(SecondsFormat::Millis, true),
            inserted_at: inserted_at.to_rfc3339_opts(SecondsFormat::Millis, true),
            source_ref: record.source_ref.unwrap_or_default(),
            user_id: record.user_id.unwrap_or_default(),
            variant: record.variant.unwrap_or_default(),
            dimensions: record.dimensions,
        })
    }
}

fn validate_identifier(field: &'static str, value: &str) -> Result<(), ValidationError> {
    if value.is_empty() {
        return Err(ValidationError::Empty(field));
    }
    if value.len() > MAX_IDENTIFIER_LENGTH {
        return Err(ValidationError::TooLong(field));
    }
    Ok(())
}
