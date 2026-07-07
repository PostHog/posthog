use anyhow::Error;
use flate2::read::GzDecoder;
use serde::{Deserialize, Serialize};
use std::panic::AssertUnwindSafe;
use std::{
    io::Read,
    path::{Path, PathBuf},
    sync::Arc,
};
use tokio::sync::mpsc;
use zip::ZipArchive;

/// Magic-byte prefixes of the compression formats we might be handed by mistake.
/// Each entry maps a constant header prefix to the format name.
///
/// A newline-delimited JSON import only ever expects plaintext JSON, whose values
/// begin with `{ [ " -`, a digit, `t`/`f`/`n`, or whitespace. None of the first
/// bytes below (`0x1f 0x28 0x50 0x42 0xfd 0x78`) collide with those, so a match at
/// the *start of a part* is an unambiguous "still compressed" signal rather than a
/// coincidence - see [`detect_compression_magic`].
const COMPRESSION_MAGICS: &[(&[u8], &str)] = &[
    (&[0x1f, 0x8b], "gzip"),
    (&[0x28, 0xb5, 0x2f, 0xfd], "zstd"),
    (&[0x50, 0x4b, 0x03, 0x04], "zip"),
    (&[0x50, 0x4b, 0x05, 0x06], "zip"), // empty archive
    (&[0x50, 0x4b, 0x07, 0x08], "zip"), // spanned archive
    (&[0x42, 0x5a, 0x68], "bzip2"),
    (&[0xfd, 0x37, 0x7a, 0x58, 0x5a, 0x00], "xz"),
    // zlib streams start with CM/CINFO byte 0x78 followed by an FLG byte chosen so
    // that (CMF*256 + FLG) % 31 == 0. These four FLG values cover the compression
    // levels every common zlib encoder emits.
    (&[0x78, 0x01], "zlib"),
    (&[0x78, 0x5e], "zlib"),
    (&[0x78, 0x9c], "zlib"),
    (&[0x78, 0xda], "zlib"),
];

/// Return the name of the compression format whose magic bytes prefix `data`, or
/// `None` if `data` does not start with a recognized compression header. Data
/// shorter than a candidate prefix simply does not match it.
pub(crate) fn detect_compression_magic(data: &[u8]) -> Option<&'static str> {
    COMPRESSION_MAGICS
        .iter()
        .find(|(magic, _)| data.starts_with(magic))
        .map(|(_, name)| *name)
}

/// Peek the first bytes of `path` and, if they are a recognized *non-gzip*
/// compression header, return that format's name. Used to enrich a gzip decode
/// failure: a real gzip that fails to decode is genuine corruption, but a zstd /
/// zip / xz / ... file reaching the gzip extractor is a compression-setting
/// mismatch worth naming. Best-effort - any IO error yields `None`.
fn peek_non_gzip_compression(path: &Path) -> Option<&'static str> {
    let mut buf = [0u8; 8];
    let mut file = std::fs::File::open(path).ok()?;
    let n = file.read(&mut buf).ok()?;
    detect_compression_magic(&buf[..n]).filter(|&fmt| fmt != "gzip")
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ExtractorType {
    ZipGzipJson,
    #[default]
    PlainGzip,
}

impl ExtractorType {
    pub fn create_extractor(&self) -> Arc<dyn PartExtractor> {
        match self {
            ExtractorType::ZipGzipJson => Arc::new(ZipGzipJsonExtractor),
            ExtractorType::PlainGzip => Arc::new(PlainGzipExtractor),
        }
    }
}

/// The data source trait reads parts in forward, monotonically increasing byte
/// ranges. For sources that hand us a compressed file (export endpoints, gzipped
/// S3 objects), we previously decompressed the whole thing to a second on-disk
/// file so the range reads could `seek`. That made worst-case disk usage scale
/// with the *decompressed* size — a single multi-GB compressed export could
/// expand to tens of GB and exhaust the staging volume.
///
/// Instead we stream: a `PartExtractor` opens a [`StreamingReader`] over the
/// compressed file that decompresses on demand as the job reads forward, so disk
/// usage is bounded by the compressed `.raw` file alone. Decompression runs on a
/// dedicated producer thread (off the async runtime) feeding a bounded channel;
/// the reader keeps only a small carry buffer (~one chunk) of decompressed bytes.
pub trait PartExtractor: Send + Sync {
    /// Open a forward streaming reader over the compressed file at `raw_file_path`.
    fn open_reader(&self, raw_file_path: PathBuf) -> StreamingReader;
}

