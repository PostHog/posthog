use std::sync::Arc;

use mixpanel::MixpanelContentConfig;
use serde::{Deserialize, Serialize};

use crate::cache::{GroupCache, IdentifyCache};

pub mod amplitude;
pub mod captured;
pub mod mixpanel;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum ContentType {
    Mixpanel(MixpanelContentConfig), // From a mixpanel export
    Amplitude,
    Captured, // Each json object structured as if it was going to be sent to the capture endpoint
}

// All /extra/ information needed to go from any input format to an InternallyCapturedEvent,
// e.g. team_id
#[derive(Debug, Clone)]
pub struct TransformContext {
    pub team_id: i32,
    pub token: String,
    pub identify_cache: Arc<dyn IdentifyCache>,
    pub group_cache: Arc<dyn GroupCache>,
    pub import_events: bool,
    pub generate_identify_events: bool,
    pub generate_group_identify_events: bool,
}
