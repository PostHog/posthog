//! One-shot gzip codec on libdeflate. ~2-3x the throughput of the streaming flate2 legs this
//! replaced, at the cost of needing the output size up front — which gzip already carries in its
//! ISIZE footer.

use std::cell::RefCell;

use anyhow::{anyhow, bail, Result};
use libdeflater::{CompressionLvl, Compressor, Decompressor};

/// Cap decompressed sizes so a gzip bomb (or a forged ISIZE footer) can't OOM the worker thread;
/// real replay payloads decompress to tens of MB at most.
pub const MAX_DECOMPRESSED_BYTES: usize = 256 * 1024 * 1024;

thread_local! {
    // libdeflate (de)compressor states are one-time ~50-300 KB mallocs; cv work runs per
    // sub-field (several calls per event), so reuse them per thread instead of paying the
    // allocation on every call. The state carries nothing across calls.
    static DECOMPRESSOR: RefCell<Decompressor> = RefCell::new(Decompressor::new());
    static COMPRESSOR: RefCell<Compressor> =
        RefCell::new(Compressor::new(CompressionLvl::default()));
}

/// Gunzip a single-member stream. The output buffer is sized exactly from the stream's ISIZE
/// footer (uncompressed length mod 2^32, RFC 1952), so both footer lies fail closed: claiming
/// more than [`MAX_DECOMPRESSED_BYTES`] is rejected before allocating, and claiming less than the
/// real size makes libdeflate stop at the buffer end with `InsufficientSpace`.
pub fn gunzip(raw: &[u8]) -> Result<Vec<u8>> {
    let Some(footer) = raw.len().checked_sub(4).map(|start| &raw[start..]) else {
        bail!("gzip stream too short");
    };
    let hint = u32::from_le_bytes(footer.try_into().expect("4-byte slice")) as usize;
    if hint > MAX_DECOMPRESSED_BYTES {
        bail!("gzip uncompressed size exceeds limit");
    }
    let mut out = vec![0u8; hint];
    let n = DECOMPRESSOR
        .with(|d| d.borrow_mut().gzip_decompress(raw, &mut out))
        .map_err(|e| anyhow!("gunzip: {e:?}"))?;
    out.truncate(n);
    Ok(out)
}

/// Gzip `payload` as one default-level (6, matching both flate2's default and the TS pipeline's
/// pako default) member.
pub fn gzip(payload: &[u8]) -> Result<Vec<u8>> {
    COMPRESSOR.with(|c| {
        let mut c = c.borrow_mut();
        let mut out = vec![0u8; c.gzip_compress_bound(payload.len())];
        let n = c
            .gzip_compress(payload, &mut out)
            .map_err(|e| anyhow!("gzip: {e:?}"))?;
        out.truncate(n);
        Ok(out)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};

    #[test]
    fn round_trips_through_an_independent_codec() {
        let payload = b"hello hello hello compression".repeat(50);

        // Ours -> flate2: the member we emit must be a standard gzip stream.
        let ours = gzip(&payload).unwrap();
        let mut via_flate2 = Vec::new();
        flate2::read::GzDecoder::new(&ours[..])
            .read_to_end(&mut via_flate2)
            .unwrap();
        assert_eq!(via_flate2, payload);

        // flate2 -> ours: we must decode members other encoders produced.
        let mut enc =
            flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        enc.write_all(&payload).unwrap();
        let theirs = enc.finish().unwrap();
        assert_eq!(gunzip(&theirs).unwrap(), payload);
    }

    #[test]
    fn rejects_a_footer_claiming_more_than_the_cap() {
        // A syntactically real stream whose ISIZE footer is forged upward must be rejected
        // before any allocation happens (the pre-libdeflate code streamed up to the cap instead).
        let mut stream = gzip(b"small").unwrap();
        let n = stream.len();
        stream[n - 4..].copy_from_slice(&(u32::MAX).to_le_bytes());
        let err = gunzip(&stream).unwrap_err().to_string();
        assert!(err.contains("exceeds limit"), "got: {err}");
    }

    #[test]
    fn fails_closed_on_a_footer_claiming_less_than_the_real_size() {
        // ISIZE forged downward: the exact-sized buffer runs out mid-stream and libdeflate
        // reports it, rather than silently truncating the payload.
        let payload = b"0123456789".repeat(100);
        let mut stream = gzip(&payload).unwrap();
        let n = stream.len();
        stream[n - 4..].copy_from_slice(&8u32.to_le_bytes());
        assert!(gunzip(&stream).is_err());
    }

    #[test]
    fn rejects_truncated_and_empty_streams() {
        assert!(gunzip(b"").is_err());
        assert!(gunzip(&[0x1f, 0x8b, 0x08]).is_err());
    }
}
