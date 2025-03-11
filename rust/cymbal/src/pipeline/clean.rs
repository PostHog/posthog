use std::collections::HashMap;

use common_kafka::kafka_messages::ingest_warning::IngestionWarning;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::error::PipelineResult;

pub fn clean_set_props(
    mut buffer: Vec<PipelineResult>,
) -> (Vec<PipelineResult>, Vec<IngestionWarning>) {
    #[derive(Debug, Clone, Serialize, Deserialize)]

    struct SetProps {
        #[serde(rename = "$set")]
        set: Option<HashMap<String, Value>>,
        #[serde(rename = "$set_once")]
        set_once: Option<HashMap<String, Value>>,
        #[serde(flatten)]
        other: HashMap<String, Value>,
    }

    let mut warnings = Vec::new();
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

            warnings.push(IngestionWarning::new(
                event.team_id,
                "exception_ingestion".to_string(),
                "set_on_exception".to_string(),
                warning_details,
                None,
            ));
        }

        event.properties =
            Some(serde_json::to_string(&props).expect("event properties can be serialized"));
    }

    (buffer, warnings)
}
