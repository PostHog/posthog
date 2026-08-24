use std::ops::Range;

use chrono::{DateTime, Datelike, SecondsFormat, Utc};
use serde::Serialize;
use thiserror::Error;
use usage_ingestion_proto::usage_ingestion::v1::BillingUsageRecord;
use uuid::Uuid;

const CLICKHOUSE_DATETIME64_YEARS: Range<i32> = 1900..2300;
/// A record_id may have to mirror a whole dedup identity: the analytics producers compose
/// theirs from the events table's sorting key, whose event name and distinct_id are each
/// capped at 200. Rejecting one would drop the record and under-bill.
const MAX_IDENTIFIER_LENGTH: usize = 512;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ValidationError {
    #[error("{0} must not be empty")]
    Empty(&'static str),
    #[error("{0} exceeds the maximum length")]
    TooLong(&'static str),
    #[error("team_id must be positive")]
    InvalidTeamId,
    #[error("quantity must be positive")]
    InvalidQuantity,
    #[error("timestamp_ms must be milliseconds since the epoch, between years 1900 and 2300")]
    InvalidTimestamp,
}

#[derive(Debug, Serialize)]
pub struct KafkaBillingUsageRecord {
    pub schema_version: u8,
    pub record_id: String,
    pub producer_id: String,
    pub team_id: i64,
    pub organization_id: Uuid,
    pub usage_key: String,
    pub unit: String,
    pub quantity: i64,
    pub timestamp: String,
    pub inserted_at: String,
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
        // Every record is a delta, so nothing meaningful is zero. A snapshot producer would
        // need this exemption back alongside the mode column.
        if record.quantity <= 0 {
            return Err(ValidationError::InvalidQuantity);
        }

        // This protects the Kafka engine rather than defining a billing-time policy. Tighten the
        // accepted range when producers have an explicit backfill and future-skew contract.
        let timestamp = DateTime::from_timestamp_millis(record.timestamp_ms)
            .filter(|value| CLICKHOUSE_DATETIME64_YEARS.contains(&value.year()))
            .ok_or(ValidationError::InvalidTimestamp)?;

        Ok(Self {
            schema_version: 1,
            record_id: record.record_id,
            producer_id: record.producer_id,
            team_id: record.team_id,
            organization_id,
            usage_key: record.usage_key,
            unit: record.unit,
            quantity: record.quantity,
            timestamp: timestamp.to_rfc3339_opts(SecondsFormat::Millis, true),
            inserted_at: inserted_at.to_rfc3339_opts(SecondsFormat::Millis, true),
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
