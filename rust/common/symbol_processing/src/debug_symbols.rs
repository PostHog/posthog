use std::path::{Path, PathBuf};

use anyhow::{anyhow, Result};
use posthog_symbol_data::{write_symbol_data, AppleDsym, ElfDebugInfo};
use symbolic::debuginfo::{Archive, FileFormat, ObjectError, ObjectKind};
use tracing::{info, warn};

use crate::dsym::{
    source_bundle::{self, SourceFiles},
    DsymFile,
};
use crate::upload::SymbolSetUpload;

/// The name of the binary inside the zip of a native symbol set. The server reads it by name.
pub const DWARF_ENTRY: &str = "dwarf";

/// Go's linker on macOS compresses DWARF into sections with this prefix.
const COMPRESSED_DWARF_MARKER: &[u8] = b"__zdebug_";

const ELF_MAGIC: &[u8; 4] = b"\x7fELF";
// Thin little-endian 64/32-bit Mach-O and the big-endian fat header — the
// on-disk layouts produced by Apple toolchains and Go, and the ones the
// symbolic archive parser understands (fat64, `0xcafebabf`, is not supported
// and stays skipped).
const MACHO_MAGICS: [[u8; 4]; 3] = [
    [0xcf, 0xfa, 0xed, 0xfe],
    [0xce, 0xfa, 0xed, 0xfe],
    [0xca, 0xfe, 0xba, 0xbe],
];

/// A native debug-info file discovered on disk, parsed and validated,
/// ready to be packaged for upload.
pub struct DebugSymbolFile {
    /// The debug id used as chunk_id: derived from the GNU build id for ELF
    /// (lowercase), or the `LC_UUID` for Mach-O (uppercase, matching the SDK
    /// and `dsym upload`)
    pub debug_id: String,
    pub path: PathBuf,
    /// Raw contents: the whole file for ELF, one architecture slice for Mach-O
    /// (a fat binary yields one `DebugSymbolFile` per slice)
    data: Vec<u8>,
    /// Size of the data, used to pick the richer candidate on debug_id collisions
    size: usize,
    format: NativeFormat,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NativeFormat {
    Elf,
    MachO,
}

/// The format the first four bytes of a file announce, for a caller that must not read a whole
/// build artifact to learn that it is not a native binary.
pub fn magic_format(magic: &[u8; 4]) -> Option<NativeFormat> {
    if magic == ELF_MAGIC {
        Some(NativeFormat::Elf)
    } else if MACHO_MAGICS.contains(magic) {
        Some(NativeFormat::MachO)
    } else {
        None
    }
}

/// Zip a native binary as [`DWARF_ENTRY`], with its sources after it when given, and wrap the
/// zip in the symbol_data container of its format (`ElfDebugInfo` for ELF, `AppleDsym` for
/// Mach-O - the layout the server expects per chunk kind).
pub fn pack_debug_file(
    data: &[u8],
    format: NativeFormat,
    sources: Option<&SourceFiles>,
) -> Result<Vec<u8>> {
    use std::io::{Cursor, Write};

    let mut buffer = Cursor::new(Vec::new());
    {
        let mut zip = zip::ZipWriter::new(&mut buffer);
        let options = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Deflated);

        zip.start_file(DWARF_ENTRY, options)?;
        zip.write_all(data)?;

        if let Some(sources) = sources {
            source_bundle::add_source_to_zip(&mut zip, sources)?;
        }

        zip.finish()?;
    }

    let zip_data = buffer.into_inner();
    let wrapped = match format {
        NativeFormat::MachO => write_symbol_data(AppleDsym { data: zip_data })?,
        NativeFormat::Elf => write_symbol_data(ElfDebugInfo { data: zip_data })?,
    };

    Ok(wrapped)
}

/// The outcome of scanning a directory for native debug symbols.
#[derive(Default)]
pub struct DiscoveryReport {
    /// Validated files, deduplicated by debug id
    pub files: Vec<DebugSymbolFile>,
    /// ELF/Mach-O executables/libraries that carry no debug info (skipped)
    pub without_debug_info: Vec<PathBuf>,
    /// ELFs with debug info but no GNU build id (cannot be uploaded)
    pub missing_build_id: Vec<PathBuf>,
    /// Mach-O binaries with debug info but no `LC_UUID` (cannot be uploaded)
    pub missing_uuid: Vec<PathBuf>,
    /// Mach-O binaries whose DWARF is compressed (`__zdebug_*` sections, Go's
    /// default on macOS), which the symbolication server can't read yet
    pub compressed_dwarf: Vec<PathBuf>,
    /// Apple dSYM bundles spotted while scanning (packaged via the dsym path)
    pub dsym_bundles: Vec<PathBuf>,
    /// Split-DWARF artifacts spotted while scanning (unsupported)
    pub split_dwarf: Vec<PathBuf>,
}

