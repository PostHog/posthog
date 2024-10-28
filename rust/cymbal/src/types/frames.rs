use serde::{Deserialize, Serialize};

use crate::{
    error::Error, langs::js::RawJSFrame, metric_consts::PER_FRAME_TIME, symbol_store::Catalog,
};

// We consume a huge variety of differently shaped stack frames, which we have special-case
// transformation for, to produce a single, unified representation of a frame.
#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(untagged)]
pub enum RawFrame {
    JavaScript(RawJSFrame),
}

impl RawFrame {
    pub async fn resolve(&self, team_id: i32, catalog: &Catalog) -> Result<Frame, Error> {
        let RawFrame::JavaScript(raw) = self;

        let frame_resolve_time = common_metrics::timing_guard(PER_FRAME_TIME, &[]);
        let res = raw.resolve(team_id, catalog).await;
        if res.is_err() {
            frame_resolve_time.label("outcome", "failed")
        } else {
            frame_resolve_time.label("outcome", "success")
        }
        .fin();

        res
    }
}

// We emit a single, unified representation of a frame, which is what we pass on to users.
#[derive(Debug, Clone, Serialize)]
pub struct Frame {
    pub mangled_name: String,          // Mangled name of the function
    pub line: Option<u32>,             // Line the function is define on, if known
    pub column: Option<u32>,           // Column the function is defined on, if known
    pub source: Option<String>,        // Generally, the file the function is defined in
    pub in_app: bool,                  // We hard-require clients to tell us this?
    pub resolved_name: Option<String>, // The name of the function, after symbolification
    pub lang: String,                  // The language of the frame. Always known (I guess?)
}
