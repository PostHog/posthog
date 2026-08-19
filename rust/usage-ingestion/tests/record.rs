use chrono::Utc;
use usage_ingestion::record::{KafkaUsageRecord, ValidationError};
use usage_ingestion_proto::usage_ingestion::v1::{UsageMode, UsageRecord};
use uuid::Uuid;

fn record() -> UsageRecord {
    UsageRecord {
        record_id: "record-1".to_string(),
        producer_id: "feature-flags".to_string(),
        team_id: 42,
        organization_id: None,
        usage_key: "feature_flag_requests".to_string(),
        mode: UsageMode::Delta as i32,
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
    let result = KafkaUsageRecord::from_proto(record(), organization_id, Utc::now()).unwrap();

    assert_eq!(result.organization_id, organization_id);
    assert_eq!(result.mode, "delta");
    assert_eq!(result.event_timestamp, "2023-11-14T22:13:20.000Z");
}

#[test]
fn rejects_zero_delta_quantity() {
    let mut invalid = record();
    invalid.quantity = 0;

    assert_eq!(
        KafkaUsageRecord::from_proto(invalid, Uuid::new_v4(), Utc::now()).unwrap_err(),
        ValidationError::InvalidDeltaQuantity
    );
}
