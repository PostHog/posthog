use core::str;
use std::path::PathBuf;

use anyhow::{anyhow, Context, Error, Ok};
use common_symbol_data::{write_symbol_data, SourceAndMap};
use tracing::info;

use crate::commands::inject::read_pairs;

use super::{auth::load_token, inject::SourcePair};

pub struct ChunkUpload {
    chunk_id: String,
    data: Vec<u8>,
}

pub fn upload(host: &str, directory: &PathBuf, _build_id: &Option<String>) -> Result<(), Error> {
    let token = load_token().context("While starting upload command")?;

    let url = format!(
        "{}/api/projects/{}/error_tracking/symbol_sets",
        host, token.env_id
    );

    let pairs = read_pairs(directory)?;

    let uploads = collect_uploads(pairs).context("While preparing files for upload")?;
    info!("Found {} chunks to upload", uploads.len());

    upload_chunks(&url, &token.token, uploads)?;

    Ok(())
}

fn collect_uploads(pairs: Vec<SourcePair>) -> Result<Vec<ChunkUpload>, Error> {
    let mut uploads = Vec::new();
    for pair in pairs {
        let sourcemap = str::from_utf8(&std::fs::read(pair.sourcemap.path)?)?.to_string();
        let chunk_id = get_chunk_id(&sourcemap)?;
        let data = SourceAndMap {
            minified_source: pair.source.content,
            sourcemap,
        };

        let bytes = write_symbol_data(data)?;

        let upload = ChunkUpload {
            chunk_id,
            data: bytes,
        };

        uploads.push(upload);
    }

    return Ok(uploads);
}

fn get_chunk_id(sourcemap: &str) -> Result<String, Error> {
    #[derive(serde::Deserialize)]
    struct S {
        debug_id: String,
    }

    let s: S = serde_json::from_str(sourcemap).context("While getting chunk id")?;
    Ok(s.debug_id)
}

fn upload_chunks(url: &str, token: &str, uploads: Vec<ChunkUpload>) -> Result<(), Error> {
    let client = reqwest::blocking::Client::new();
    for upload in uploads {
        info!("Uploading chunk {}", upload.chunk_id);
        let res = client
            .post(url)
            .header("Authorization", format!("Bearer {}", token))
            .query(&[("chunk_id", &upload.chunk_id)])
            .body(upload.data)
            .send()
            .context(format!("While uploading chunk to {}", url))?;

        if !res.status().is_success() {
            return Err(anyhow!("Failed to upload chunk: {:?}", res)
                .context(format!("Chunk id: {}", upload.chunk_id)));
        }
    }

    Ok(())
}
