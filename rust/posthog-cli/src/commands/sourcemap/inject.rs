use anyhow::{anyhow, bail, Ok, Result};
use std::path::{Path, PathBuf};
use tracing::info;
use uuid;

use crate::utils::sourcemaps::read_pairs;

pub fn inject(directory: &Path, _output: &Option<PathBuf>) -> Result<()> {
    let directory = directory.canonicalize().map_err(|e| {
        anyhow!(
            "Directory '{}' not found or inaccessible: {}",
            directory.display(),
            e
        )
    })?;
    info!("Processing directory: {}", directory.display());
    let mut pairs = read_pairs(&directory)?;
    if pairs.is_empty() {
        bail!("No source files found");
    }
    info!("Found {} pairs", pairs.len());
    for pair in &mut pairs {
        let chunk_id = uuid::Uuid::now_v7().to_string();
        pair.set_chunk_id(chunk_id)?;
    }
    // Write the source and sourcemaps back to disk
    for pair in &pairs {
        pair.save()?;
    }
    info!("Finished processing directory");
    Ok(())
}
