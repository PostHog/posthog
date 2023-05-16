use std::collections::HashMap;

use serde::{Deserialize, Serialize};
// Define the API interface for capture here.
// This is used for serializing responses and deserializing requests

// LATER ME
// Trying to figure out wtf the schema for this is. Turns out we have about
// a million special cases and properties all over the place

Also - what are the possible types for a property value? Account for those.
#[derive(Debug, Deserialize, Serialize)]
pub struct CaptureRequest{
    #[serde(alias = "$token", alias = "api_key")]
    pub token: String,

    pub event: String,
    pub properties: HashMap<String>
}

#[derive(Debug, Deserialize, Serialize)]
pub struct CaptureResponse{}
