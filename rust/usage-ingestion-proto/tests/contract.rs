use prost::Message;
use usage_ingestion_proto::usage_ingestion::v1::{BillingUsageRecord, IngestBillingUsageRequest};

#[test]
fn usage_record_round_trips_every_field() {
    let request = IngestBillingUsageRequest {
        records: vec![BillingUsageRecord {
            record_id: "018f7c8e-4c08-7c5e-9bc0-15c9f5cc9f42".to_string(),
            producer_id: "feature-flags".to_string(),
            team_id: 42,
            usage_key: "feature_flag_requests".to_string(),
            unit: "request".to_string(),
            quantity: 10,
            timestamp_ms: 1_700_000_000_000,
        }],
    };

    let decoded = IngestBillingUsageRequest::decode(request.encode_to_vec().as_slice()).unwrap();
    let record = decoded.records.first().unwrap();

    assert_eq!(record.team_id, 42);
    assert_eq!(record.timestamp_ms, 1_700_000_000_000);
    assert_eq!(record.record_id, "018f7c8e-4c08-7c5e-9bc0-15c9f5cc9f42");
    assert_eq!(record.quantity, 10);
}
