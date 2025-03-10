use anyhow::{anyhow, Ok, Result};
use std::path::{Path, PathBuf};
use tracing::info;
use uuid;

use crate::utils::sourcemaps::read_pairs;

pub fn inject(directory: &Path, _output: &Option<PathBuf>) -> Result<()> {
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