/// Block size the producer thread reads/sends at. Larger blocks keep channel
/// overhead low for multi-GB files.
const PRODUCER_BLOCK_SIZE: usize = 64 * 1024;
/// Bounded channel capacity (in blocks). Caps in-flight decompressed bytes and
/// applies backpressure to the producer thread, so memory stays bounded.
const PRODUCER_CHANNEL_CAPACITY: usize = 32;

type Block = Result<Vec<u8>, String>;

/// A decompressed range returned by [`StreamingReader::read_at`].
pub struct ReadChunk {
    pub bytes: Vec<u8>,
    /// The total decompressed size, populated only once end-of-stream has been
    /// observed. `None` while more data may follow — callers must not treat the
    /// size as known until this is `Some`.
    pub total: Option<u64>,
}

/// A forward-only, resumable reader over a decompressed stream.
///
/// The decompressed size is discovered lazily (only once the producer hits EOF),
/// because we never materialize the decompressed data and therefore cannot know
/// its length up front. Reads must be monotonically non-decreasing in `offset`;
/// small rewinds within the most recently returned span are supported (the job's
/// chunker can re-request the tail of a partially-consumed chunk), but seeking
/// backwards beyond the retained carry buffer is not.
pub struct StreamingReader {
    rx: mpsc::Receiver<Block>,
    /// Decompressed bytes for the half-open range `[carry_start, decoded_end)`.
    carry: Vec<u8>,
    carry_start: u64,
    decoded_end: u64,
    eof: bool,
    /// A decode/producer error, latched so every subsequent read keeps failing.
    /// The producer thread exits after sending an error, and without the latch a
    /// retried read would see the closed channel as a clean EOF and report the
    /// partially decoded length as the stream total - callers that retry reads
    /// would then treat a truncated stream as complete (silent data loss).
    error: Option<String>,
}

impl StreamingReader {
    fn spawn<F>(producer: F) -> Self
    where
        F: FnOnce(mpsc::Sender<Block>) + Send + 'static,
    {
        let (tx, rx) = mpsc::channel(PRODUCER_CHANNEL_CAPACITY);
        // A dedicated OS thread (not the tokio blocking pool) owns the decoder for
        // the lifetime of the read. It exits when the receiver is dropped.
        //
        // Guard against a producer panic (e.g. an internal flate2/zip panic): without
        // this, a panic would drop `tx`, and `read_at` would read the closed channel as
        // a clean EOF and record a truncated part as complete (silent data loss). Convert
        // the panic into a channel error so `read_at` surfaces it instead.
        std::thread::spawn(move || {
            let err_tx = tx.clone();
            if std::panic::catch_unwind(AssertUnwindSafe(move || producer(tx))).is_err() {
                let _unused =
                    err_tx.blocking_send(Err("decompression producer thread panicked".to_string()));
            }
        });
        Self {
            rx,
            carry: Vec::new(),
            carry_start: 0,
            decoded_end: 0,
            eof: false,
            error: None,
        }
    }

