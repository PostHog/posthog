use serde::{Deserialize, Serialize};

pub mod mixpanel;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum ContentType {
    Mixpanel,
}

// All /extra/ information needed to go from any input format to an InternallyCapturedEvent,
// e.g. team_id
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransformContext {
    pub team_id: i32,
    pub token: String,
}
