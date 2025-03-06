use core::str;
use std::{collections::HashMap, path::PathBuf};

use anyhow::{anyhow, Context, Error, Ok};
use common_symbol_data::{write_symbol_data, SourceAndMap};
use tracing::info;

use super::auth::load_token;

pub struct JsFilePair {
    minified: PathBuf,
    source_map: PathBuf,
}

pub struct ChunkUpload {
    chunk_id: String,
    data: Vec<u8>,
}

pub fn upload(host: &str, directory: &str, _build_id: &Option<String>) -> Result<(), Error> {
    let token = load_token().context("While starting upload command")?;

    let url = format!(
        "{}/api/projects/{}/error_tracking/symbol_sets",
        host, token.env_id
    );

    let files = std::fs::read_dir(directory)
        .context(format!("While reading directory {}", directory))?
        .map(|entry| entry.map(|e| e.path()))
        .collect::<Result<Vec<_>, std::io::Error>>()
        .context(format!("While reading directory {}", directory))?;

    let pairs = collect_files_to_pairs(files).context(format!(
        "While collecting files to minified source : map pairs"
    ))?;

    let uploads = collect_uploads(pairs).context("While preparing files for upload")?;
    info!("Found {} chunks to upload", uploads.len());

    upload_chunks(&url, &token.token, uploads)?;

    Ok(())
}

// We want to collect to pairs of `<file>` and `<file>.map` files
pub fn collect_files_to_pairs(files: Vec<PathBuf>) -> Result<HashMap<String, JsFilePair>, Error> {
    let mut collected: HashMap<String, Vec<PathBuf>> = HashMap::new();
    for file in files {
        let key = file
            .file_stem()
            .ok_or_else(|| anyhow!("Could not get file stem for {:?}", file))?
            .to_string_lossy()
            .to_string();
        let value = collected.entry(key).or_insert_with(Vec::new);
        value.push(file);
    }

    let mut pairs = HashMap::new();

    for (key, value) in collected {
        if value.len() == 1 {
            return Err(anyhow!("Found orphan file: {:?}", value[0]));
        }

        if value.len() > 2 {
            return Err(anyhow!(
                "Found more than two files for key: {:?}, {:?}",
                key,
                value
            ));
        }

        let mut minified = None;
        let mut source_map = None;

        for file in &value {
            if file.extension().map(|e| e == "map").unwrap_or(false) {
                source_map = Some(file);
            } else {
                minified = Some(file);
            }
        }

        if let (Some(minified), Some(source_map)) = (minified, source_map) {
            pairs.insert(
                key,
                JsFilePair {
                    minified: minified.clone(),
                    source_map: source_map.clone(),
                },
            );
        } else {
            return Err(anyhow!(
                "Found a file file pair where neither looks like a sourcemap: {:?}, {:?}",
                value[0],
                value[1]
            ));
        }
    }

    Ok(pairs)
}

fn collect_uploads(pairs: HashMap<String, JsFilePair>) -> Result<Vec<ChunkUpload>, Error> {
    let mut uploads = Vec::new();
    for pair in pairs {
        let (_, pair) = pair;
        let sourcemap = str::from_utf8(&std::fs::read(pair.source_map)?)?.to_string();
        let chunk_id = get_chunk_id(&sourcemap)?;
        let data = SourceAndMap {
            minified_source: str::from_utf8(&std::fs::read(pair.minified)?)?.to_string(),
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
