use std::ops::Range;
use std::path::{Path, PathBuf};

use crate::debug_symbols::{pack_debug_file, NativeFormat};
use crate::upload::SymbolSetUpload;
use anyhow::{anyhow, Result};
use symbolic::debuginfo::{Archive, FileFormat};

pub mod source_bundle;

use source_bundle::SourceFiles;

// Fat Mach-O magic numbers (big-endian fat header variants)
const FAT_MAGIC: u32 = 0xCAFE_BABE;
const FAT_MAGIC_64: u32 = 0xCAFE_BABF;
const FAT_CIGAM: u32 = 0xBEBA_FECA; // byte-swapped FAT_MAGIC
const FAT_CIGAM_64: u32 = 0xBFBA_FECA; // byte-swapped FAT_MAGIC_64

const FAT_HEADER_LENGTH: usize = 8;
const FAT_ARCH_LENGTH: usize = 20;
const FAT_ARCH_64_LENGTH: usize = 32;
/// The offset and the size follow the CPU type and subtype, which are 4 bytes each.
const FAT_ARCH_OFFSET_FIELD: usize = 8;
/// A Java class file starts with the same 4 bytes as a fat file, followed by its version where a
/// fat file has its count. symbolic reads 45 or more as a class file, and no fat file has that
/// many architectures.
const MIN_JAVA_CLASS_VERSION: u32 = 45;

/// A single DWARF binary extracted from a dSYM bundle, ready for upload
struct DsymEntry {
    /// The UUID of this DWARF binary (used as chunk_id)
    uuid: String,
    /// ZIP containing only this DWARF binary (+ optional source files)
    data: Vec<u8>,
}

/// Represents a dSYM bundle ready for upload.
/// Each DWARF binary in the bundle gets its own ZIP, keyed by its UUID.
pub struct DsymFile {
    entries: Vec<DsymEntry>,
    /// Optional release ID
    pub release_id: Option<String>,
}

impl DsymFile {
    /// Create a new DsymFile from a .dSYM bundle path.
    /// Each DWARF binary in the bundle gets its own ZIP so that
    /// stable UUIDs (e.g. app stubs) don't get a new content hash
    /// when a sibling binary (e.g. debug dylib) changes.
    pub fn new(path: &PathBuf, include_source: bool, source_root: Option<&Path>) -> Result<Self> {
        if !path.is_dir() {
            anyhow::bail!("Path {} is not a directory", path.display());
        }

        let extension = path.extension().and_then(|e| e.to_str());
        if extension != Some("dSYM") {
            anyhow::bail!(
                "Path {} is not a dSYM bundle (expected .dSYM extension)",
                path.display()
            );
        }

        let dwarf_dir = path.join("Contents/Resources/DWARF");
        let uuid_entries = extract_dsym_uuids(path)?;

        let mut entries = Vec::new();
        for (uuid, arch, dwarf_filename) in &uuid_entries {
            let dwarf_path = dwarf_dir.join(dwarf_filename);
            let data = zip_dwarf_binary(&dwarf_path, arch, include_source, source_root)?;
            entries.push(DsymEntry {
                uuid: uuid.clone(),
                data,
            });
        }

        Ok(Self {
            entries,
            release_id: None,
        })
    }

    pub fn uuids(&self) -> Vec<&str> {
        self.entries.iter().map(|e| e.uuid.as_str()).collect()
    }

    pub fn total_size(&self) -> usize {
        self.entries.iter().map(|e| e.data.len()).sum()
    }

    /// Convert to SymbolSetUploads (one per UUID)
    pub fn into_uploads(self) -> Vec<SymbolSetUpload> {
        self.entries
            .into_iter()
            .map(|entry| SymbolSetUpload {
                chunk_id: entry.uuid,
                release_id: self.release_id.clone(),
                data: entry.data,
                content_hash: None,
            })
            .collect()
    }
}

