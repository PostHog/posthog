//! One-shot compression codecs: gzip on libdeflate (~2-3x the throughput of the streaming flate2
//! legs it replaced, at the cost of needing the output size up front — which gzip carries in its
//! ISIZE footer), plus the zstd leg that re-emits `cv` payloads.

use std::cell::RefCell;
use std::io::Read;

use anyhow::{anyhow, bail, Result};
use libdeflater::{CompressionLvl, Compressor, Decompressor};

/// Compression-bomb cap: ~6x the 10.3 MB largest payload in a 1000-message production sample.
/// Exceeding it fails closed as a classified DLQ instead of an unclassifiable OOM crash-loop.
pub const MAX_DECOMPRESSED_BYTES: usize = 64 * 1024 * 1024;

/// Leading magic of a gzip member (RFC 1952).
pub const GZIP_MAGIC: [u8; 2] = [0x1f, 0x8b];

/// Leading magic of a zstd frame (RFC 8878).
pub const ZSTD_MAGIC: [u8; 4] = [0x28, 0xb5, 0x2f, 0xfd];

/// zstd level for re-emitted cv payloads. Counterintuitively negative: raw codec ratio is 20%
/// worse than level 1 (0.145 vs 0.121 on the real cv corpus), but these bytes are stored
/// latin-1-in-JSON inside snappy blocks, where entropy-coded output pays twice — high bytes cost
/// 2 UTF-8 bytes each and are incompressible to the block snappy, while the raw ASCII literals
/// negative levels leave behind cost 1 byte and snappy still compresses them. Measured end to
/// end on the corpus, -1 beats 1 on every axis: 3.67 vs 3.88 ms/msg, snappy'd blocks 272.7 vs
/// 289.2 MB, and the loader-side decompress is ~30% faster. Levels below -1 gain nothing.
const CV_ZSTD_LEVEL: i32 = -1;

/// zstd `windowLogMax` cap. The decoder's back-reference window can't exceed our decompressed-size
/// cap (2^26 = 64 MiB), so a frame header declaring a huge `windowLog` can't force an outsized
/// working-buffer allocation before the size cap engages. Real cv payloads sit far below this.
const CV_ZSTD_WINDOW_LOG_MAX: u32 = 26;

thread_local! {
    // Reused per thread: each codec state is a one-time ~50-300 KB malloc and cv work runs several
    // times per event.
    static DECOMPRESSOR: RefCell<Decompressor> = RefCell::new(Decompressor::new());
    static COMPRESSOR: RefCell<Compressor> =
        RefCell::new(Compressor::new(CompressionLvl::default()));
    static ZSTD_COMPRESSOR: RefCell<zstd::bulk::Compressor<'static>> = RefCell::new(
        zstd::bulk::Compressor::new(CV_ZSTD_LEVEL).expect("static zstd level is valid"),
    );
    static ZSTD_DECOMPRESSOR: RefCell<zstd::bulk::Decompressor<'static>> = RefCell::new({
        let mut d = zstd::bulk::Decompressor::new().expect("default zstd decompressor is valid");
        d.set_parameter(zstd::zstd_safe::DParameter::WindowLogMax(CV_ZSTD_WINDOW_LOG_MAX))
            .expect("window log max is a valid decompression parameter");
        d
    });
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

/// Decompress a single zstd frame. Unlike gzip there is no ISIZE trailer: when the frame header
/// declares its content size the output buffer is sized from it (a declaration past
/// [`MAX_DECOMPRESSED_BYTES`] is rejected before allocating), and a frame without one falls back to
/// a streaming decode capped at the same limit.
///
/// The input must be exactly one frame that consumes every byte. Trailing bytes, concatenated
/// frames, and appended skippable frames all decode to less than the input; accepting them would
/// let never-decompressed bytes ride verbatim into a "kept unchanged" re-emit (the cv scrub keeps
/// an unchanged zstd payload's original bytes). Fail closed on anything but a single self-contained
/// frame — the gzip leg gets this for free (an unchanged gzip payload always re-emits, never keeps
/// its bytes), so only the zstd leg needs the explicit check.
pub fn unzstd(raw: &[u8]) -> Result<Vec<u8>> {
    match zstd::zstd_safe::find_frame_compressed_size(raw) {
        Ok(n) if n == raw.len() => {}
        Ok(_) => bail!("zstd cv payload is not a single self-contained frame"),
        Err(code) => bail!("zstd frame: {}", zstd::zstd_safe::get_error_name(code)),
    }
    match zstd::zstd_safe::get_frame_content_size(raw) {
        Ok(Some(size)) => {
            if size > MAX_DECOMPRESSED_BYTES as u64 {
                bail!("zstd declared content size exceeds limit");
            }
            ZSTD_DECOMPRESSOR
                .with(|d| d.borrow_mut().decompress(raw, size as usize))
                .map_err(|e| anyhow!("unzstd: {e}"))
        }
        Ok(None) => {
            let mut decoder = zstd::stream::read::Decoder::new(raw)?;
            decoder.window_log_max(CV_ZSTD_WINDOW_LOG_MAX)?;
            let mut out = Vec::new();
            decoder
                .take(MAX_DECOMPRESSED_BYTES as u64 + 1)
                .read_to_end(&mut out)
                .map_err(|e| anyhow!("unzstd (streaming): {e}"))?;
            if out.len() > MAX_DECOMPRESSED_BYTES {
                bail!("zstd uncompressed size exceeds limit");
            }
            Ok(out)
        }
        Err(e) => bail!("zstd frame header: {e}"),
    }
}

