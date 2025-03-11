use mixpanel::MixpanelContentConfig;
use serde::{Deserialize, Serialize};

pub mod captured;
pub mod mixpanel;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum ContentType {
    Mixpanel(MixpanelContentConfig), // From a mixpanel export
    Captured, // Each json object structured as if it was going to be sent to the capture endpoint
}

// All /extra/ information needed to go from any input format to an InternallyCapturedEvent,
// e.g. team_id
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransformContext {
    pub team_id: i32,
    pub token: String,
}