    /// Return decompressed bytes in `[offset, offset + max_len)`, clamped to the
    /// end of the stream. `offset` must be >= the start of the retained window.
    pub async fn read_at(&mut self, offset: u64, max_len: usize) -> Result<ReadChunk, Error> {
        if let Some(e) = &self.error {
            return Err(Error::msg(e.clone()));
        }
        if offset < self.carry_start {
            return Err(Error::msg(format!(
                "streaming reader received non-monotonic read: offset {offset} precedes retained window start {}",
                self.carry_start
            )));
        }

        let target = offset.saturating_add(max_len as u64);
        while !self.eof && self.decoded_end < target {
            match self.rx.recv().await {
                Some(Ok(block)) => {
                    self.decoded_end += block.len() as u64;
                    self.carry.extend_from_slice(&block);
                    // Drop everything before `offset` to bound memory to ~one chunk.
                    // Forward-only access guarantees those bytes are never re-read.
                    if self.carry_start < offset {
                        let drop_to = offset.min(self.decoded_end);
                        let drop_len = (drop_to - self.carry_start) as usize;
                        self.carry.drain(0..drop_len);
                        self.carry_start = drop_to;
                    }
                }
                Some(Err(e)) => {
                    self.error = Some(e.clone());
                    return Err(Error::msg(e));
                }
                None => self.eof = true,
            }
        }

        let avail_end = self.decoded_end.min(target);
        let bytes = if avail_end <= offset {
            Vec::new()
        } else {
            let start = (offset - self.carry_start) as usize;
            let end = (avail_end - self.carry_start) as usize;
            self.carry[start..end].to_vec()
        };
        let total = self.eof.then_some(self.decoded_end);
        Ok(ReadChunk { bytes, total })
    }
}

pub struct ZipGzipJsonExtractor;

impl PartExtractor for ZipGzipJsonExtractor {
    fn open_reader(&self, raw_file_path: PathBuf) -> StreamingReader {
        StreamingReader::spawn(move |tx| run_zip_gzip_json_producer(raw_file_path, tx))
    }
}

pub struct PlainGzipExtractor;

impl PartExtractor for PlainGzipExtractor {
    fn open_reader(&self, raw_file_path: PathBuf) -> StreamingReader {
        StreamingReader::spawn(move |tx| run_plain_gzip_producer(raw_file_path, tx))
    }
}

/// Decompress a single gzip member, streaming blocks to `tx`. Appends a trailing
/// newline if the decompressed content is non-empty and didn't already end with
/// one, so the downstream JSONL parser always sees a complete final line.
///
/// `GzDecoder` decodes a single gzip member (it stops at the first member's end).
/// This matches the previous materializing extractor; the export endpoints we
/// consume emit single-member gzip streams, not concatenated members.
fn run_plain_gzip_producer(raw_file_path: PathBuf, tx: mpsc::Sender<Block>) {
    let file = match std::fs::File::open(&raw_file_path) {
        Ok(f) => f,
        Err(e) => {
            let _unused = tx.blocking_send(Err(format!(
                "Failed to open gzip file {}: {e}",
                raw_file_path.display()
            )));
            return;
        }
    };

    let mut decoder = GzDecoder::new(file);
    let mut buffer = vec![0u8; PRODUCER_BLOCK_SIZE];
    let mut last_byte: Option<u8> = None;
    let mut produced_any = false;

    loop {
        match decoder.read(&mut buffer) {
            Ok(0) => break,
            Ok(n) => {
                produced_any = true;
                last_byte = Some(buffer[n - 1]);
                if tx.blocking_send(Ok(buffer[..n].to_vec())).is_err() {
                    return;
                }
            }
            Err(e) => {
                // A decode failure before any output is usually a wrong-format file
                // (e.g. a zstd/zip/xz object reaching the gzip extractor), not a
                // corrupt gzip. Sniff the raw header and, if it is another known
                // format, name it so the pause message is actionable.
                let msg = match (!produced_any)
                    .then(|| peek_non_gzip_compression(&raw_file_path))
                    .flatten()
                {
                    Some(fmt) => format!(
                        "Failed to decompress gzip data: {e}. The file appears to be \
                         {fmt}-compressed, but this import expects gzip - check the source's \
                         compression setting."
                    ),
                    None => format!("Failed to decompress gzip data: {e}"),
                };
                let _unused = tx.blocking_send(Err(msg));
                return;
            }
        }
    }

    if produced_any && last_byte != Some(b'\n') {
        let _unused = tx.blocking_send(Ok(vec![b'\n']));
    }
}

