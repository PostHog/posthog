use std::fmt::Display;

use serde::{Deserialize, Serialize};

use crate::{
    error::UnhandledError,
    frames::Frame,
    langs::CommonFrameMetadata,
    symbol_store::{chunk_id::OrChunkId, hermesmap::ParsedHermesMap, SymbolCatalog},
};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawHermesFrame {
    #[serde(rename = "colno")]
    pub column: u32, // Hermes frames don't have a line number
    #[serde(rename = "filename")]
    pub source: String, // This will /usually/ be meaningless
    #[serde(rename = "function")]
    pub fn_name: String, // Mangled function name - sometimes, but not always, the same as the demangled function name
    #[serde(rename = "chunkId", skip_serializing_if = "Option::is_none")]
    pub chunk_id: Option<String>, // Hermes frames are required to provide a chunk ID, or they cannot be resolved
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

// This is an enum it's impossible to construct an instance of. We use it here, along with OrChunkId, to represent that the hermes frames
// will always have a chunk ID - this lets us assert the OrChunkId variant will always be OrChunkId::ChunkId, because the R in this case
// is impossible to construct. Change to a never type once that's stable - https://doc.rust-lang.org/std/primitive.never.html
#[derive(Debug, Clone)]
pub enum HermesRef {}

impl RawHermesFrame {
    pub async fn resolve<C>(&self, team_id: i32, catalog: &C) -> Result<Frame, UnhandledError>
    where
        C: SymbolCatalog<OrChunkId<HermesRef>, ParsedHermesMap>,
    {
        todo!()
    }

    pub fn frame_id(&self) -> String {
        todo!()
    }
}

impl Display for HermesRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "HermesRef")
    }
}
