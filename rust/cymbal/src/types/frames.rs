use serde::{Deserialize, Serialize};

use crate::{
    error::{Error, ResolutionError},
    langs::js::RawJSFrame,
    symbol_store::SymbolSetRef,
};

// We consume a huge variety of differently shaped stack frames, which we have special-case
// transformation for, to produce a single, unified representation of a frame.
#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(untagged)]
pub enum RawFrame {
    JavaScript(RawJSFrame),
}

impl RawFrame {
    pub fn source_ref(&self) -> Result<SymbolSetRef, Error> {
        let RawFrame::JavaScript(raw) = self;
        let id = raw.source_ref();
        id.map(SymbolSetRef::Js).map_err(Error::from)
    }

    // We expect different exception types to handle failure to resolve differently,
    // so raw frames are handed the error in the event of one to see if they can
    // turn it into a Frame anyway. E.g. for JS frames, if the failure is that
    // we didn't manage to find a sourcemap, that indicates we should treat the
    // frame as a "real" frame, and just pass it through.
    pub fn try_handle_resolve_error(&self, e: Error) -> Result<Frame, Error> {
        let RawFrame::JavaScript(raw) = self;

        // We unpack the general resolution error into the specific one our inner frame can
        // handle
        let Error::ResolutionError(ResolutionError::JavaScript(e)) = e else {
            return Err(e);
        };
        raw.try_handle_resolution_error(e)
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