/// Decompress every `.json.gz` member of a zip archive in natural-sorted order,
/// streaming blocks to `tx`. A trailing newline is appended after each non-empty
/// member that didn't end with one, matching the previous concatenation behavior.
fn run_zip_gzip_json_producer(raw_file_path: PathBuf, tx: mpsc::Sender<Block>) {
    let file = match std::fs::File::open(&raw_file_path) {
        Ok(f) => f,
        Err(e) => {
            let _unused = tx.blocking_send(Err(format!(
                "Failed to open zip file {}: {e}",
                raw_file_path.display()
            )));
            return;
        }
    };

    let mut archive = match ZipArchive::new(file) {
        Ok(a) => a,
        Err(e) => {
            let _unused = tx.blocking_send(Err(format!("Failed to read zip archive: {e}")));
            return;
        }
    };

    let mut file_names: Vec<String> = (0..archive.len())
        .filter_map(|i| {
            archive.by_index(i).ok().and_then(|f| {
                let name = f.name().to_string();
                name.ends_with(".json.gz").then_some(name)
            })
        })
        .collect();
    file_names.sort_by(|a, b| natord::compare(a, b));

    let mut buffer = vec![0u8; PRODUCER_BLOCK_SIZE];
    for name in file_names {
        let zip_file = match archive.by_name(&name) {
            Ok(zf) => zf,
            Err(e) => {
                let _unused = tx.blocking_send(Err(format!(
                    "Failed to find file {name} in zip archive: {e}"
                )));
                return;
            }
        };
        let mut decoder = GzDecoder::new(zip_file);
        let mut last_byte: Option<u8> = None;
        let mut entry_bytes: u64 = 0;

        loop {
            match decoder.read(&mut buffer) {
                Ok(0) => break,
                Ok(n) => {
                    entry_bytes += n as u64;
                    last_byte = Some(buffer[n - 1]);
                    if tx.blocking_send(Ok(buffer[..n].to_vec())).is_err() {
                        return;
                    }
                }
                Err(e) => {
                    let _unused = tx.blocking_send(Err(format!(
                        "Failed to decompress gzip data from {name}: {e}"
                    )));
                    return;
                }
            }
        }

        if entry_bytes > 0 && last_byte != Some(b'\n') && tx.blocking_send(Ok(vec![b'\n'])).is_err()
        {
            return;
        }
    }
}

#[cfg(test)]
fn run_verbatim_producer(raw_file_path: PathBuf, tx: mpsc::Sender<Block>) {
    let mut file = match std::fs::File::open(&raw_file_path) {
        Ok(f) => f,
        Err(e) => {
            let _unused = tx.blocking_send(Err(format!(
                "Failed to open file {}: {e}",
                raw_file_path.display()
            )));
            return;
        }
    };

    let mut buffer = vec![0u8; PRODUCER_BLOCK_SIZE];
    loop {
        match file.read(&mut buffer) {
            Ok(0) => break,
            Ok(n) => {
                if tx.blocking_send(Ok(buffer[..n].to_vec())).is_err() {
                    return;
                }
            }
            Err(e) => {
                let _unused = tx.blocking_send(Err(format!("Failed to read file: {e}")));
                return;
            }
        }
    }
}

/// Producer that emits one block then panics, to simulate an internal decoder panic.
#[cfg(test)]
fn run_panicking_producer(tx: mpsc::Sender<Block>) {
    let _unused = tx.blocking_send(Ok(b"partial".to_vec()));
    panic!("simulated producer panic");
}

#[cfg(test)]
impl StreamingReader {
    /// Stream the file at `raw_file_path` verbatim (no decompression, no newline
    /// normalization). Used by tests that exercise the source plumbing with
    /// already-plaintext bodies.
    pub(crate) fn open_verbatim(raw_file_path: PathBuf) -> StreamingReader {
        StreamingReader::spawn(move |tx| run_verbatim_producer(raw_file_path, tx))
    }

    /// A reader whose producer panics mid-stream. Used to prove a panic surfaces as an
    /// error rather than a silently truncated EOF.
    pub(crate) fn open_panicking() -> StreamingReader {
        StreamingReader::spawn(run_panicking_producer)
    }

