use std::collections::HashMap;

use common_kafka::kafka_messages::ingest_warning::IngestionWarning;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::error::PipelineResult;

// const SET_ON_EXCEPTION_WARNING_TYPE: &str = "set_on_exception";
// const EXCEPTION_INGESTION_SOURCE: &str = "exception_ingestion";

pub fn clean_set_props(
    mut buffer: Vec<PipelineResult>,
) -> (Vec<PipelineResult>, Vec<IngestionWarning>) {
    #[derive(Debug, Clone, Serialize, Deserialize)]

    struct SetProps {
        // The UI does not handle nulls well here, so we skip serialising instead
        #[serde(rename = "$set", skip_serializing_if = "Option::is_none")]
        set: Option<HashMap<String, Value>>,
        #[serde(rename = "$set_once", skip_serializing_if = "Option::is_none")]
        set_once: Option<HashMap<String, Value>>,
        #[serde(flatten)]
        other: HashMap<String, Value>,
    }

    let warnings = Vec::new();
    for item in buffer.iter_mut() {
        let Ok(event) = item else {
            continue;
        };

        let Some(props) = event.properties.take() else {
            continue;
        };

        // Danger zone - we've now modified the event, and have to remember
        // to put the props back on before returning

        let mut props: SetProps = serde_json::from_str(&props)
            .expect("event properties have successfully been parsed before");

        let had_set_props = props.set.is_some() || props.set_once.is_some();

        props.set = None;
        props.set_once = None;

        if had_set_props {
            let mut warning_details = HashMap::new();
            warning_details.insert(
                "event_uuid".to_string(),
                Value::String(event.uuid.to_string()),
            );

            // TODO - once we update SDKs to no longer send this automatically, we
            // should emit ingestion warnings for set and set_once properties
            // warnings.push(IngestionWarning::new(
            //     event.team_id,
            //     EXCEPTION_INGESTION_SOURCE.to_string(),
            //     SET_ON_EXCEPTION_WARNING_TYPE.to_string(),
            //     warning_details,
            //     None,
            // ));
        }

        event.properties =
            Some(serde_json::to_string(&props).expect("event properties can be serialized"));
    }

    (buffer, warnings)
}
