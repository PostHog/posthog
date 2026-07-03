//! Measure candidate cv re-compression codecs/levels on the real decompressed cv payloads from
//! the prod corpus (/tmp/prod-payloads, see prod_bench.rs). Compression of changed payloads is
//! the single largest cost in the whole pipeline (~29% of profile samples at gzip level 6), so
//! this quantifies the two knobs: gzip level, and switching the emitted format entirely (zstd) —
//! the SDK input stays gzip either way; only what we re-emit is in question, and the sole
//! consumer of these blocks is the ML training prep pipeline.
//!
//! Run: cargo run --release --example compression_bench -p replay-anonymizer-node

use std::time::Instant;

use replay_anonymizer_node::gzip;
use serde_json::Value;

/// Latin-1 wire format: each gzip byte stored as its U+00XX codepoint.
fn latin1_to_bytes(s: &str) -> Option<Vec<u8>> {
    let mut out = Vec::with_capacity(s.len());
    for c in s.chars() {
        let cp = c as u32;
        if cp > 0xFF {
            return None;
        }
        out.push(cp as u8);
    }
    Some(out)
}

fn collect_gz_string(v: Option<&Value>, out: &mut Vec<Vec<u8>>) {
    let Some(s) = v.and_then(Value::as_str) else {
        return;
    };
    if s.is_empty() {
        return;
    }
    if let Some(payload) = latin1_to_bytes(s).and_then(|raw| gzip::gunzip(&raw).ok()) {
        out.push(payload);
    }
}

/// Pull every decompressed cv payload (full-snapshot blobs and mutation sub-fields) out of the
/// corpus — exactly the inputs the scrubber re-compresses when it changes them.
fn collect_cv_payloads() -> Vec<Vec<u8>> {
    let mut paths: Vec<_> = std::fs::read_dir("/tmp/prod-payloads")
        .expect("run the fetch script first")
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().map(|x| x == "bin").unwrap_or(false))
        .collect();
    paths.sort();

    let mut payloads = Vec::new();
    for path in paths {
        let bytes = std::fs::read(&path).unwrap();
        let Ok(envelope) = serde_json::from_slice::<Value>(&bytes) else {
            continue;
        };
        let Some(data) = envelope["data"].as_str() else {
            continue;
        };
        let Ok(message) = serde_json::from_str::<Value>(data) else {
            continue;
        };
        let Some(events) = message["properties"]["$snapshot_items"].as_array() else {
            continue;
        };
        for event in events {
            if event["cv"].is_null() {
                continue;
            }
            match event["type"].as_u64() {
                Some(2) => collect_gz_string(Some(&event["data"]), &mut payloads),
                Some(3) => {
                    for key in ["texts", "attributes", "adds"] {
                        collect_gz_string(event["data"].get(key), &mut payloads);
                    }
                }
                _ => {}
            }
        }
    }
    payloads
}

struct Row {
    label: String,
    compress_mb_s: f64,
    decompress_mb_s: f64,
    ratio: f64,
}

fn bench<C, D>(label: &str, payloads: &[Vec<u8>], total_mb: f64, mut compress: C, mut decompress: D) -> Row
where
    C: FnMut(&[u8]) -> Vec<u8>,
    D: FnMut(&[u8], usize) -> Vec<u8>,
{
    // Aim for ~128 MB through each codec (capped at 64 rounds) so small samples still time stably.
    let rounds = ((128.0 / total_mb).ceil() as usize).clamp(1, 64);

    // Warmup round, then timed rounds.
    for p in payloads {
        std::hint::black_box(compress(p));
    }
    let t0 = Instant::now();
    let mut out_bytes = 0usize;
    let mut compressed: Vec<Vec<u8>> = Vec::new();
    for round in 0..rounds {
        out_bytes = 0;
        let round_out: Vec<Vec<u8>> = payloads
            .iter()
            .map(|p| {
                let c = compress(p);
                out_bytes += c.len();
                c
            })
            .collect();
        if round == 0 {
            compressed = round_out;
        }
    }
    let c_secs = t0.elapsed().as_secs_f64() / rounds as f64;

    let t1 = Instant::now();
    for _ in 0..rounds {
        for (c, p) in compressed.iter().zip(payloads) {
            std::hint::black_box(decompress(c, p.len()));
        }
    }
    let d_secs = t1.elapsed().as_secs_f64() / rounds as f64;

    let in_bytes: usize = payloads.iter().map(Vec::len).sum();
    Row {
        label: label.to_string(),
        compress_mb_s: total_mb / c_secs,
        decompress_mb_s: total_mb / d_secs,
        ratio: out_bytes as f64 / in_bytes as f64,
    }
}

fn main() {
    let mut payloads = collect_cv_payloads();
    // Even-stride sample down to ~1k payloads: keeps the size mix (sub-KB mutation fields through
    // multi-MB snapshots) while making the slow codec levels tolerable; the timed loop below runs
    // enough rounds over the sample for stable rates.
    const SAMPLE: usize = 1000;
    if payloads.len() > SAMPLE {
        let stride = payloads.len() / SAMPLE;
        payloads = payloads
            .into_iter()
            .step_by(stride)
            .take(SAMPLE)
            .collect();
    }
    let in_bytes: usize = payloads.iter().map(Vec::len).sum();
    let total_mb = in_bytes as f64 / (1024.0 * 1024.0);
    let mut sizes: Vec<usize> = payloads.iter().map(Vec::len).collect();
    sizes.sort_unstable();
    println!(
        "{} cv payloads, {total_mb:.0} MB decompressed | sizes p50 {} B, p95 {} B, max {} KB\n",
        payloads.len(),
        sizes[sizes.len() / 2],
        sizes[sizes.len() * 95 / 100],
        sizes.last().unwrap() / 1024,
    );

    let mut rows = Vec::new();

    for level in [1, 3, 6, 9, 12] {
        let lvl = libdeflater::CompressionLvl::new(level).unwrap();
        rows.push(bench(
            &format!("gzip (libdeflate) -{level}"),
            &payloads,
            total_mb,
            |p| {
                let mut c = libdeflater::Compressor::new(lvl);
                let mut out = vec![0u8; c.gzip_compress_bound(p.len())];
                let n = c.gzip_compress(p, &mut out).unwrap();
                out.truncate(n);
                out
            },
            |c, hint| {
                let mut d = libdeflater::Decompressor::new();
                let mut out = vec![0u8; hint];
                let n = d.gzip_decompress(c, &mut out).unwrap();
                out.truncate(n);
                out
            },
        ));
    }

    for level in [1, 3, 6, 12, 19] {
        rows.push(bench(
            &format!("zstd -{level}"),
            &payloads,
            total_mb,
            |p| zstd::bulk::compress(p, level).unwrap(),
            |c, hint| zstd::bulk::decompress(c, hint + 64).unwrap(),
        ));
    }

    rows.push(bench(
        "lz4 block (reference floor)",
        &payloads,
        total_mb,
        |p| lz4::block::compress(p, None, true).unwrap(),
        |c, _| lz4::block::decompress(c, None).unwrap(),
    ));

    println!(
        "{:<28} {:>14} {:>16} {:>8}",
        "codec", "compress MB/s", "decompress MB/s", "ratio"
    );
    for r in &rows {
        println!(
            "{:<28} {:>14.0} {:>16.0} {:>8.3}",
            r.label, r.compress_mb_s, r.decompress_mb_s, r.ratio
        );
    }
}
