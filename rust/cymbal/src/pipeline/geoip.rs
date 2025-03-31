use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{app_context::AppContext, error::PipelineResult};

// Delete the $IP property from the event if it exists, doing geoip lookup unless $geoip_disable is true
pub fn add_geoip(mut buffer: Vec<PipelineResult>, context: &AppContext) -> Vec<PipelineResult> {
    #[derive(Debug, Clone, Serialize, Deserialize)]
    struct GeoIpProps {
        #[serde(rename = "$ip")]
        ip: Option<String>,

        #[serde(flatten)]
        other: HashMap<String, Value>,
    }

    for item in buffer.iter_mut() {
        let Ok(event) = item else {
            continue;
        };

        let Some(properties) = &event.properties else {
            continue;
        };

        let mut ip_props: GeoIpProps = serde_json::from_str(properties)
            .expect("we control the $ip property type, and it should always be a string");

        // Clear the $ip property
        let Some(ip) = ip_props.ip.take() else {
            continue;
        };

        let Some(lookup) = context.geoip_client.get_geoip_properties(&ip) else {
            continue;
        };

        ip_props
            .other
            .extend(lookup.into_iter().map(|(k, v)| (k, Value::String(v))));
    }

    buffer
}
