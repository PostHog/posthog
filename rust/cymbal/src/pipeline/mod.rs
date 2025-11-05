use std::sync::Arc;

use billing::apply_billing_limits;
use clean::clean_set_props;
use common_kafka::{
    kafka_consumer::Offset, kafka_messages::ingest_warning::IngestionWarning,
    kafka_producer::send_iter_to_kafka,
};
use common_types::{CapturedEvent, ClickHouseEvent};

use exception::do_exception_handling;
use geoip::add_geoip;
use person::add_person_properties;
use prep::prepare_events;
use serde::Deserialize;
use tracing::error;

use crate::{
    app_context::{AppContext, FilterMode},
    error::{EventError, PipelineFailure, PipelineResult, UnhandledError},
    metric_consts::{
        BILLING_LIMITS_TIME, CLEAN_PROPS_TIME, EMIT_INGESTION_WARNINGS_TIME,
        EXCEPTION_PROCESSING_TIME, GEOIP_TIME, GROUP_TYPE_MAPPING_TIME, PERSON_PROCESSING_TIME,
        PREPARE_EVENTS_TIME, TEAM_LOOKUP_TIME,
    },
    pipeline::group::map_group_types,
    teams::do_team_lookups,
};

pub mod billing;
pub mod clean;
pub mod errors;
pub mod exception;
pub mod geoip;
pub mod group;
pub mod person;
pub mod prep;

// We can receive either ClickhouseEvents or CaptureEvents
#[derive(Debug, Clone, Deserialize)]
// ClickhouseEvent is hefty compared to CapturedEvent (496 vs 160 bytes), but we mostly pass
// around vecs of these and I'd rather skip the pointer chase
#[allow(clippy::large_enum_variant)]
#[serde(untagged)]
pub enum IncomingEvent {
    ClickhouseReady(ClickHouseEvent),
    Captured(CapturedEvent),
}

pub async fn handle_batch(
    buffer: Vec<IncomingEvent>,
    offsets: &[Offset], // Used purely for debugging
    context: Arc<AppContext>,
) -> Result<Vec<PipelineResult>, PipelineFailure> {
    let log_err = |err: PipelineFailure| {
        let (index, err) = (err.index, err.error);
        let offset = &offsets[index];
        error!("Error handling event: {:?}; offset: {:?}", err, offset);
        err
    };

    let billing_limits_time = common_metrics::timing_guard(BILLING_LIMITS_TIME, &[]);
    let buffer = apply_billing_limits(buffer, &context)
        .await
        .map_err(log_err)
        .unwrap();
    billing_limits_time.label("outcome", "success").fin();

    // We grab the start count after applying billing limits, because we
    // drop events then.
    let start_count = buffer.len();

    let team_lookup_time = common_metrics::timing_guard(TEAM_LOOKUP_TIME, &[]);
    let teams_lut = do_team_lookups(context.clone(), &buffer)
        .await
        .map_err(log_err)
        .unwrap();
    team_lookup_time.label("outcome", "success").fin();

    let prepare_time = common_metrics::timing_guard(PREPARE_EVENTS_TIME, &[]);
    let buffer = prepare_events(buffer, teams_lut).map_err(log_err).unwrap();
    prepare_time.label("outcome", "success").fin();
    assert_eq!(start_count, buffer.len());

    let buffer = filter_by_team_id(buffer, &context.filtered_teams, &context.filter_mode);

    let clean_props_time = common_metrics::timing_guard(CLEAN_PROPS_TIME, &[]);
    let (buffer, warnings) = clean_set_props(buffer);
    clean_props_time.label("outcome", "success").fin();
    assert_eq!(start_count, buffer.len());

    let geoip_time = common_metrics::timing_guard(GEOIP_TIME, &[]);
    let buffer = add_geoip(buffer, &context);
    geoip_time.label("outcome", "success").fin();
    assert_eq!(start_count, buffer.len());

    let gtm_time = common_metrics::timing_guard(GROUP_TYPE_MAPPING_TIME, &[]);
    let buffer = map_group_types(buffer, &context).await?;
    gtm_time.label("outcome", "success").fin();
    assert_eq!(start_count, buffer.len());

    // We do exception processing before person processing so we can drop based on issue
    // suppression before doing the more expensive pipeline stage
    let exception_time = common_metrics::timing_guard(EXCEPTION_PROCESSING_TIME, &[]);
    let buffer = do_exception_handling(buffer, context.clone())
        .await
        .map_err(log_err)
        .unwrap();
    exception_time.label("outcome", "success").fin();
    assert_eq!(start_count, buffer.len());

    let person_time = common_metrics::timing_guard(PERSON_PROCESSING_TIME, &[]);
    let buffer = add_person_properties(buffer, context.clone())
        .await
        .map_err(log_err)
        .unwrap();
    person_time.label("outcome", "success").fin();
    assert_eq!(start_count, buffer.len());

    // We choose to panic if this fails, because failure to emit ingestion warnings implies a kafka problem
    let emit_warning_time = common_metrics::timing_guard(EMIT_INGESTION_WARNINGS_TIME, &[]);
    emit_ingestion_warnings(&context, warnings)
        .await
        .expect("Emitting ingestion warnings does not fail");
    emit_warning_time.label("outcome", "success").fin();

    Ok(buffer)
}

pub fn filter_by_team_id(
    events: Vec<PipelineResult>,
    team_ids: &[i32],
    mode: &FilterMode,
) -> Vec<PipelineResult> {
    events
        .into_iter()
        .map(|e| {
            let Ok(e) = e else { return e };

            match (mode, team_ids.contains(&e.team_id)) {
                (FilterMode::In, true) | (FilterMode::Out, false) => Ok(e),
                (FilterMode::In, false) | (FilterMode::Out, true) => {
                    Err(EventError::FilteredByTeamId)
                }
            }
        })
        .collect()
}

pub async fn emit_ingestion_warnings(
    context: &AppContext,
    warnings: Vec<IngestionWarning>,
) -> Result<(), UnhandledError> {
    send_iter_to_kafka(
        &context.immediate_producer,
        &context.config.ingestion_warnings_topic,
        warnings,
    )
    .await
    .into_iter()
    .collect::<Result<(), _>>()
    .map_err(|e| e.into())
}

#[cfg(test)]
mod test {

    use common_types::{format::parse_datetime_assuming_utc, ClickHouseEvent, PersonMode};
    use uuid::Uuid;

    use crate::app_context::FilterMode;

    use super::filter_by_team_id;

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

        let ts = parse_datetime_assuming_utc(&event.timestamp).unwrap();
        assert_eq!(ts.to_rfc3339(), "2021-08-02T12:34:56.789+00:00");

        event.timestamp = "invalid".to_string();

        let ts = parse_datetime_assuming_utc(&event.timestamp);
        assert!(ts.is_err());
    }

    #[test]
    pub fn test_team_filtering() {
        let event = ClickHouseEvent {
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

        let buffer = vec![Ok(event)];

        let filter_list = vec![1];

        let result = filter_by_team_id(buffer.clone(), &filter_list, &FilterMode::In);
        for event in result {
            assert!(event.is_ok())
        }

        let result = filter_by_team_id(buffer.clone(), &filter_list, &FilterMode::Out);
        for event in result {
            assert!(event.is_err())
        }

        let filter_list = vec![2];
        let result = filter_by_team_id(buffer.clone(), &filter_list, &FilterMode::In);
        for event in result {
            assert!(event.is_err())
        }

        let result = filter_by_team_id(buffer, &filter_list, &FilterMode::Out);
        for event in result {
            assert!(event.is_ok())
        }
    }
}