impl DebugSymbolFile {
    /// Package the file for upload: a ZIP with the binary stored as `dwarf` at
    /// the root (plus an optional `__source/` bundle), wrapped in the
    /// symbol_data container matching its format (`ElfDebugInfo` for ELF,
    /// `AppleDsym` for Mach-O — the layout the server expects per chunk kind).
    pub fn into_upload(
        self,
        release_id: Option<String>,
        include_source: bool,
        source_root: Option<&Path>,
    ) -> Result<SymbolSetUpload> {
        let sources = if include_source {
            self.collect_sources(source_root)
        } else {
            None
        };

        let wrapped = pack_debug_file(&self.data, self.format, sources.as_ref())?;

        Ok(SymbolSetUpload {
            chunk_id: self.debug_id,
            release_id,
            data: wrapped,
            content_hash: None,
        })
    }

    /// The sources the binary's DWARF names. A failure to read them is logged, and the binary
    /// then uploads without sources.
    fn collect_sources(&self, source_root: Option<&Path>) -> Option<SourceFiles> {
        let all_paths = match source_bundle::extract_source_paths_from_dwarf_bytes(&self.data) {
            Ok(all_paths) => all_paths,
            Err(e) => {
                warn!(
                    "Failed to extract DWARF source paths: {} (continuing without source)",
                    e
                );
                return None;
            }
        };

        let filtered = source_bundle::filter_source_paths_for_upload(
            &all_paths,
            source_root,
            &self.path,
            is_native_source_path,
        );
        if filtered.is_empty() {
            return None;
        }

        match source_bundle::collect_source_files(&filtered) {
            Ok(source_files) => Some(source_files),
            Err(e) => {
                warn!(
                    "Failed to collect source files: {} (continuing without source)",
                    e
                );
                None
            }
        }
    }
}

/// Drop native registry/toolchain sources outside the user's project tree.
/// Go toolchain sources are already trimmed inside the shared extraction
/// (see `filter_go_toolchain_sources`).
pub fn is_native_source_path(path: &str) -> bool {
    const EXCLUDED: &[&str] = &[
        "/.cargo/registry/",
        "/.cargo/git/",
        "/rustc/",
        "/.rustup/toolchains/",
        "/vendor/",
    ];
    if EXCLUDED.iter().any(|sub| path.contains(sub)) {
        tracing::debug!("Filtered out (native toolchain): {}", path);
        return false;
    }
    true
}

/// Walk `directory` and classify everything that looks like native debug
/// symbols. Only ELF and Mach-O executables, shared libraries, and debug
/// companions (e.g. from `objcopy --only-keep-debug`) are considered;
/// relocatable objects and other kinds are ignored.
pub fn discover(directory: &Path) -> Result<DiscoveryReport> {
    use walkdir::WalkDir;

    let mut report = DiscoveryReport::default();
    let mut seen: std::collections::HashMap<String, usize> = std::collections::HashMap::new();

    for entry in WalkDir::new(directory).follow_links(true) {
        // A symlink loop, dangling link, or unreadable directory surfaces here
        // as an iterator error. Skip just that entry rather than aborting the
        // whole scan, which would discard every valid file already found.
        let entry = match entry {
            Ok(entry) => entry,
            Err(e) => {
                warn!("Skipping unreadable path while scanning: {e}");
                continue;
            }
        };
        let path = entry.path();

        if path.is_dir() {
            if path.extension().is_some_and(|e| e == "dSYM") {
                report.dsym_bundles.push(path.to_path_buf());
            }
            continue;
        }

        if path.extension().is_some_and(|e| e == "dwp" || e == "dwo") {
            report.split_dwarf.push(path.to_path_buf());
            continue;
        }

        if !entry.file_type().is_file() {
            continue;
        }

        // Files inside a .dSYM bundle (its inner DWARF Mach-O) belong to the
        // bundle, which is packaged wholesale via the dsym path.
        if path
            .ancestors()
            .skip(1)
            .any(|p| p.extension().is_some_and(|e| e == "dSYM"))
        {
            continue;
        }

        for file in parse_candidates(path)? {
            match file {
                Candidate::NoDebugInfo => report.without_debug_info.push(path.to_path_buf()),
                Candidate::NoBuildId => report.missing_build_id.push(path.to_path_buf()),
                Candidate::MissingUuid => report.missing_uuid.push(path.to_path_buf()),
                Candidate::CompressedDwarf => report.compressed_dwarf.push(path.to_path_buf()),
                Candidate::Valid(file) => {
                    // Dedup by debug id (e.g. a binary and its objcopy companion):
                    // keep the larger file, which carries at least as much debug data.
                    if let Some(&existing) = seen.get(&file.debug_id) {
                        let existing_file = &report.files[existing];
                        warn!(
                            "Duplicate debug id {} for {} and {}; keeping the larger file",
                            file.debug_id,
                            existing_file.path.display(),
                            file.path.display()
                        );
                        if file.size > existing_file.size {
                            report.files[existing] = file;
                        }
                    } else {
                        seen.insert(file.debug_id.clone(), report.files.len());
                        report.files.push(file);
                    }
                }
            }
        }
    }

    Ok(report)
}

