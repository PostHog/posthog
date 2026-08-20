use prost::Message;
use usage_ingestion_proto::usage_ingestion::v1::{
    BillingUsageMode, BillingUsageRecord, IngestBillingUsageRequest,
};

#[test]
fn usage_record_round_trips_optional_organization_and_dimensions() {
    let request = IngestBillingUsageRequest {
        records: vec![BillingUsageRecord {
            record_id: "018f7c8e-4c08-7c5e-9bc0-15c9f5cc9f42".to_string(),
            producer_id: "feature-flags".to_string(),
            team_id: 42,
            organization_id: None,
            usage_key: "feature_flag_requests".to_string(),
            mode: BillingUsageMode::Delta as i32,
            unit: "request".to_string(),
            quantity: 10,
            version: 1,
            event_timestamp_ms: 1_700_000_000_000,
            source_ref: Some("flush:018f7c8e".to_string()),
            user_id: None,
            variant: Some("decide".to_string()),
            dimensions: [("library".to_string(), "js".to_string())].into(),
        }],
    };

    let decoded = IngestBillingUsageRequest::decode(request.encode_to_vec().as_slice()).unwrap();
    let record = decoded.records.first().unwrap();

    assert_eq!(record.team_id, 42);
    assert_eq!(record.organization_id, None);
    assert_eq!(record.mode, BillingUsageMode::Delta as i32);
    assert_eq!(record.dimensions.get("library"), Some(&"js".to_string()));
}
