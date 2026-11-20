use std::path::PathBuf;

use anyhow::Result;
use posthog_symbol_data::{write_symbol_data, ProguardMapping};

use crate::{files::SourceFile, upload::SymbolSetUpload};

pub struct ProguardFile {
    pub inner: SourceFile<String>,
    pub release_id: Option<String>,
    pub map_id: String,
}

impl ProguardFile {
    pub fn new(path: &PathBuf, map_id: String) -> Result<Self> {
        let inner: SourceFile<String> = SourceFile::load(path)?;

        if !is_valid_mapping(inner.content.as_bytes()) {
            anyhow::bail!(
                "File at {} is not a valid proguard mapping file",
                path.display()
            )
        }

        Ok(Self {
            inner,
            release_id: None,
            map_id,
        })
    }
}

/// Whether the bytes are a ProGuard or R8 mapping. The check works on bytes, so a caller that
/// reports a file that is not UTF-8 apart from one that is not a mapping decodes it first.
pub fn is_valid_mapping(content: &[u8]) -> bool {
    proguard::ProguardMapping::new(content).is_valid()
}

/// The symbol set container for a mapping file. The content goes in as it is on disk: a byte
/// order mark or CRLF line endings stay, because the content hash covers them.
pub fn mapping_container(content: String) -> Result<Vec<u8>> {
    Ok(write_symbol_data(ProguardMapping { content })?)
}

impl TryInto<SymbolSetUpload> for ProguardFile {
    type Error = anyhow::Error;

    fn try_into(self) -> Result<SymbolSetUpload> {
        let inner = self.inner;

        let data = mapping_container(inner.content)?;

        Ok(SymbolSetUpload {
            chunk_id: self.map_id,
            release_id: self.release_id,
            data,
            content_hash: None,
        })
    }
}
