use anyhow::{anyhow, bail, Error, Ok, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
};
use tracing::info;
use uuid;

pub struct Source {
    path: PathBuf,
    content: String,
}

impl Source {
    pub fn get_sourcemap_path(&self) -> PathBuf {
        // Try to resolve the sourcemap by adding .map to the path
        let mut path = self.path.clone();
        path.push(".map");
        path
    }

    pub fn add_chunk_id(&mut self, chunk_id: String) {
        self.prepend(format!(r#"!function(){{try{{var e="undefined"!=typeof window?window:"undefined"!=typeof global?global:"undefined"!=typeof self?self:{{}},n=(new e.Error).stack;n&&(e._posthogChunkIds=e._posthogChunkIds||{{}},e._posthogChunkIds[n]="{}")}}catch(e){{}}}}();"#, chunk_id));
        self.append(format!(r#"//# chunkId={}\n"#, chunk_id));
    }

    pub fn read(path: &PathBuf) -> Result<Source> {
        let content = std::fs::read_to_string(path)?;
        Ok(Source {
            path: path.clone(),
            content,
        })
    }

    pub fn write(&self) -> Result<()> {
        std::fs::write(&self.path, &self.content)?;
        Ok(())
    }

    pub fn prepend(&mut self, prefix: String) {
        self.content = format!("{}{}", prefix, self.content);
    }

    pub fn append(&mut self, suffix: String) {
        self.content = format!("{}{}", self.content, suffix);
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SourceMapContent {
    chunk_id: Option<String>,
    #[serde(flatten)]
    fields: HashMap<String, Value>,
}

#[derive(Debug)]
pub struct SourceMap {
    path: PathBuf,
    content: SourceMapContent,
}

impl SourceMap {
    pub fn add_chunk_id(&mut self, chunk_id: String) -> Result<()> {
        if self.content.chunk_id.is_some() {
            return Err(anyhow::anyhow!("Sourcemap has already been processed"));
        }
        self.content.chunk_id = Some(chunk_id);
        Ok(())
    }

    pub fn read(path: &PathBuf) -> Result<SourceMap> {
        let content = serde_json::from_slice(&std::fs::read(path)?)?;
        Ok(SourceMap {
            path: path.clone(),
            content,
        })
    }

    pub fn write(&self) -> Result<()> {
        std::fs::write(&self.path, serde_json::to_string_pretty(&self.content)?)?;
        Ok(())
    }
}

pub struct SourcePair {
    source: Source,
    sourcemap: SourceMap,
}

impl SourcePair {
    pub fn add_chunk_id(&mut self, chunk_id: String) -> Result<()> {
        self.source.add_chunk_id(chunk_id.clone());
        self.sourcemap.add_chunk_id(chunk_id)?;
        Ok(())
    }

    pub fn write(&self) -> Result<()> {
        self.source.write()?;
        self.sourcemap.write()?;
        Ok(())
    }
}

pub fn process_directory(directory: &Path) -> Result<()> {
    // Resolve directory path
    let directory = directory.canonicalize()?;
    info!("Processing directory: {}", directory.display());
    let mut pairs = read_pairs(&directory)?;
    if pairs.is_empty() {
        return Err(anyhow!("No source files found"));
    }
    for pair in &mut pairs {
        let chunk_id = uuid::Uuid::now_v7().to_string();
        pair.add_chunk_id(chunk_id)?;
    }

    // Write the source and sourcemaps back to disk
    for pair in &pairs {
        pair.write()?;
    }

    Ok(())
}

fn read_pairs(directory: &PathBuf) -> Result<Vec<SourcePair>> {
    // Make sure the directory exists
    if !directory.exists() {
        return Err(anyhow!("Directory does not exist"));
    }

    let mut pairs = Vec::new();
    for entry in std::fs::read_dir(directory)? {
        let entry_path = entry?.path().canonicalize()?;
        if is_javascript_file(&entry_path) {
            let source = Source::read(&entry_path).map_err(|_| {
                Error::msg(format!(
                    "Failed to read source file: {}",
                    entry_path.display()
                ))
            })?;
            let sourcemap_path = source.get_sourcemap_path();
            if sourcemap_path.exists() {
                let sourcemap = SourceMap::read(&sourcemap_path)?;
                pairs.push(SourcePair { source, sourcemap });
            } else {
                bail!("No sourcemap file found for file {}", entry_path.display());
            }
        }
    }

    Ok(pairs)
}

fn is_javascript_file(path: &Path) -> bool {
    path.extension().map_or(false, |ext| ext == "js")
}
