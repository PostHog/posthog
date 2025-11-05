use std::collections::HashMap;

use metrics::counter;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{app_context::AppContext, error::PipelineResult, metric_consts::GEOIP_PROCESSED};

pub fn add_geoip(mut buffer: Vec<PipelineResult>, context: &AppContext) -> Vec<PipelineResult> {
    #[derive(Debug, Clone, Serialize, Deserialize)]
    struct GeoIpProps {
        // Not set if anonymize_ips is set at the team level
        #[serde(rename = "$ip", skip_serializing_if = "Option::is_none")]
        ip: Option<String>,

        #[serde(rename = "$geoip_disable", skip_serializing_if = "Option::is_none")]
        disabled: Option<bool>,

        #[serde(flatten)]
        other: HashMap<String, Value>,
    }

    for item in buffer.iter_mut() {
        let Ok(event) = item else {
            continue;
        };

        let Some(properties) = &event.properties else {
            counter!(GEOIP_PROCESSED, "outcome" => "no_props").increment(1);
            continue;
        };

        let mut ip_props: GeoIpProps = serde_json::from_str(properties)
            .expect("we control the $ip property type, and it should always be a string");

        if ip_props.disabled.unwrap_or_default() {
            counter!(GEOIP_PROCESSED, "outcome" => "disabled").increment(1);
            continue;
        }

        let Some(ip) = ip_props.ip.clone() else {
            counter!(GEOIP_PROCESSED, "outcome" => "no_ip").increment(1);
            continue;
        };

        let Some(lookup) = context.geoip_client.get_geoip_properties(&ip) else {
            counter!(GEOIP_PROCESSED, "outcome" => "lookup_failed").increment(1);
            continue;
        };

        ip_props
            .other
            .extend(lookup.into_iter().map(|(k, v)| (k, Value::String(v))));

        event.properties =
            Some(serde_json::to_string(&ip_props).expect("serialization should not fail"));
    }

    buffer
}
