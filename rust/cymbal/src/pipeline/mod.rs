use std::sync::Arc;

use billing::apply_billing_limits;
use chrono::{DateTime, NaiveDateTime, Utc};
use clean::clean_set_props;
use common_kafka::kafka_producer::send_iter_to_kafka;
use common_types::{CapturedEvent, ClickHouseEvent};
use exception::do_exception_processing;
use geoip::add_geoip;
use person::add_person_properties;
use prep::prepare_events;
use serde::Deserialize;

use crate::{
    app_context::AppContext,
    error::{EventError, PipelineFailure, PipelineResult},
    teams::do_team_lookups,
};

pub mod billing;
pub mod clean;
pub mod errors;
pub mod exception;
pub mod geoip;
pub mod person;
pub mod prep;

// We can receive either ClickhouseEvents or CaptureEvents
#[derive(Debug, Clone, Deserialize)]
// ClickhouseEvent is hefty compared to CapturedEvent (496 vs 160 bytes), but we mostly pass
// around vecs of these and I'd rather skip the pointer chase
#[allow(clippy::large_enum_variant)]
pub enum IncomingEvent {
    ClickhouseReady(ClickHouseEvent),
    Captured(CapturedEvent),
}

pub async fn handle_batch(
    events: Vec<IncomingEvent>,
    context: Arc<AppContext>,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    let teams_lut = do_team_lookups(context.clone(), &events).await?;

    let start_count = events.len();

    let buffer = prepare_events(events, teams_lut)?;
    assert_eq!(start_count, buffer.len());

    // Now we have our buffer of "clickhouse events", and can start doing person processing etc
    let buffer = apply_billing_limits(buffer, &context).await?;
    assert_eq!(start_count, buffer.len());

    let (buffer, warnings) = clean_set_props(buffer);
    assert_eq!(start_count, buffer.len());

    // This isn't a failure tied to a specific, so we just panic rather than returning a PipelineFailure,
    // since we don't have an event index to associate with the failure
    send_iter_to_kafka(
        &context.immediate_producer,
        &context.config.ingestion_warnings_topic,
        warnings,
    )
    .await
    .into_iter()
    .collect::<Result<(), _>>()
    .expect("Failed to send warnings");

    let buffer = add_geoip(buffer, &context);
    assert_eq!(start_count, buffer.len());

    // We do exception processing before anything else so we can drop based on issue
    // suppression
    let buffer = do_exception_processing(buffer, context.clone()).await?;
    assert_eq!(start_count, buffer.len());

    let buffer = add_person_properties(buffer, context.clone()).await?;
    assert_eq!(start_count, buffer.len());

    // TODO - add this if we decide we need it, but since error tracking is new, any library
    // using it should be flattening on the client side
    // let buffer = do_semver_flattening(buffer);
    // assert_eq!(start_count, buffer.len());

    Ok(buffer)
}

// Equivalent to the JS:'yyyy-MM-dd HH:mm:ss.u'
const CH_FORMAT: &str = "%Y-%m-%d %H:%M:%S%.3f";
pub fn parse_ts_assuming_utc(input: &str) -> Result<DateTime<Utc>, EventError> {
    let mut parsed = DateTime::parse_from_rfc3339(input).map(|d| d.to_utc());

    if parsed.is_err() {
        // If we can't parse a timestamp, try parsing it as a naive datetime
        // and assuming UTC
        parsed = NaiveDateTime::parse_from_str(input, "%Y-%m-%d %H:%M:%S%.f").map(|d| d.and_utc())
    }

    parsed.map_err(|e| EventError::InvalidTimestamp(input.to_string(), e.to_string()))
}

pub fn format_ch_timestamp(ts: DateTime<Utc>) -> String {
    ts.format(CH_FORMAT).to_string()
}

#[cfg(test)]
mod test {

    use common_types::{ClickHouseEvent, PersonMode};
    use uuid::Uuid;

    use crate::pipeline::parse_ts_assuming_utc;

    #[test]
    pub fn test_timestamp_parsing() {
        let mut event = ClickHouseEvent {
            uuid: Uuid::now_v7(),
            team_id: 1,
            project_id: Some(1),
            event: "test".to_string(),
            distinct_id: "test".to_string(),
            properties: None,
            person_id: None,
            timestamp: "2021-08-02 12:34:56.789".to_string(),
            created_at: "2021-08-02 12:34:56.789".to_string(),
            elements_chain: None,
            person_created_at: None,
            person_properties: None,
            group0_properties: None,
            group1_properties: None,
            group2_properties: None,
            group3_properties: None,
            group4_properties: None,
            group0_created_at: None,
            group1_created_at: None,
            group2_created_at: None,
            group3_created_at: None,
            group4_created_at: None,
            person_mode: PersonMode::Propertyless,
        };

        let ts = parse_ts_assuming_utc(&event.timestamp).unwrap();
        assert_eq!(ts.to_rfc3339(), "2021-08-02T12:34:56.789+00:00");

        event.timestamp = "invalid".to_string();

        let ts = parse_ts_assuming_utc(&event.timestamp);
        assert!(ts.is_err());
    }
}
