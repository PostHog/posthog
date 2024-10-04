use std::collections::HashMap;

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use super::{js::RawJSFrame, symbolifier::Symbolifier};

#[derive(Debug, Deserialize)]
#[serde(untagged)]
pub enum RawFrame {
    JavaScript(RawJSFrame),
}

// Stacks don't care what the "type" of the frames they contain are, and even permit
// frames of different types to be mixed together, because we're going to end up "exploding"
// them into their frame-set anyway, and dispatching a task per frame in a language-agnostic
// way. Supporting mixed-type stacks is a side benefit of this - I don't know that we'll ever
// see them, but we get the flexibility "for free"
#[derive(Debug, Deserialize)]
pub struct RawStack {
    pub frames: Vec<RawFrame>,
}

pub enum ProcessedFrame {
    JavaScript(),
}

pub struct ProcessedStack {
    pub frames: Vec<ProcessedFrame>,
}

impl RawStack {
    pub async fn process(self, sym: &Symbolifier) -> ProcessedStack {
        unimplemented!()
    }
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct PropertyView {
    #[serde(rename = "$exception_type")]
    pub exception_type: String,
    #[serde(rename = "$exception_message")]
    pub exception_message: String,
    #[serde(rename = "$exception_stack_trace_raw")]
    pub exception_stack_trace_raw: String,
    #[serde(rename = "$exception_level")]
    pub exception_level: String,
    #[serde(rename = "$exception_source")]
    pub exception_source: String,
    #[serde(rename = "$exception_lineno")]
    pub exception_line: u32,
    #[serde(rename = "$exception_colno")]
    pub exception_col: u32,
    #[serde(flatten)]
    other: HashMap<String, Value>,
}

#[cfg(test)]
mod test {
    use common_types::ClickHouseEvent;

    use crate::symbols::types::{PropertyView, RawFrame};

    #[test]
    fn it_symbolifies() {
        let raw: &'static str = include_str!("../../tests/static/raw_js_stack.json");

        let raw: ClickHouseEvent = serde_json::from_str(raw).unwrap();

        let exception_properties: PropertyView =
            serde_json::from_str(&raw.properties.unwrap()).unwrap();

        let stack_trace: Vec<RawFrame> =
            serde_json::from_str(&exception_properties.exception_stack_trace_raw).unwrap();

        println!("{:?}", stack_trace);
    }
}