enum Candidate {
    Valid(DebugSymbolFile),
    NoDebugInfo,
    NoBuildId,
    MissingUuid,
    CompressedDwarf,
}

/// One object of a native file, classified. A thin file holds one object, and a universal (fat)
/// Mach-O holds one per architecture.
pub enum ObjectCandidate<'data> {
    /// Ready to upload. `data` is the object's own bytes: the whole file for a thin one, and the
    /// architecture slice for a fat one, because the server resolves one binary per chunk id.
    Valid {
        debug_id: String,
        format: NativeFormat,
        data: &'data [u8],
    },
    NoDebugInfo,
    NoBuildId,
    MissingUuid,
    CompressedDwarf,
    /// The object did not parse. posthog-cli logs it and goes on to the next object. hog-worker
    /// reports it for a slice of a fat file, and fails the file when it is thin.
    Unparseable(ObjectError),
}

fn has_native_magic(path: &Path) -> bool {
    use std::io::Read;

    let Ok(mut file) = std::fs::File::open(path) else {
        warn!("Could not open {} (skipping)", path.display());
        return false;
    };
    let mut magic = [0u8; 4];
    if file.read_exact(&mut magic).is_err() {
        return false;
    }
    magic_format(&magic).is_some()
}

/// Parse a file into native debug-symbol candidates. Returns an empty vec for
/// anything that isn't an ELF or Mach-O executable/library/debug companion.
/// A universal (fat) Mach-O yields one candidate per architecture slice, each
/// carrying just that slice's bytes and its own `LC_UUID`.
fn parse_candidates(path: &Path) -> Result<Vec<Candidate>> {
    // Check the magic before loading the file: build trees contain large
    // unrelated artifacts that shouldn't be read into memory just to be skipped.
    if !has_native_magic(path) {
        return Ok(Vec::new());
    }

    let Ok(data) = std::fs::read(path) else {
        warn!("Could not read {} (skipping)", path.display());
        return Ok(Vec::new());
    };

    let objects = match classify_objects(&data) {
        Ok(objects) => objects,
        Err(e) => {
            warn!("Could not parse {} (skipping): {e}", path.display());
            return Ok(Vec::new());
        }
    };

    let mut candidates = Vec::new();
    for object in objects {
        candidates.push(match object {
            ObjectCandidate::Valid {
                debug_id,
                format,
                data,
            } => Candidate::Valid(DebugSymbolFile {
                debug_id,
                path: path.to_path_buf(),
                size: data.len(),
                data: data.to_vec(),
                format,
            }),
            ObjectCandidate::NoDebugInfo => Candidate::NoDebugInfo,
            ObjectCandidate::NoBuildId => Candidate::NoBuildId,
            ObjectCandidate::MissingUuid => Candidate::MissingUuid,
            ObjectCandidate::CompressedDwarf => Candidate::CompressedDwarf,
            ObjectCandidate::Unparseable(_) => {
                warn!("Unparseable object in {} (skipping it)", path.display());
                continue;
            }
        });
    }

    Ok(candidates)
}

