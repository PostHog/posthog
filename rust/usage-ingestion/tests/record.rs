use chrono::Utc;
use usage_ingestion::record::{KafkaBillingUsageRecord, ValidationError};
use usage_ingestion_proto::usage_ingestion::v1::BillingUsageRecord;
use uuid::Uuid;

fn record() -> BillingUsageRecord {
    BillingUsageRecord {
        record_id: "record-1".to_string(),
        producer_id: "feature-flags".to_string(),
        team_id: 42,
        usage_key: "feature_flag_requests".to_string(),
        unit: "request".to_string(),
        quantity: 2,
        timestamp_ms: 1_700_000_000_000,
    }
}

#[test]
fn converts_a_valid_record_to_clickhouse_json_shape() {
    let organization_id = Uuid::new_v4();
    let result =
        KafkaBillingUsageRecord::from_proto(record(), organization_id, Utc::now()).unwrap();

    assert_eq!(result.organization_id, organization_id);
    assert_eq!(result.timestamp, "2023-11-14T22:13:20.000Z");
}

/// A producer sending microseconds or nanoseconds would otherwise serialize a year
/// ClickHouse cannot parse, stalling the Kafka engine table on that row.
#[test]
fn rejects_timestamps_outside_the_clickhouse_range() {
    for timestamp_ms in [
        1_700_000_000_000_000,     // microseconds
        1_700_000_000_000_000_000, // nanoseconds
        -2_208_988_800_001,        // just before 1900
        10_413_792_000_000,        // 2300
    ] {
        let mut invalid = record();
        invalid.timestamp_ms = timestamp_ms;

        assert_eq!(
            KafkaBillingUsageRecord::from_proto(invalid, Uuid::new_v4(), Utc::now()).unwrap_err(),
            ValidationError::InvalidTimestamp,
            "{timestamp_ms} should be rejected"
        );
    }
}

/// Every record is a delta, so a zero or negative quantity bills nothing and means nothing.
#[test]
fn rejects_quantities_that_are_not_positive() {
    for quantity in [0, -1] {
        let mut invalid = record();
        invalid.quantity = quantity;

        assert_eq!(
            KafkaBillingUsageRecord::from_proto(invalid, Uuid::new_v4(), Utc::now()).unwrap_err(),
            ValidationError::InvalidQuantity,
            "quantity {quantity} should be rejected"
        );
    }
}

/// The analytics producers compose a record_id from the events table's dedup identity, whose
/// event name and distinct_id are each capped at 200. Lowering this bound would reject those
/// records, and a rejected record is usage nobody is billed for.
#[test]
fn accepts_a_record_id_long_enough_for_a_composed_identity() {
    for (length, expected) in [
        (512, Ok(())),
        (513, Err(ValidationError::TooLong("record_id"))),
    ] {
        let mut candidate = record();
        candidate.record_id = "r".repeat(length);
        let result = KafkaBillingUsageRecord::from_proto(candidate, Uuid::new_v4(), Utc::now());
        assert_eq!(result.map(|_| ()), expected, "record_id of {length} bytes");
    }
}
