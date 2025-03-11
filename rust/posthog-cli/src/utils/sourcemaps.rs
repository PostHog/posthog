use anyhow::{anyhow, bail, Context, Ok, Result};
use common_symbol_data::{write_symbol_data, SourceAndMap};
use core::str;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
};
use tracing::{info, warn};
use walkdir::WalkDir;

pub struct Source {
    path: PathBuf,
    pub content: String,
}

impl Source {
    pub fn get_sourcemap_path(&self) -> PathBuf {
        // Try to resolve the sourcemap by adding .map to the path
        let mut path = self.path.clone();
        match path.extension() {
            Some(ext) => path.set_extension(format!("{}.map", ext.to_string_lossy())),
            None => path.set_extension("map"),
        };
        path
    }

    pub fn add_chunk_id(&mut self, chunk_id: String) {
        self.prepend(&format!(r#"!function(){{try{{var e="undefined"!=typeof window?window:"undefined"!=typeof global?global:"undefined"!=typeof self?self:{{}},n=(new e.Error).stack;n&&(e._posthogChunkIds=e._posthogChunkIds||{{}},e._posthogChunkIds[n]="{}")}}catch(e){{}}}}();"#, chunk_id));
        self.append(&format!(r#"//# chunkId={}"#, chunk_id));
    }

    pub fn read(path: &PathBuf) -> Result<Source> {
        let content = std::fs::read_to_string(path)
            .map_err(|_| anyhow!("Failed to read source file: {}", path.display()))?;
        Ok(Source {
            path: path.clone(),
            content,
        })
    }

    pub fn write(&self) -> Result<()> {
        std::fs::write(&self.path, &self.content)?;
        Ok(())
    }

    pub fn prepend(&mut self, prefix: &str) {
        self.content.insert_str(0, prefix);
    }

    pub fn append(&mut self, suffix: &str) {
        self.content.push_str(&suffix);
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
    pub path: PathBuf,
    content: SourceMapContent,
}

impl SourceMap {
    pub fn add_chunk_id(&mut self, chunk_id: String) -> Result<()> {
        if self.content.chunk_id.is_some() {
            bail!("Sourcemap has already been processed");
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
        std::fs::write(&self.path, self.to_string()?)?;
        Ok(())
    }

    pub fn chunk_id(&self) -> Option<String> {
        self.content.chunk_id.clone()
    }

    pub fn to_string(&self) -> Result<String> {
        serde_json::to_string(&self.content)
            .map_err(|e| anyhow!("Failed to serialize sourcemap content: {}", e))
    }
}

pub struct SourcePair {
    pub source: Source,
    pub sourcemap: SourceMap,
}

pub struct ChunkUpload {
    pub chunk_id: String,
    pub data: Vec<u8>,
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

    pub fn chunk_id(&self) -> Option<String> {
        self.sourcemap.chunk_id()
    }

    pub fn into_chunk_upload(self) -> Result<ChunkUpload> {
        let chunk_id = self
            .chunk_id()
            .ok_or_else(|| anyhow!("Chunk ID not found"))?;
        let sourcemap_content = self
            .sourcemap
            .to_string()
            .context("Failed to serialize sourcemap")?;
        let data = SourceAndMap {
            minified_source: self.source.content,
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
            let source = Source::read(&entry_path)?;
            let sourcemap_path = source.get_sourcemap_path();
            if sourcemap_path.exists() {
                let sourcemap = SourceMap::read(&sourcemap_path)?;
                pairs.push(SourcePair { source, sourcemap });
            } else {
                warn!("No sourcemap file found for file {}", entry_path.display());
            }
        }
    }
    Ok(pairs)
}

fn is_javascript_file(path: &Path) -> bool {
    path.extension()
        .map_or(false, |ext| ext == "js" || ext == "mjs" || ext == "cjs")
}

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::{Context, Result};
    use std::fs::File;
    use std::io::Write;
    use tempfile::{tempdir, TempDir};
    use test_log::test;
    use tracing::info;

    fn create_pair(dir: &TempDir, path: &str, pair_name: &str, extension: &str) -> Result<()> {
        let sub_path = dir.path().join(path);
        if !sub_path.exists() {
            std::fs::create_dir_all(&sub_path)?;
        }
        let js_path = sub_path.join(format!("{}.{}", pair_name, extension));
        info!("Creating file: {:?}", js_path);
        let mut file = File::create(&js_path).context("Failed to create file")?;
        let map_path = sub_path.join(format!("{}.{}.{}", pair_name, extension, "map"));
        let mut map_file = File::create(&map_path).context("Failed to create map")?;
        writeln!(file, "console.log('hello');").context("Failed to write to file")?;
        writeln!(map_file, "{{}}").context("Failed to write to file")?;
        Ok(())
    }

    fn setup_test_directory() -> Result<TempDir> {
        let dir = tempdir()?;
        create_pair(&dir, "", "regular", "js")?;
        create_pair(&dir, "assets", "module", "mjs")?;
        create_pair(&dir, "assets/sub", "common", "cjs")?;
        Ok(dir)
    }

    #[test]
    fn test_tempdir_creation() {
        let dist_dir = setup_test_directory().unwrap();
        assert!(dist_dir.path().exists());
        let dist_dir_path = dist_dir.path().to_path_buf();
        let pairs = read_pairs(&dist_dir_path).expect("Failed to read pairs");
        assert_eq!(pairs.len(), 3);
    }
}