/// Re-compress a cv payload as zstd. The consumer distinguishes formats by magic bytes alone
/// (`1f 8b` gzip vs `28 b5 2f fd` zstd), so historical gzip blocks stay readable.
pub fn compress_cv(payload: &[u8]) -> Result<Vec<u8>> {
    ZSTD_COMPRESSOR.with(|c| {
        c.borrow_mut()
            .compress(payload)
            .map_err(|e| anyhow!("zstd: {e}"))
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
        let mut enc = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        enc.write_all(&payload).unwrap();
        let theirs = enc.finish().unwrap();
        assert_eq!(gunzip(&theirs).unwrap(), payload);
    }

    #[test]
    fn rejects_a_footer_claiming_more_than_the_cap() {
        let mut stream = gzip(b"small").unwrap();
        let n = stream.len();
        stream[n - 4..].copy_from_slice(&(u32::MAX).to_le_bytes());
        let err = gunzip(&stream).unwrap_err().to_string();
        assert!(err.contains("exceeds limit"), "got: {err}");
    }

    #[test]
    fn fails_closed_on_a_footer_claiming_less_than_the_real_size() {
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

    #[test]
    fn unzstd_round_trips_bulk_and_streaming_frames() {
        let payload = b"zstd zstd zstd payload".repeat(100);
        // Bulk frame with a declared content size — what `compress_cv` emits.
        let bulk = compress_cv(&payload).unwrap();
        assert_eq!(unzstd(&bulk).unwrap(), payload);
        // A streaming encoder omits the content size, exercising the capped streaming leg.
        let mut enc = zstd::stream::write::Encoder::new(Vec::new(), 1).unwrap();
        std::io::Write::write_all(&mut enc, &payload).unwrap();
        let streamed = enc.finish().unwrap();
        assert_eq!(
            zstd::zstd_safe::get_frame_content_size(&streamed).unwrap(),
            None,
            "fixture must omit the declared content size"
        );
        assert_eq!(unzstd(&streamed).unwrap(), payload);
    }

    #[test]
    fn unzstd_rejects_a_declared_size_over_the_cap() {
        let frame = compress_cv(&vec![0u8; MAX_DECOMPRESSED_BYTES + 1]).unwrap();
        let err = unzstd(&frame).unwrap_err().to_string();
        assert!(err.contains("exceeds limit"), "got: {err}");
    }

    #[test]
    fn unzstd_rejects_garbage() {
        assert!(unzstd(b"").is_err());
        assert!(unzstd(&[0x28, 0xb5, 0x2f, 0xfd, 0x00]).is_err());
    }

    #[test]
    fn unzstd_rejects_non_single_frame_payloads() {
        // Bytes past the first frame would ride verbatim into a "kept unchanged" re-emit without
        // ever being decompressed/scrubbed, so a single self-contained frame is required.
        let frame = compress_cv(b"clean cv content").unwrap();

        // Two concatenated frames.
        let mut concatenated = frame.clone();
        concatenated.extend_from_slice(&frame);
        assert!(unzstd(&concatenated)
            .unwrap_err()
            .to_string()
            .contains("single self-contained frame"));

        // A skippable frame appended (magic 0x184D2A50, 4-byte LE length, then arbitrary bytes).
        let mut with_skippable = frame.clone();
        with_skippable.extend_from_slice(&[0x50, 0x2a, 0x4d, 0x18]);
        with_skippable.extend_from_slice(&4u32.to_le_bytes());
        with_skippable.extend_from_slice(b"junk");
        assert!(unzstd(&with_skippable)
            .unwrap_err()
            .to_string()
            .contains("single self-contained frame"));

        // Trailing garbage after a complete frame.
        let mut with_trailing = frame.clone();
        with_trailing.extend_from_slice(b"trailing");
        assert!(unzstd(&with_trailing).is_err());

        // The clean single frame still decodes.
        assert_eq!(unzstd(&frame).unwrap(), b"clean cv content");
    }

    #[test]
    fn compress_cv_emits_a_zstd_frame() {
        // Magic-byte dispatch is the consumer contract, so pin the emitted magic.
        let payload = b"payload".repeat(20);
        let zs = compress_cv(&payload).unwrap();
        assert_eq!(&zs[..4], &[0x28, 0xb5, 0x2f, 0xfd]);
        assert_eq!(
            zstd::bulk::decompress(&zs, payload.len() + 64).unwrap(),
            payload
        );
    }
}