/// Extract all UUIDs, architectures, and DWARF filenames from a dSYM bundle.
/// Returns `(uuid, arch, dwarf_filename)` triples.
fn extract_dsym_uuids(dsym_path: &PathBuf) -> Result<Vec<(String, String, String)>> {
    use std::process::Command;

    let output = Command::new("dwarfdump")
        .arg("--uuid")
        .arg(dsym_path)
        .output()
        .map_err(|e| anyhow!("Failed to run dwarfdump: {e}. Is Xcode installed?"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("dwarfdump failed: {stderr}");
    }

    let stdout = String::from_utf8_lossy(&output.stdout);

    // Parse output like: "UUID: 12345678-1234-1234-1234-123456789ABC (arm64) /path/to/DWARF/PostHogExample"
    let entries: Vec<(String, String, String)> = stdout
        .lines()
        .filter_map(|line| {
            let uuid_start = line.find("UUID: ")? + 6;
            let uuid_part = &line[uuid_start..];
            let uuid_end = uuid_part.find(' ')?;
            let uuid = uuid_part[..uuid_end].to_uppercase();

            // Extract arch from the "(<arch>)" parentheses
            let arch_start = line.find('(')? + 1;
            let arch_end = line.find(')')?;
            let arch = line.get(arch_start..arch_end)?.trim().to_string();

            // Extract the DWARF filename from the path at end of line
            // Format: "UUID: <uuid> (<arch>) <full_path>"
            let path_start = line.rfind(')')? + 2; // Skip ") "
            let dwarf_path = line.get(path_start..)?;
            let dwarf_filename = Path::new(dwarf_path).file_name()?.to_str()?.to_string();

            Some((uuid, arch, dwarf_filename))
        })
        .collect();

    if entries.is_empty() {
        anyhow::bail!(
            "Could not extract any UUIDs from dSYM at {}. dwarfdump output: {}",
            dsym_path.display(),
            stdout
        );
    }

    Ok(entries)
}

/// Create a minimal ZIP containing a single DWARF binary (single-arch) and optional source files.
///
/// If the DWARF binary is a fat (universal) Mach-O, only the slice for `arch`
/// is included via [`thin_if_fat`]. This ensures the content hash is stable for
/// a given architecture even when a sibling architecture slice is rebuilt — which
/// would otherwise cause a `content_hash_mismatch` error on incremental uploads.
///
/// ZIP layout:
///   dwarf                    — the raw DWARF Mach-O binary (single-arch)
///   __source/manifest.json   — (optional) source file manifest
///   __source/...             — (optional) source files
fn zip_dwarf_binary(
    dwarf_path: &Path,
    arch: &str,
    include_source: bool,
    source_root: Option<&Path>,
) -> Result<Vec<u8>> {
    // If the file is a fat binary, thin it to only this arch first so that
    // a rebuild of a sibling slice does not change this UUID's content hash.
    let contents = thin_if_fat(dwarf_path, arch)?;

    // Optionally include source files referenced by this DWARF binary
    let sources = if include_source {
        collect_sources(dwarf_path, source_root)
    } else {
        None
    };

    pack_debug_file(&contents, NativeFormat::MachO, sources.as_ref())
}

/// The sources the DWARF binary names. A failure to read them is logged, and the binary then
/// uploads without sources.
fn collect_sources(dwarf_path: &Path, source_root: Option<&Path>) -> Option<SourceFiles> {
    let all_paths = match source_bundle::extract_source_paths_from_dwarf(dwarf_path) {
        Ok(all_paths) => all_paths,
        Err(e) => {
            tracing::warn!(
                "Failed to extract DWARF source paths: {} (continuing without source)",
                e
            );
            return None;
        }
    };

    let filtered =
        source_bundle::filter_source_paths_for_upload(&all_paths, source_root, dwarf_path, |_| {
            true
        });
    if filtered.is_empty() {
        return None;
    }

    match source_bundle::collect_source_files(&filtered) {
        Ok(source_files) => Some(source_files),
        Err(e) => {
            tracing::warn!(
                "Failed to collect source files: {} (continuing without source)",
                e
            );
            None
        }
    }
}

/// Return the bytes for the given architecture slice of `path`.
///
/// If the file is a fat (universal) binary, runs `lipo -thin <arch>` to extract
/// only the relevant slice. If it is already a thin binary (single-arch), the
/// file is read as-is. Using only the relevant slice means the content hash for
/// a stable architecture does not change when a sibling architecture is rebuilt.
fn thin_if_fat(path: &Path, arch: &str) -> Result<Vec<u8>> {
    use std::process::Command;

    let raw = std::fs::read(path)
        .map_err(|e| anyhow!("Failed to read DWARF binary {}: {e}", path.display()))?;

    if raw.len() < 4 {
        return Ok(raw);
    }

    let magic = u32::from_be_bytes([raw[0], raw[1], raw[2], raw[3]]);
    let is_fat =
        magic == FAT_MAGIC || magic == FAT_MAGIC_64 || magic == FAT_CIGAM || magic == FAT_CIGAM_64;

    if !is_fat {
        tracing::debug!(
            "[lipo] {} is already a thin binary, using as-is",
            path.display()
        );
        return Ok(raw);
    }

    tracing::info!(
        "[lipo] fat binary detected at {}, thinning to {} slice ({} bytes total)",
        path.display(),
        arch,
        raw.len()
    );

    // Run `lipo -thin <arch>` to extract just this architecture.
    // NamedTempFile is deleted automatically on drop — covers both success and
    // all early-return error paths without manual cleanup.
    let tmp_file = tempfile::Builder::new()
        .prefix(&format!("posthog_lipo_{arch}_"))
        .suffix(".dwarf")
        .tempfile()
        .map_err(|e| anyhow!("Failed to create temp file for lipo output: {e}"))?;
    let tmp_path = tmp_file.path().to_path_buf();

    let status = Command::new("lipo")
        .args([
            path.to_str()
                .ok_or_else(|| anyhow!("Non-UTF8 path: {}", path.display()))?,
            "-thin",
            arch,
            "-output",
            tmp_path
                .to_str()
                .ok_or_else(|| anyhow!("Non-UTF8 temp path"))?,
        ])
        .status()
        .map_err(|e| anyhow!("Failed to run lipo: {e}. Is Xcode installed?"))?;

    if !status.success() {
        // lipo failed (e.g. arch not present) — fall back to full binary.
        tracing::warn!(
            "[lipo] lipo -thin {arch} failed for {}; falling back to full fat binary",
            path.display()
        );
        return Ok(raw);
    }

    let thinned =
        std::fs::read(&tmp_path).map_err(|e| anyhow!("Failed to read lipo output: {e}"))?;
    tracing::info!(
        "[lipo] thinned {} ({} arch): {} bytes → {} bytes",
        path.file_name().unwrap_or_default().to_string_lossy(),
        arch,
        raw.len(),
        thinned.len()
    );
    Ok(thinned)
}

/// Find all dSYM bundles in a directory
pub fn find_dsym_bundles(directory: &PathBuf) -> Result<Vec<PathBuf>> {
    use walkdir::WalkDir;

    let mut dsyms = Vec::new();

    for entry in WalkDir::new(directory).follow_links(true) {
        let entry = entry?;
        let path = entry.path();

        if path.is_dir() {
            if let Some(ext) = path.extension() {
                if ext == "dSYM" {
                    dsyms.push(path.to_path_buf());
                }
            }
        }
    }

    Ok(dsyms)
}

/// One architecture of a DWARF file from a dSYM bundle: its `LC_UUID` in the uppercase form
/// PostHog stores, and where its bytes sit in the file.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DsymSlice {
    pub uuid: String,
    pub range: Range<usize>,
}