/// Classify every object in the bytes of a native file. Objects that are not an ELF or Mach-O
/// executable, library or debug companion are left out. The error is the file itself failing to
/// parse.
pub fn classify_objects(data: &[u8]) -> Result<Vec<ObjectCandidate<'_>>, ObjectError> {
    let archive = Archive::parse(data)?;

    let mut candidates = Vec::new();
    for object in archive.objects() {
        let object = match object {
            Ok(object) => object,
            Err(error) => {
                candidates.push(ObjectCandidate::Unparseable(error));
                continue;
            }
        };

        let format = match object.file_format() {
            FileFormat::Elf => NativeFormat::Elf,
            FileFormat::MachO => NativeFormat::MachO,
            _ => continue,
        };

        // Relocatable objects (.o) and other kinds aren't loadable images.
        if !matches!(
            object.kind(),
            ObjectKind::Executable | ObjectKind::Library | ObjectKind::Debug
        ) {
            continue;
        }

        if !object.has_debug_info() {
            // Go's darwin linker compresses the DWARF it embeds (`__zdebug_*`
            // sections) by default, which the server can't read — surface
            // that as its own case so the guidance can name the fix.
            if format == NativeFormat::MachO && contains_zdebug_section(object.data()) {
                candidates.push(ObjectCandidate::CompressedDwarf);
            } else {
                candidates.push(ObjectCandidate::NoDebugInfo);
            }
            continue;
        }

        // Without an identity the SDK can reproduce at runtime — the GNU
        // build id for ELF, the LC_UUID for Mach-O — the upload would never
        // match any crash event. For ELF specifically, symbolic synthesizes a
        // content-derived debug id when the build id is missing, so the
        // code_id check must come first.
        let debug_id = object.debug_id();
        if (format == NativeFormat::Elf && object.code_id().is_none()) || debug_id.is_nil() {
            candidates.push(match format {
                NativeFormat::MachO => ObjectCandidate::MissingUuid,
                NativeFormat::Elf => ObjectCandidate::NoBuildId,
            });
            continue;
        }

        // Chunk id casing is per-format and case-sensitive on the server:
        // ELF ids are lowercase, Mach-O ids are uppercase (matching the SDKs
        // and `dsym upload`).
        let debug_id = match format {
            NativeFormat::MachO => debug_id.to_string().to_uppercase(),
            NativeFormat::Elf => debug_id.to_string(),
        };

        candidates.push(ObjectCandidate::Valid {
            debug_id,
            format,
            data: object.data(),
        });
    }

    Ok(candidates)
}

/// Detect Go-style compressed DWARF in a Mach-O slice. Section names live
/// verbatim in the section headers, so a plain byte scan is sufficient for a
/// diagnostic.
fn contains_zdebug_section(data: &[u8]) -> bool {
    data.windows(COMPRESSED_DWARF_MARKER.len())
        .any(|window| window == COMPRESSED_DWARF_MARKER)
}

/// Package any discovered Apple `.dSYM` bundles into uploads, reusing the exact
/// same code path as `posthog-cli dsym upload` (uppercase `LC_UUID` chunk_ids,
/// `AppleDsym` container). A bundle that fails to process — most often because
/// `dwarfdump` is unavailable, since it ships with Xcode and is macOS-only — is
/// logged and skipped rather than aborting the run, so a mixed ELF + dSYM
/// directory still uploads its ELF symbols on Linux.
///
/// Uploads come back with no release id; the caller stamps one (if any) after it
/// knows there is something to upload, so a fully-skipped run leaves no release.
pub fn package_dsym_bundles(
    bundles: &[PathBuf],
    include_source: bool,
    source_root: Option<&Path>,
) -> Vec<SymbolSetUpload> {
    let mut uploads = Vec::new();
    for bundle in bundles {
        match DsymFile::new(bundle, include_source, source_root) {
            Ok(dsym_file) => {
                info!(
                    "Processing dSYM {} (UUIDs: {})",
                    bundle.display(),
                    dsym_file.uuids().join(", ")
                );
                uploads.extend(dsym_file.into_uploads());
            }
            Err(e) => {
                warn!(
                    "Failed to process dSYM {}: {e} (skipping)",
                    bundle.display()
                );
            }
        }
    }
    uploads
}

/// Extract the debug id of an ELF file, e.g. for testing parity with the SDK.
pub fn elf_debug_id(path: &Path) -> Result<String> {
    let data = std::fs::read(path)?;
    let archive = Archive::parse(&data).map_err(|e| anyhow!("parse {}: {e}", path.display()))?;
    let object = archive
        .objects()
        .next()
        .ok_or_else(|| anyhow!("no objects in {}", path.display()))?
        .map_err(|e| anyhow!("parse object in {}: {e}", path.display()))?;
    Ok(object.debug_id().to_string())
}
