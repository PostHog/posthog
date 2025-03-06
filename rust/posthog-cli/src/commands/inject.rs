use anyhow::{Ok, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::HashMap, path::PathBuf};
use uuid;
pub struct Source(pub String);

#[derive(Debug, Serialize, Deserialize)]
pub struct SourceMap {
    chunk_id: Option<String>,
    #[serde(flatten)]
    fields: HashMap<String, Value>,
}

pub struct SourcePair {
    source: Source,
    sourcemap: SourceMap,
    debug_id: String,
}

pub fn inject(directory: PathBuf, debug_id: String) -> Result<()> {
    // Find js sources and sourcemaps.
    Ok(())
}

fn find_pair(directory: PathBuf) -> Result<Vec<SourcePair>> {
    // Make sure the directory exists
    if !directory.exists() {
        return Err(anyhow::anyhow!("Directory does not exist"));
    }

    let mut pairs = Vec::new();
    for entry in std::fs::read_dir(directory)? {
        let entry = entry?;

        if is_sourcemap(&entry.path()) {
            let js_path = entry.path().with_extension("js");
            if js_path.exists() {
                let source = Source(js_path.to_string_lossy().to_string());
                let sourcemap = serde_json::from_slice(&std::fs::read(entry.path())?)?;
                let debug_id = uuid::Uuid::new_v4().to_string();
                let pair = SourcePair {
                    source,
                    sourcemap,
                    debug_id: debug_id.clone(),
                };
                pairs.push(pair);
            }
        }
    }

    Ok(pairs)

    // Find js sources and sourcemaps.
    Ok(vec![])
}

fn is_source(path: &PathBuf) -> bool {
    path.extension().map_or(false, |ext| ext == "js")
}

fn is_sourcemap(path: &PathBuf) -> bool {
    path.extension().map_or(false, |ext| ext == "js.map")
}

fn inject_sourcemap(sourcemap_path: PathBuf, debug_id: String) -> Result<()> {
    // Find js sources and sourcemaps.
    Ok(())
}

fn inject_source(source_path: PathBuf, debug_id: String) -> Result<()> {
    // Find js sources and sourcemaps.
    Ok(())
}