/// The slices of a DWARF file from a dSYM bundle, read from the fat header and the load commands.
///
/// posthog-cli asks `dwarfdump --uuid` and `lipo -thin` for the same answer, see
/// [`DsymFile::new`], and those tools only exist on a Mac with Xcode. hog-worker calls this
/// instead, so a dSYM uploads from any machine with the bytes those tools give.
pub fn read_slices(file: &[u8]) -> Result<Vec<DsymSlice>> {
    let whole = std::iter::once(0..file.len()).collect();
    let ranges = fat_slice_ranges(file).unwrap_or(whole);

    let mut slices = Vec::new();
    for range in ranges {
        let archive = Archive::parse(&file[range.clone()])?;
        let Some(object) = archive.objects().next() else {
            continue;
        };
        let object = object?;

        if object.file_format() == FileFormat::MachO && !object.debug_id().is_nil() {
            slices.push(DsymSlice {
                uuid: object.debug_id().to_string().to_uppercase(),
                range,
            });
        }
    }

    Ok(slices)
}

fn big_endian(bytes: &[u8], at: usize, width: usize) -> Option<u64> {
    let field = bytes.get(at..at + width)?;

    Some(
        field
            .iter()
            .fold(0, |value, byte| (value << 8) | u64::from(*byte)),
    )
}

