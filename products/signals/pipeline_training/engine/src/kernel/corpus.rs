//! Corpus loading: the engine reads a materialized corpus dir (signals.jsonl + embeddings.npy),
//! produced by the orchestrator's shard-aware, content-hashed corpus materializer.

use anyhow::{bail, Context, Result};
use serde::Deserialize;
use std::io::BufRead;

use crate::npy;

#[derive(Deserialize, Clone)]
pub struct Signal {
    pub id: String,
    pub ts: f64,
    pub content: String,
    pub product: String,
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(default)]
    pub source_id: Option<String>,
}

pub struct Corpus {
    pub signals: Vec<Signal>,
    pub embeddings: Vec<Vec<f32>>, // row-aligned with signals, L2-normalized
    /// raw rows exactly as stored on disk — the classifier/featurize paths
    /// normalize these themselves (feats::normalize, f64 arithmetic) so scores
    /// stay bit-identical to the old replayer
    pub raw: npy::Matrix,
}

impl Corpus {
    pub fn load(dir: &str) -> Result<Self> {
        let sig_path = format!("{dir}/signals.jsonl");
        let file = std::fs::File::open(&sig_path).with_context(|| format!("open {sig_path}"))?;
        let mut signals = Vec::new();
        for line in std::io::BufReader::new(file).lines() {
            let line = line?;
            if line.trim().is_empty() {
                continue;
            }
            signals.push(serde_json::from_str::<Signal>(&line)?);
        }
        let m = npy::read_npy_f32(&format!("{dir}/embeddings.npy"))?;
        if m.rows != signals.len() {
            bail!("embeddings rows {} != signals {}", m.rows, signals.len());
        }
        // L2-normalize rows so cosine = dot
        let mut embeddings = Vec::with_capacity(m.rows);
        for r in 0..m.rows {
            let row = m.row(r);
            let norm = row.iter().map(|x| x * x).sum::<f32>().sqrt().max(1e-12);
            embeddings.push(row.iter().map(|x| x / norm).collect());
        }
        Ok(Self {
            signals,
            embeddings,
            raw: m,
        })
    }
}
