use chrono::Utc;
use usage_ingestion::record::{KafkaBillingUsageRecord, ValidationError};
use usage_ingestion_proto::usage_ingestion::v1::{BillingUsageMode, BillingUsageRecord};
use uuid::Uuid;

fn record() -> BillingUsageRecord {
    BillingUsageRecord {
        record_id: "record-1".to_string(),
        producer_id: "feature-flags".to_string(),
        team_id: 42,
        organization_id: None,
        usage_key: "feature_flag_requests".to_string(),
        mode: BillingUsageMode::Delta as i32,
        unit: "request".to_string(),
        quantity: 2,
        version: 1,
        event_timestamp_ms: 1_700_000_000_000,
        source_ref: None,
        user_id: None,
        variant: None,
        dimensions: Default::default(),
    }
}

#[test]
fn converts_a_valid_record_to_clickhouse_json_shape() {
    let organization_id = Uuid::new_v4();
    let result = KafkaBillingUsageRecord::from_proto(record(), organization_id, Utc::now()).unwrap();

    assert_eq!(result.organization_id, organization_id);
    assert_eq!(result.mode, "delta");
    assert_eq!(result.event_timestamp, "2023-11-14T22:13:20.000Z");
}

/// A producer sending microseconds or nanoseconds would otherwise serialize a year
/// ClickHouse cannot parse, stalling the Kafka engine table on that row.
#[test]
fn rejects_timestamps_outside_the_clickhouse_range() {
    for event_timestamp_ms in [
        1_700_000_000_000_000,     // microseconds
        1_700_000_000_000_000_000, // nanoseconds
        -2_208_988_800_001,        // just before 1900
        10_413_792_000_000,        // 2300
    ] {
        let mut invalid = record();
        invalid.event_timestamp_ms = event_timestamp_ms;

        assert_eq!(
            KafkaBillingUsageRecord::from_proto(invalid, Uuid::new_v4(), Utc::now()).unwrap_err(),
            ValidationError::InvalidTimestamp,
            "{event_timestamp_ms} should be rejected"
        );
    }
}

#[test]
fn rejects_zero_delta_quantity() {
    let mut invalid = record();
    invalid.quantity = 0;

    assert_eq!(
        KafkaBillingUsageRecord::from_proto(invalid, Uuid::new_v4(), Utc::now()).unwrap_err(),
        ValidationError::InvalidDeltaQuantity
    );
}