    /// Drive the reader forward to EOF in `chunk`-sized reads, returning the full
    /// reconstructed stream and its discovered total size.
    pub(crate) async fn read_to_end_for_test(&mut self, chunk: usize) -> (Vec<u8>, u64) {
        let mut out = Vec::new();
        let mut offset = 0u64;
        loop {
            let rc = self.read_at(offset, chunk).await.expect("read_at failed");
            offset += rc.bytes.len() as u64;
            out.extend_from_slice(&rc.bytes);
            if let Some(total) = rc.total {
                if offset >= total {
                    return (out, total);
                }
            } else if rc.bytes.is_empty() {
                // Not at EOF yet but nothing produced — avoid spinning.
                return (out, offset);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::Result;
    use flate2::{write::GzEncoder, Compression};
    use std::{fs::File as StdFile, io::Write};
    use tempfile::TempDir;
    use zip::{write::SimpleFileOptions, ZipWriter};

    fn create_test_gzip_file(content: &str, path: &std::path::Path) -> Result<()> {
        let file = StdFile::create(path)?;
        let mut encoder = GzEncoder::new(file, Compression::default());
        encoder.write_all(content.as_bytes())?;
        encoder.finish()?;
        Ok(())
    }

    fn create_test_zip_with_gzip_json(
        json_files: Vec<(&str, &str)>,
        zip_path: &std::path::Path,
    ) -> Result<()> {
        let file = StdFile::create(zip_path)?;
        let mut zip = ZipWriter::new(file);

        for (filename, content) in json_files {
            let options = SimpleFileOptions::default();
            zip.start_file(filename, options)?;

            let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
            encoder.write_all(content.as_bytes())?;
            let compressed = encoder.finish()?;

            zip.write_all(&compressed)?;
        }
        zip.finish()?;
        Ok(())
    }

    #[test]
    fn test_extractory_type_default() {
        let default_type = ExtractorType::default();
        assert!(matches!(default_type, ExtractorType::PlainGzip));
    }

    #[test]
    fn test_detect_compression_magic_positive() {
        // Real headers emitted by each encoder must be recognized by name.
        let cases: [(&[u8], &str); 8] = [
            (&[0x1f, 0x8b, 0x08, 0x00], "gzip"),
            (&[0x28, 0xb5, 0x2f, 0xfd, 0x00], "zstd"),
            (b"PK\x03\x04rest", "zip"),
            (b"PK\x05\x06", "zip"),
            (b"BZh9blah", "bzip2"),
            (&[0xfd, 0x37, 0x7a, 0x58, 0x5a, 0x00, 0x00], "xz"),
            (&[0x78, 0x9c, 0xcb, 0x48], "zlib"),
            (&[0x78, 0xda, 0x01], "zlib"),
        ];
        for (bytes, expected) in cases {
            assert_eq!(
                detect_compression_magic(bytes),
                Some(expected),
                "bytes {bytes:02x?} should be detected as {expected}"
            );
        }
    }

    #[test]
    fn test_detect_compression_magic_negative() {
        // Plaintext JSONL and other non-magic inputs must never be flagged: this is
        // what keeps the offset-0 job-loop guard from ever tripping on real data.
        let cases: [&[u8]; 7] = [
            b"{\"event\":\"x\"}\n",    // bare JSON object line
            b"[1,2,3]\n",              // JSON array line
            &[0xef, 0xbb, 0xbf, b'{'], // UTF-8 BOM then JSON
            &[0x1f],                   // gzip first byte only - too short to match
            &[0x78],                   // zlib first byte only - too short to match
            &[0xff, 0xff, 0xff],       // invalid-utf8 binary that is not a magic
            b"",                       // empty
        ];
        for bytes in cases {
            assert_eq!(
                detect_compression_magic(bytes),
                None,
                "bytes {bytes:02x?} must not be detected as compression"
            );
        }
    }

    #[tokio::test]
    async fn test_plain_gzip_producer_enriches_wrong_format_error() {
        // A zstd file reaching the gzip extractor is a compression-setting mismatch,
        // not corruption. The decode error must name the actual format so the pause
        // message is actionable, instead of a bare "failed to decompress" string.
        let temp_dir = TempDir::new().unwrap();
        let zstd_file = temp_dir.path().join("actually.zst");
        // A minimal zstd magic-led body is enough: GzDecoder rejects it at the header.
        std::fs::write(&zstd_file, [0x28, 0xb5, 0x2f, 0xfd, 0x00, 0x01, 0x02, 0x03]).unwrap();

        let mut reader = PlainGzipExtractor.open_reader(zstd_file);
        let Err(err) = reader.read_at(0, 8192).await else {
            panic!("a zstd file must not decode as gzip");
        };
        let msg = format!("{err:#}");
        assert!(
            msg.contains("zstd"),
            "decode error should name the detected format, got: {msg}"
        );
        assert!(
            msg.contains("gzip"),
            "decode error should state the expected format, got: {msg}"
        );
    }

    #[tokio::test]
    async fn test_plain_gzip_producer_does_not_mislabel_corrupt_gzip() {
        // A genuinely corrupt gzip (valid header, truncated body) is corruption, not a
        // format mismatch - the error must stay generic and never claim another format.
        let temp_dir = TempDir::new().unwrap();
        let gzip_file = temp_dir.path().join("corrupt.gz");
        create_test_gzip_file(&"line\n".repeat(10000), &gzip_file).unwrap();
        let full = std::fs::read(&gzip_file).unwrap();
        std::fs::write(&gzip_file, &full[..20]).unwrap();

        let mut reader = PlainGzipExtractor.open_reader(gzip_file);
        let Err(err) = reader.read_at(0, 8192).await else {
            panic!("truncated gzip must error");
        };
        let msg = format!("{err:#}");
        assert!(
            !msg.contains("zstd") && !msg.contains("compression setting"),
            "corrupt gzip must not be mislabeled as a format mismatch, got: {msg}"
        );
    }

    #[tokio::test]
    async fn test_plain_gzip_extractor_newline_normalization() -> Result<()> {
        // The extractor guarantees exactly one trailing newline on non-empty
        // content and leaves empty content untouched.
        // (case name, raw input, expected decompressed output)
        let cases: [(&str, &str, &str); 3] = [
            (
                "already terminated",
                "line1\nline2\nline3\n",
                "line1\nline2\nline3\n",
            ),
            (
                "missing trailing newline",
                "line1\nline2\nline3",
                "line1\nline2\nline3\n",
            ),
            ("empty file", "", ""),
        ];

        for (name, input, expected) in cases {
            let temp_dir = TempDir::new()?;
            let gzip_file = temp_dir.path().join("test.gz");
            create_test_gzip_file(input, &gzip_file)?;

            let mut reader = PlainGzipExtractor.open_reader(gzip_file);
            let (data, size) = reader.read_to_end_for_test(8192).await;

            assert_eq!(
                size as usize,
                expected.len(),
                "size mismatch for case: {name}"
            );
            assert_eq!(data, expected.as_bytes(), "data mismatch for case: {name}");
        }
        Ok(())
    }

    #[tokio::test]
    async fn test_plain_gzip_extractor_corrupt_midstream_errors() {
        let temp_dir = TempDir::new().unwrap();
        let gzip_file = temp_dir.path().join("corrupt.gz");
        // Write a valid gzip, then truncate it so the header is intact but the
        // deflate body (and trailer) are incomplete.
        create_test_gzip_file(&"line\n".repeat(10000), &gzip_file).unwrap();
        let full = std::fs::read(&gzip_file).unwrap();
        assert!(full.len() > 50, "compressed fixture should be non-trivial");
        std::fs::write(&gzip_file, &full[..20]).unwrap();

        // Decoding the truncated stream must surface an error rather than
        // silently truncating output or panicking.
        let mut reader = PlainGzipExtractor.open_reader(gzip_file);
        let result = reader.read_at(0, 8192).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_decode_error_is_latched_across_reads() {
        // Once a decode error is delivered, every subsequent read must keep
        // returning it. The producer thread exits after sending the error, so a
        // naive re-read would see the closed channel as a clean EOF and report the
        // partially decoded length as the stream total - callers that retry reads
        // (the sources' get_chunk retry loops) would then record a truncated part
        // as complete: silent data loss.
        let temp_dir = TempDir::new().unwrap();
        let gzip_file = temp_dir.path().join("corrupt.gz");
        // Large content so plenty of blocks decode successfully before the
        // truncation point - the dangerous shape, since decoded_end is well past
        // zero when the error arrives.
        create_test_gzip_file(&"line\n".repeat(100_000), &gzip_file).unwrap();
        let full = std::fs::read(&gzip_file).unwrap();
        std::fs::write(&gzip_file, &full[..full.len() - 5]).unwrap();

        let mut reader = PlainGzipExtractor.open_reader(gzip_file);

        // Drive forward until the decode error surfaces (some reads succeed first).
        let mut offset = 0u64;
        while let Ok(chunk) = reader.read_at(offset, 8192).await {
            assert!(
                chunk.total.is_none(),
                "truncated stream must never report a total"
            );
            assert!(!chunk.bytes.is_empty(), "no progress and no error");
            offset += chunk.bytes.len() as u64;
        }

        // The error must be sticky: re-reads (at the same or an earlier retained
        // offset) return the error again, never a clean EOF with a bogus total.
        for _ in 0..2 {
            let retry = reader.read_at(offset, 8192).await;
            assert!(
                retry.is_err(),
                "retried read after a decode error must keep erroring, not report EOF"
            );
        }
    }

    #[tokio::test]
    async fn test_zip_gzip_json_extractor_single_file() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let zip_file = temp_dir.path().join("test.zip");
        let json_content = r#"{"event": "test", "timestamp": 123}
    {"event": "test2", "timestamp": 456}"#;

        create_test_zip_with_gzip_json(vec![("data.json.gz", json_content)], &zip_file)?;

        let mut reader = ZipGzipJsonExtractor.open_reader(zip_file);
        let (data, size) = reader.read_to_end_for_test(8192).await;

        assert!(size > 0);
        let extracted = String::from_utf8(data).unwrap();
        assert!(extracted.contains("test"));
        assert!(extracted.contains("test2"));
        Ok(())
    }

    #[tokio::test]
    async fn test_zip_gzip_json_extractor_multiple_files() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let zip_file = temp_dir.path().join("multi.zip");
        let json_files = vec![
            ("001.json.gz", r#"{"id": 1}"#),
            ("002.json.gz", r#"{"id": 2}"#),
            ("003.json.gz", r#"{"id": 3}"#),
        ];

        create_test_zip_with_gzip_json(json_files, &zip_file)?;

        let mut reader = ZipGzipJsonExtractor.open_reader(zip_file);
        let (data, _size) = reader.read_to_end_for_test(8192).await;

        let extracted = String::from_utf8(data).unwrap();
        // Natural sort keeps members ordered; newline appended after each.
        assert_eq!(extracted, "{\"id\": 1}\n{\"id\": 2}\n{\"id\": 3}\n");
        Ok(())
    }

    #[tokio::test]
    async fn test_zip_gzip_json_extractor_ignores_non_json_gz_files() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let zip_file = temp_dir.path().join("mixed.zip");

        let file = StdFile::create(&zip_file)?;
        let mut zip = ZipWriter::new(file);

        zip.start_file("data.json.gz", SimpleFileOptions::default())?;
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(b"valid json")?;
        let compressed = encoder.finish()?;
        zip.write_all(&compressed)?;

        zip.start_file("readme.txt", SimpleFileOptions::default())?;
        zip.write_all(b"ignore me")?;

        zip.start_file("data.json", SimpleFileOptions::default())?;
        zip.write_all(b"also ignore")?;

        zip.finish()?;

        let mut reader = ZipGzipJsonExtractor.open_reader(zip_file);
        let (data, _size) = reader.read_to_end_for_test(8192).await;

        let extracted = String::from_utf8(data).unwrap();
        assert!(extracted.contains("valid json"));
        assert!(!extracted.contains("ignore me"));
        assert!(!extracted.contains("also ignore"));
        Ok(())
    }

    #[tokio::test]
    async fn test_plain_gzip_extractor_nonexistent_file() {
        let temp_dir = TempDir::new().unwrap();
        let nonexistent_file = temp_dir.path().join("nonexistent.gz");

        let mut reader = PlainGzipExtractor.open_reader(nonexistent_file);
        // The open error surfaces on the first read.
        let result = reader.read_at(0, 8192).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_zip_gzip_extractor_invalid_zip() {
        let temp_dir = TempDir::new().unwrap();
        let invalid_zip = temp_dir.path().join("invalid.zip");
        std::fs::write(&invalid_zip, b"not a zip file").unwrap();

        let mut reader = ZipGzipJsonExtractor.open_reader(invalid_zip);
        let result = reader.read_at(0, 8192).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_zip_gzip_extractor_empty_zip() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let zip_file = temp_dir.path().join("empty.zip");
        let file = StdFile::create(&zip_file)?;
        let zip = ZipWriter::new(file);
        zip.finish()?;

        let mut reader = ZipGzipJsonExtractor.open_reader(zip_file);
        let (data, size) = reader.read_to_end_for_test(8192).await;

        assert_eq!(size, 0);
        assert!(data.is_empty());
        Ok(())
    }

    #[tokio::test]
    async fn test_large_file_handling() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let large_content = "line\n".repeat(10000);
        let gzip_file = temp_dir.path().join("large.gz");
        create_test_gzip_file(&large_content, &gzip_file)?;

        // Small read chunk + large content exercises the carry buffer / front-trim.
        let mut reader = PlainGzipExtractor.open_reader(gzip_file);
        let (data, size) = reader.read_to_end_for_test(777).await;

        assert_eq!(size as usize, large_content.len());
        assert_eq!(data, large_content.as_bytes());
        Ok(())
    }

    #[tokio::test]
    async fn test_trait_object_usage() -> Result<()> {
        let temp_dir = TempDir::new()?;
        let gzip_file = temp_dir.path().join("trait_test.gz");
        create_test_gzip_file("trait test content\n", &gzip_file)?;

        let extractor: Arc<dyn PartExtractor> = Arc::new(PlainGzipExtractor);
        let mut reader = extractor.open_reader(gzip_file);
        let (data, size) = reader.read_to_end_for_test(8192).await;

        assert_eq!(size as usize, "trait test content\n".len());
        assert_eq!(data, b"trait test content\n");
        Ok(())
    }

    #[tokio::test]
    async fn test_read_at_clamps_and_reports_total_past_eof() {
        let temp_dir = TempDir::new().unwrap();
        let gzip_file = temp_dir.path().join("clamp.gz");
        create_test_gzip_file("abc\n", &gzip_file).unwrap();

        let mut reader = PlainGzipExtractor.open_reader(gzip_file);
        // Reading well past the end returns only available bytes + the total.
        let rc = reader.read_at(0, 1024).await.unwrap();
        assert_eq!(rc.bytes, b"abc\n");
        assert_eq!(rc.total, Some(4));

        // A subsequent read at/after EOF returns empty with the known total.
        let rc = reader.read_at(4, 1024).await.unwrap();
        assert!(rc.bytes.is_empty());
        assert_eq!(rc.total, Some(4));
    }

    #[tokio::test]
    async fn test_read_at_rejects_backwards_seek() {
        let temp_dir = TempDir::new().unwrap();
        let gzip_file = temp_dir.path().join("seek.gz");
        // Large enough that advancing far forward trims the front of the carry
        // window, so the retained start moves well past 0.
        create_test_gzip_file(&"x".repeat(1_000_000), &gzip_file).unwrap();

        let mut reader = PlainGzipExtractor.open_reader(gzip_file);
        reader.read_at(0, 1024).await.unwrap();
        reader.read_at(900_000, 1024).await.unwrap();
        // Seeking back before the (now-trimmed) retained window is rejected.
        let result = reader.read_at(0, 1024).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_producer_panic_surfaces_as_error_not_truncated_eof() {
        // A producer panic must not be mistaken for a clean end-of-stream, which would
        // record a truncated part as complete (silent data loss). Drive the reader past
        // the one block the producer emits before panicking, and require an error.
        let mut reader = StreamingReader::open_panicking();

        let mut offset = 0u64;
        loop {
            match reader.read_at(offset, 4).await {
                // Expected: the panic is surfaced as a read error.
                Err(_) => return,
                Ok(chunk) => {
                    assert!(
                        chunk.total.is_none(),
                        "panic was swallowed as a clean EOF (total={:?})",
                        chunk.total
                    );
                    assert!(
                        !chunk.bytes.is_empty(),
                        "no error and no progress: panic was not surfaced"
                    );
                    offset += chunk.bytes.len() as u64;
                }
            }
        }
    }
}
