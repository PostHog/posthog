use serde::{Deserialize, Serialize};

use super::frames::{Frame, RawFrame};

// The stacks we consume are a list of frames. This structure is very flexible, so that
// we support stacks of intermingled languages or types. We only case about special-cased
// handling on a per-frame basis, not a per-stack basis. All the "logic" lives at the frame
// level
#[derive(Debug, Deserialize)]
pub struct RawStack {
    pub frames: Vec<RawFrame>,
}

// Our resolved stacks are, as you'd expect, just a vecs of frames. We might add
// "stack-level" information at some point, if we find a need.
#[derive(Debug, Serialize)]
pub struct Stack {
    pub frames: Vec<Frame>,
}
