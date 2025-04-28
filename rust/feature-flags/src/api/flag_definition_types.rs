use crate::flags::flag_models::FeatureFlag;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FlagDefinitionsResponse {
    pub request_id: Uuid,

    pub flags: Vec<FeatureFlag>,

    pub group_type_mapping: HashMap<String, String>,
}
