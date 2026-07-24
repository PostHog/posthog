//! Minimal .npy reader for float32 C-order 2-D matrices (the lab's embedding cache).

use anyhow::{bail, Context, Result};
use std::fs::File;
use std::io::Read;

pub struct Matrix {
    pub data: Vec<f32>,
    pub rows: usize,
    pub cols: usize,
}

impl Matrix {
    #[inline]
    pub fn row(&self, i: usize) -> &[f32] {
        &self.data[i * self.cols..(i + 1) * self.cols]
    }
}

pub fn read_npy_f32(path: &str) -> Result<Matrix> {
    let mut f = File::open(path).with_context(|| format!("open {path}"))?;
    let mut magic = [0u8; 8];
    f.read_exact(&mut magic)?;
    if &magic[..6] != b"\x93NUMPY" {
        bail!("{path}: not an npy file");
    }
    let (major, _minor) = (magic[6], magic[7]);
    let header_len = if major == 1 {
        let mut b = [0u8; 2];
        f.read_exact(&mut b)?;
        u16::from_le_bytes(b) as usize
    } else {
        let mut b = [0u8; 4];
        f.read_exact(&mut b)?;
        u32::from_le_bytes(b) as usize
    };
    let mut header = vec![0u8; header_len];
    f.read_exact(&mut header)?;
    let header = String::from_utf8_lossy(&header);
    if !header.contains("'descr': '<f4'") && !header.contains("\"descr\": \"<f4\"") {
        bail!("{path}: expected <f4 dtype, header: {header}");
    }
    if header.contains("'fortran_order': True") {
        bail!("{path}: fortran order unsupported");
    }
    let shape_part = header
        .split("'shape':")
        .nth(1)
        .context("npy header missing shape")?;
    let open = shape_part.find('(').context("shape paren")?;
    let close = shape_part.find(')').context("shape paren")?;
    let dims: Vec<usize> = shape_part[open + 1..close]
        .split(',')
        .filter_map(|s| s.trim().parse().ok())
        .collect();
    if dims.len() != 2 {
        bail!("{path}: expected 2-D matrix, got {dims:?}");
    }
    let (rows, cols) = (dims[0], dims[1]);
    let mut raw = Vec::with_capacity(rows * cols * 4);
    f.read_to_end(&mut raw)?;
    if raw.len() < rows * cols * 4 {
        bail!(
            "{path}: truncated data ({} < {})",
            raw.len(),
            rows * cols * 4
        );
    }
    let mut data = vec![0f32; rows * cols];
    for (i, chunk) in raw.chunks_exact(4).take(rows * cols).enumerate() {
        data[i] = f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
    }
    Ok(Matrix { data, rows, cols })
}