/// The byte range of each architecture of a fat file, or `None` for a thin file, which is one
/// slice as a whole. A range the file is too short for is cut to the file, and the slice then
/// fails to parse. symbolic does not read a fat file with 64-bit offsets, and `dwarfdump` and
/// `lipo` do, which is why the header is read here.
fn fat_slice_ranges(file: &[u8]) -> Option<Vec<Range<usize>>> {
    let magic = big_endian(file, 0, 4)? as u32;
    let count = big_endian(file, 4, 4)? as u32;
    let (entry_length, field_width) = match magic {
        FAT_MAGIC => (FAT_ARCH_LENGTH, 4),
        FAT_MAGIC_64 => (FAT_ARCH_64_LENGTH, 8),
        _ => return None,
    };
    if count >= MIN_JAVA_CLASS_VERSION {
        return None;
    }

    let clamp = |value: u64| usize::try_from(value).unwrap_or(usize::MAX).min(file.len());
    (0..count as usize)
        .map(|index| {
            let entry = FAT_HEADER_LENGTH + index * entry_length + FAT_ARCH_OFFSET_FIELD;
            let offset = big_endian(file, entry, field_width)?;
            let size = big_endian(file, entry + field_width, field_width)?;

            Some(clamp(offset)..clamp(offset.saturating_add(size)))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    const CPU_TYPE_ARM64: u32 = 0x0100_000c;

    fn fat_header(magic: u32, slices: &[(u64, u64)], field_width: usize) -> Vec<u8> {
        let mut header = Vec::new();
        header.extend_from_slice(&magic.to_be_bytes());
        header.extend_from_slice(&(slices.len() as u32).to_be_bytes());
        for (offset, size) in slices {
            header.extend_from_slice(&CPU_TYPE_ARM64.to_be_bytes());
            header.extend_from_slice(&0u32.to_be_bytes());
            for field in [offset, size] {
                header.extend_from_slice(&field.to_be_bytes()[8 - field_width..]);
            }
            // The alignment, and the reserved word a 64-bit entry ends with.
            header.extend_from_slice(&vec![0; if field_width == 8 { 8 } else { 4 }]);
        }
        header.resize(4096, 0);
        header
    }

    #[test]
    fn fat_slice_ranges_reads_both_header_widths() {
        // A header read with the wrong entry size or field width would hand hog-worker other
        // bytes than `lipo -thin` gives posthog-cli, and the two would upload different hashes.
        let slices = [(1024, 512), (2048, 1000)];

        for (magic, field_width) in [(FAT_MAGIC, 4), (FAT_MAGIC_64, 8)] {
            assert_eq!(
                fat_slice_ranges(&fat_header(magic, &slices, field_width)),
                Some(vec![1024..1536, 2048..3048])
            );
        }
    }

    #[test]
    fn fat_slice_ranges_cuts_a_slice_to_the_file_and_leaves_other_files_alone() {
        let truncated = fat_header(FAT_MAGIC, &[(1024, 512), (4000, 1000)], 4);
        let thin_macho = [0xcf, 0xfa, 0xed, 0xfe, 0, 0, 0, 0];
        let java_class = [0xca, 0xfe, 0xba, 0xbe, 0, 0, 0, 52];

        assert_eq!(
            fat_slice_ranges(&truncated),
            Some(vec![1024..1536, 4000..4096])
        );
        assert_eq!(fat_slice_ranges(&thin_macho), None);
        assert_eq!(fat_slice_ranges(&java_class), None);
    }
}
