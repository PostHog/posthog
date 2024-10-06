use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub mod frames;
pub mod stacks;

// Given a Clickhouse Event's properties, we care about the contents
// of only a small subset. This struct is used to give us a strongly-typed
// "view" of those event properties we care about.
#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ErrProps {
    #[serde(rename = "$exception_type")]
    pub exception_type: String, // Required from exception producers - we will not process events without this
    #[serde(rename = "$exception_message")]
    pub exception_message: String, // Required from exception producers - we will not process events without this
    #[serde(rename = "$exception_stack_trace_raw")]
    pub exception_stack_trace_raw: Option<String>, // Not all exceptions have a stack trace
    #[serde(rename = "$exception_level")]
    pub exception_level: Option<String>, // We generally don't touch this, but we break it out explicitly for users. Not all exceptions have a level
    #[serde(rename = "$exception_source")]
    pub exception_source: Option<String>, // For some languages, we can associate the exception with e.g. a source file or binary.
    #[serde(rename = "$exception_lineno")]
    pub exception_line: Option<u32>, // Some exceptions have a source line
    #[serde(rename = "$exception_colno")]
    pub exception_col: Option<u32>, // Some even have a column
    #[serde(flatten)] // A catch-all for all the properties we don't "care" about
    pub other: HashMap<String, Value>,
}

#[cfg(test)]
mod test {
    use common_types::ClickHouseEvent;

    use crate::types::frames::RawFrame;

    use super::ErrProps;

    #[test]
    fn it_symbolifies() {
        let raw: &'static str = include_str!("../../tests/static/raw_js_stack.json");

        let raw: ClickHouseEvent = serde_json::from_str(raw).unwrap();

        let props: ErrProps = serde_json::from_str(&raw.properties.unwrap()).unwrap();

        let stack_trace: Vec<RawFrame> =
            serde_json::from_str(props.exception_stack_trace_raw.as_ref().unwrap()).unwrap();

        println!("{:?}", stack_trace);
    }
}
