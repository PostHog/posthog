use anyhow::{anyhow, bail, Ok, Result};
use core::str;
use magic_string::{GenerateDecodedMapOptions, MagicString};
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sourcemap::SourceMap;
use std::collections::BTreeMap;
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
};
use tracing::{info, warn};
use walkdir::WalkDir;

use super::constant::{CHUNKID_COMMENT_PREFIX, CHUNKID_PLACEHOLDER, CODE_SNIPPET_TEMPLATE};

pub struct SourceFile {
    pub path: PathBuf,
    pub content: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SourceMapChunkId {
    chunk_id: Option<String>,
    #[serde(flatten)]
    fields: BTreeMap<String, Value>,
}

impl SourceFile {
    pub fn new(path: PathBuf, content: String) -> Self {
        SourceFile { path, content }
    }

    pub fn load(path: &PathBuf) -> Result<Self> {
        let content = std::fs::read_to_string(path)?;
        Ok(SourceFile::new(path.clone(), content))
    }

    pub fn save(&self, dest: Option<PathBuf>) -> Result<()> {
        let final_path = dest.unwrap_or(self.path.clone());
        std::fs::write(&final_path, &self.content)?;
        Ok(())
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SourceMapContent {
    chunk_id: Option<String>,
    #[serde(flatten)]
    fields: HashMap<String, Value>,
}

pub struct SourcePair {
    pub chunk_id: Option<String>,

    pub source: SourceFile,
    pub sourcemap: SourceFile,
}

pub struct ChunkUpload {
    pub chunk_id: String,
    pub data: Vec<u8>,
}

impl SourcePair {
    pub fn set_chunk_id(&mut self, chunk_id: String) -> Result<()> {
        if self.chunk_id.is_some() {
            return Err(anyhow!("Chunk ID already set"));
        }
        let (new_source_content, source_adjustment) = {
            // Update source content with chunk ID
            let source_content = &self.source.content;
            let mut magic_source = MagicString::new(source_content);
            let code_snippet = CODE_SNIPPET_TEMPLATE.replace(CHUNKID_PLACEHOLDER, &chunk_id);
            magic_source
                .prepend(&code_snippet)
                .map_err(|err| anyhow!("Failed to prepend code snippet: {}", err))?;
            let chunk_comment = CHUNKID_COMMENT_PREFIX.replace(CHUNKID_PLACEHOLDER, &chunk_id);
            magic_source
                .append(&chunk_comment)
                .map_err(|err| anyhow!("Failed to append chunk comment: {}", err))?;
            let adjustment = magic_source
                .generate_map(GenerateDecodedMapOptions {
                    include_content: true,
                    ..Default::default()
                })
                .map_err(|err| anyhow!("Failed to generate source map: {}", err))?;
            let adjustment_sourcemap = SourceMap::from_slice(
                adjustment
                    .to_string()
                    .map_err(|err| anyhow!("Failed to serialize source map: {}", err))?
                    .as_bytes(),
            )
            .map_err(|err| anyhow!("Failed to parse adjustment sourcemap: {}", err))?;
            (magic_source.to_string(), adjustment_sourcemap)
        };

        let new_sourcemap = {
            // Update the sourcemap with the new mappings
            let mut original_sourcemap =
                SourceMap::from_slice(self.sourcemap.content.as_bytes())
                    .map_err(|err| anyhow!("Failed to parse sourcemap: {}", err))?;
            original_sourcemap.adjust_mappings(&source_adjustment);

            let mut new_sourcemap_bytes = Vec::new();
            original_sourcemap.to_writer(&mut new_sourcemap_bytes)?;

            let mut sourcemap_chunk: SourceMapChunkId =
                serde_json::from_slice(&new_sourcemap_bytes)?;
            sourcemap_chunk.chunk_id = Some(chunk_id.clone());
            sourcemap_chunk
        };

        self.chunk_id = Some(chunk_id.clone());
        self.source.content = new_source_content;
        self.sourcemap.content = serde_json::to_string(&new_sourcemap)?;
        Ok(())
    }

    pub fn save(&self) -> Result<()> {
        self.source.save(None)?;
        self.sourcemap.save(None)?;
        Ok(())
    }

    pub fn into_chunk_upload(self) -> Result<ChunkUpload> {
        let chunk_id = self.chunk_id.ok_or_else(|| anyhow!("Chunk ID not found"))?;
        let source_content = self.source.content;
        let sourcemap_content = self.sourcemap.content;
        let data = SourceAndMap {
            minified_source: source_content,
            sourcemap: sourcemap_content,
        };
        let data = write_symbol_data(data)?;
        Ok(ChunkUpload { chunk_id, data })
    }
}

pub fn read_pairs(directory: &PathBuf) -> Result<Vec<SourcePair>> {
    // Make sure the directory exists
    if !directory.exists() {
        bail!("Directory does not exist");
    }

    let mut pairs = Vec::new();
    for entry in WalkDir::new(directory).into_iter().filter_map(|e| e.ok()) {
        let entry_path = entry.path().canonicalize()?;
        info!("Processing file: {}", entry_path.display());
        if is_javascript_file(&entry_path) {
            let source = SourceFile::load(&entry_path)?;
            let sourcemap_path = guess_sourcemap_path(&source.path);
            if sourcemap_path.exists() {
                let sourcemap = SourceFile::load(&sourcemap_path)?;
                let chunk_id = get_chunk_id(&sourcemap);
                pairs.push(SourcePair {
                    chunk_id,
                    source,
                    sourcemap,
                });
            } else {
                warn!("No sourcemap file found for file {}", entry_path.display());
            }
        }
    }
    Ok(pairs)
}

pub fn get_chunk_id(sourcemap: &SourceFile) -> Option<String> {
    #[derive(Deserialize)]
    struct SourceChunkId {
        chunk_id: String,
    }
    serde_json::from_str(&sourcemap.content)
        .map(|chunk_id: SourceChunkId| chunk_id.chunk_id)
        .ok()
}

pub fn guess_sourcemap_path(path: &Path) -> PathBuf {
    // Try to resolve the sourcemap by adding .map to the path
    let mut sourcemap_path = path.to_path_buf();
    match path.extension() {
        Some(ext) => sourcemap_path.set_extension(format!("{}.map", ext.to_string_lossy())),
        None => sourcemap_path.set_extension("map"),
    };
    sourcemap_path
}

fn is_javascript_file(path: &Path) -> bool {
    path.extension()
        .map_or(false, |ext| ext == "js" || ext == "mjs" || ext == "cjs")
}
