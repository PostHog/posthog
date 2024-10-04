use ::serde::Deserialize;

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
    pub frames: Vec<RawStack>,
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

#[cfg(test)]
mod test {
    use serde_json::Value;

    use crate::symbols::types::{RawFrame, RawStack};

    #[test]
    fn it_symbolifies() {
        let raw: &'static str = include_str!("../../tests/static/raw_js_stack.json");

        let raw: Vec<RawFrame> = serde_json::from_str(raw).unwrap();

        println!("{:?}", raw);
    }
}
