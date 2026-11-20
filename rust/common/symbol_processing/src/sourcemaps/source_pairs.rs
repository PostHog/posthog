use crate::{
    files::{content_hash, SourceFile},
    sourcemaps::content::{
        get_injected_release_id, AdjustmentOptions, MinifiedSourceFile, SourceMapContent,
        SourceMapFile,
    },
    upload::{ReleaseMode, SymbolSetUpload},
};
use anyhow::{anyhow, Context, Result};
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use serde_json::Value;
use std::{borrow::Cow, path::PathBuf};
use tracing::{debug, info, warn};
use walkdir::DirEntry;

/// Sibling-JS size below which an empty sourcemap is treated as a harmless
/// bundler-generated wrapper (e.g. Turbopack App Router page entries,
/// webpack re-export shims). Turbopack page entries reach about 3 KiB after
/// chunk-id injection (#70235), and every layout, loading or error file on the
/// route makes the entry larger. Every empty map is skipped whatever its size,
/// so this cutoff only picks the message and which of the wrapper and suspect
/// counts the map adds to. A bundler that drops maps for a whole build also
/// writes empty maps for chunks well above 4 KiB, so a summary still reports it.
pub const WRAPPER_JS_SIZE_THRESHOLD_BYTES: usize = 4096;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EmptySourcemap {
    /// The bundle is small: a wrapper the bundler wrote, with nothing to symbolicate.
    Wrapper,
    /// The bundle is large, which points at a bundler that is set to drop its sourcemaps.
    Suspect,
}

/// A fault in the debug ids a bundler wrote. The caller decides how to tell the user: posthog-cli
/// logs [`DebugIdIssue::log`], hog-worker returns its own wording to hog.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DebugIdIssue {
    /// The chunk's comment and the sourcemap's field disagree. The chunk's id is used.
    Mismatch { source_id: String, map_id: String },
    /// The debug id is not a UUID. A chunk id derived from the content is used instead.
    Malformed { debug_id: String },
}

impl DebugIdIssue {
    /// posthog-cli's wording.
    pub fn log(&self, source_path: &std::path::Path) {
        match self {
            DebugIdIssue::Mismatch { source_id, map_id } => warn!(
                "debug id mismatch for {}: chunk has {}, sourcemap has {} — using the chunk's",
                source_path.display(),
                source_id,
                map_id
            ),
            DebugIdIssue::Malformed { debug_id } => warn!(
                "ignoring malformed debug id {:?} on {} — falling back to a content-derived chunk id",
                debug_id,
                source_path.display()
            ),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct UploadOptions {
    pub adjustment: AdjustmentOptions,
    /// Whether a debug id mismatch found while resolving the upload id is logged. posthog-cli
    /// logs it. hog-worker reports it once, at injection, and sets `false` here.
    pub log_debug_id_mismatch: bool,
}

impl Default for UploadOptions {
    fn default() -> Self {
        Self {
            adjustment: AdjustmentOptions::default(),
            log_debug_id_mismatch: true,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct ReadPairsOptions {
    /// Skip a pair whose `sourceMappingURL` names a JSON file that is not a sourcemap, see
    /// [`SourceMapContent::is_sourcemap`]. posthog-cli reads such a file as a map with no
    /// mappings, and hog-worker skips it.
    pub skip_non_sourcemaps: bool,
}

#[derive(Debug)]
// Source pairs are the fundamental unit of a frontend symbol set
pub struct SourcePair {
    pub source: MinifiedSourceFile,
    pub sourcemap: SourceMapFile,
}

impl SourcePair {
    /// Build a pair from content the caller already read, for a caller that does its own file
    /// reading and error reporting.
    pub fn from_parts(
        source_path: PathBuf,
        source: String,
        sourcemap_path: PathBuf,
        sourcemap: SourceMapContent,
    ) -> Self {
        Self {
            source: MinifiedSourceFile {
                inner: SourceFile::new(source_path, source),
            },
            sourcemap: SourceMapFile {
                inner: SourceFile::new(sourcemap_path, sourcemap),
            },
        }
    }

    pub fn has_chunk_id(&self) -> bool {
        // Minified chunks are the source of truth for their ID's, not sourcemaps,
        // because sometimes sourcemaps are shared across multiple chunks.
        self.get_chunk_id().is_some()
    }

    pub fn get_chunk_id(&self) -> Option<String> {
        self.source.get_chunk_id()
    }

    /// Debug id already present in the pair, if any. The chunk's comment is authoritative
    /// (sourcemaps can be shared across chunks); the sourcemap's field is only a fallback.
    pub fn get_debug_id(&self) -> Option<String> {
        let (debug_id, mismatch) = self.resolve_debug_id();
        if let Some(mismatch) = mismatch {
            mismatch.log(&self.source.inner.path);
        }
        debug_id
    }

    pub fn resolve_debug_id(&self) -> (Option<String>, Option<DebugIdIssue>) {
        let source_debug_id = self.source.get_debug_id();
        let sourcemap_debug_id = self.sourcemap.get_debug_id();
        let mismatch = match (&source_debug_id, &sourcemap_debug_id) {
            (Some(source_id), Some(map_id)) if source_id != map_id => {
                Some(DebugIdIssue::Mismatch {
                    source_id: source_id.clone(),
                    map_id: map_id.clone(),
                })
            }
            _ => None,
        };

        (source_debug_id.or(sourcemap_debug_id), mismatch)
    }

    pub fn empty_sourcemap(&self) -> Option<EmptySourcemap> {
        if !self.sourcemap.is_empty() {
            return None;
        }

        Some(
            if self.source.inner.content.len() < WRAPPER_JS_SIZE_THRESHOLD_BYTES {
                EmptySourcemap::Wrapper
            } else {
                EmptySourcemap::Suspect
            },
        )
    }

    pub fn has_release_id(&self) -> bool {
        self.sourcemap.has_release_id()
    }

    pub fn get_release_id(&self) -> Option<String> {
        self.sourcemap.get_release_id()
    }

    /// The release id embedded in the source's injected snippet (event release mode),
    /// as opposed to `get_release_id`, which reads the one stamped into the sourcemap.
    pub fn get_injected_release_id(&self) -> Option<String> {
        let chunk_id = self.get_chunk_id()?;
        get_injected_release_id(&self.source.inner.content, &chunk_id)
    }

    pub fn remove_chunk_id(&mut self, chunk_id: String) -> Result<()> {
        self.remove_chunk_id_with(chunk_id, AdjustmentOptions::default())
    }

    pub fn remove_chunk_id_with(
        &mut self,
        chunk_id: String,
        options: AdjustmentOptions,
    ) -> Result<()> {
        if self.get_chunk_id().as_ref() != Some(&chunk_id) {
            return Err(anyhow!("Chunk ID mismatch"));
        }
        let adjustment = self.source.remove_chunk_id_with(chunk_id, options)?;
        self.sourcemap.apply_adjustment(adjustment)?;
        self.sourcemap.set_chunk_id(None);
        Ok(())
    }

    pub fn update_chunk_id(
        &mut self,
        previous_chunk_id: String,
        new_chunk_id: String,
    ) -> Result<()> {
        self.update_chunk_id_with(
            previous_chunk_id,
            new_chunk_id,
            AdjustmentOptions::default(),
        )
    }

    pub fn update_chunk_id_with(
        &mut self,
        previous_chunk_id: String,
        new_chunk_id: String,
        options: AdjustmentOptions,
    ) -> Result<()> {
        self.remove_chunk_id_with(previous_chunk_id, options)?;
        self.add_chunk_id_with(new_chunk_id, None, options)?;
        Ok(())
    }

    pub fn add_chunk_id(&mut self, chunk_id: String, release_id: Option<&str>) -> Result<()> {
        self.add_chunk_id_with(chunk_id, release_id, AdjustmentOptions::default())
    }

    pub fn add_chunk_id_with(
        &mut self,
        chunk_id: String,
        release_id: Option<&str>,
        options: AdjustmentOptions,
    ) -> Result<()> {
        if self.has_chunk_id() {
            return Err(anyhow!("Chunk ID already set"));
        }

        let adjustment = self
            .source
            .set_chunk_id_with(&chunk_id, release_id, options)?;
        // In cases where sourcemaps are shared across multiple chunks,
        // we should only apply the adjustment if the sourcemap doesn't
        // have a chunk ID set (since otherwise, it's already been adjusted)
        if self.sourcemap.get_chunk_id().is_none() {
            self.sourcemap.apply_adjustment(adjustment)?;
            self.sourcemap.set_chunk_id(Some(chunk_id));
        }
        Ok(())
    }

    pub fn set_release_id(&mut self, release_id: Option<String>) {
        self.sourcemap.set_release_id(release_id);
    }

    pub fn save(&self) -> Result<()> {
        self.source.save()?;
        self.sourcemap.save()?;
        Ok(())
    }
}

pub fn read_pairs(
    selection: impl Iterator<Item = DirEntry>,
    prefix: &Option<String>,
) -> Vec<SourcePair> {
    read_pairs_with(selection, prefix, ReadPairsOptions::default())
}

pub fn read_pairs_with(
    selection: impl Iterator<Item = DirEntry>,
    prefix: &Option<String>,
    options: ReadPairsOptions,
) -> Vec<SourcePair> {
    let mut seen_paths = std::collections::HashSet::new();
    let pairs = selection
        .filter_map(|entry| {
            let path = entry.path();
            let entry_path = path
                .canonicalize()
                .context("failed to canonicalize path")
                .map_err(|e| warn!("skip: {e:?}"))
                .ok()?;
            // Overlapping selection roots yield the same file more than once; a second
            // pass would stamp a fresh chunk id over the first and upload a stale copy.
            if !seen_paths.insert(entry_path.clone()) {
                return None;
            }
            let source = MinifiedSourceFile::load(&entry_path)
                .context("failed to read source")
                .map_err(|e| warn!("skip: {e:?}"))
                .ok()?;
            let sourcemap_path = source
                .get_sourcemap_path(prefix)
                .context("no sourcemap found")
                .map_err(|e| info!("skip: {e:?}"))
                .ok()
                .flatten()?;
            let sourcemap = SourceMapFile::load(&sourcemap_path)
                .context("failed to read sourcemap")
                .map_err(|e| warn!("skip: {e:?}"))
                .ok()?;
            if options.skip_non_sourcemaps && !sourcemap.inner.content.is_sourcemap() {
                info!(
                    "skip: {} names {} as its sourcemap, which has no mappings",
                    entry_path.display(),
                    sourcemap_path.display()
                );
                return None;
            }
            debug!("adding pair for {}", entry_path.display());
            Some(SourcePair { source, sourcemap })
        })
        .collect::<Vec<SourcePair>>();
    info!("found {} pairs", pairs.len());
    pairs
}

// The control characters keep the token from matching anything a bundler writes.
const FILE_PATH_TOKEN: &str = "\u{1}file-path\u{1}";

/// Replace every script file path in `text` with one token, for the event-mode content hash.
/// With content-hashed file names every release renames every chunk, because each chunk carries
/// the release id, and the names appear inside chunks: imports, `sourceMappingURL` and the map's
/// `file`. A path is a run of path characters that ends in `.js`, `.mjs` or `.cjs` with no
/// identifier character after it. The result depends only on `text`, so one chunk hashes the same
/// way in every upload.
///
/// A stored symbol set that this lets the server keep resolves frames the same way: the hash still
/// covers the mappings, so a path that changes length changes the hash. A function named after a
/// run, such as `{"one.js"(){}}`, could only go stale if one chunk id covered two builds whose code
/// differs inside a run. No chunk id does: `@posthog/rollup-plugin` derives its ids before imports
/// become file names, and every other chunk id covers the final content.
fn without_file_paths(text: &str) -> Cow<'_, str> {
    let bytes = text.as_bytes();
    let mut normalized = String::new();
    let mut copied = 0;
    let mut searched = 0;
    while let Some(found) = text[searched..].find("js") {
        let js = searched + found;
        let end = js + 2;
        searched = end;
        let extension = if js >= 1 && bytes[js - 1] == b'.' {
            js - 1
        } else if js >= 2 && matches!(bytes[js - 1], b'm' | b'c') && bytes[js - 2] == b'.' {
            js - 2
        } else {
            continue;
        };
        if text[end..].chars().next().is_some_and(is_identifier_char) {
            continue;
        }
        // Walking back stops at what was already replaced, which keeps the scan linear.
        let Some(start) = text[copied..extension]
            .char_indices()
            .rev()
            .take_while(|(_, c)| is_path_char(*c))
            .last()
            .map(|(offset, _)| copied + offset)
        else {
            continue;
        };
        if normalized.is_empty() {
            normalized.reserve(text.len());
        }
        normalized.push_str(&text[copied..start]);
        normalized.push_str(FILE_PATH_TOKEN);
        copied = end;
    }
    if normalized.is_empty() {
        return Cow::Borrowed(text);
    }
    normalized.push_str(&text[copied..]);
    Cow::Owned(normalized)
}

fn is_identifier_char(c: char) -> bool {
    c.is_alphanumeric() || matches!(c, '_' | '$')
}

fn is_path_char(c: char) -> bool {
    is_identifier_char(c) || matches!(c, '-' | '.' | '/' | '\\' | '~' | '@' | '+')
}

/// Replace the file path in the map's `file` field, the only field that names the chunk rather
/// than its sources.
fn without_file_path_in_file_field(map: &mut SourceMapContent) {
    if let Some(Value::String(file)) = map.fields.get_mut("file") {
        if let Cow::Owned(normalized) = without_file_paths(file) {
            *file = normalized;
        }
    }
}

impl SourcePair {
    /// Turn the pair into an upload payload. The payload always carries the injected artifact;
    /// only the content hash depends on the mode.
    ///
    /// In event mode the hash is computed over the pair with the injection undone (snippet and
    /// chunk-id comment removed, sourcemap adjustment reversed), because the embedded release id
    /// changes every release while the chunk id does not. The server keys its skip-or-conflict
    /// decision on this hash per chunk id, so hashing the embedded id would re-upload every chunk
    /// on every release.
    ///
    /// The hash does cover which snippet variant is embedded. The release variant is longer, so it
    /// shifts every generated column in the uploaded sourcemap. Two builds of one unchanged chunk,
    /// one before a release could be resolved and one after, therefore ship different maps. Equal
    /// hashes would make the server keep the first map and resolve later frames to the wrong
    /// source positions.
    ///
    /// The hash also leaves out script file paths, which change with every release when the
    /// bundler names chunks by content (see `without_file_paths`).
    ///
    /// In symbol-set mode no hash is set and the upload layer hashes the raw payload, matching
    /// the hashes the server already stores for previous uploads.
    pub fn into_upload(self, release_mode: ReleaseMode) -> Result<SymbolSetUpload> {
        self.into_upload_with(release_mode, UploadOptions::default())
    }

    pub fn into_upload_with(
        mut self,
        release_mode: ReleaseMode,
        options: UploadOptions,
    ) -> Result<SymbolSetUpload> {
        let injected_chunk_id = self.get_chunk_id();
        let debug_id = |pair: &Self| {
            if options.log_debug_id_mismatch {
                pair.get_debug_id()
            } else {
                pair.resolve_debug_id().0
            }
        };
        let chunk_id = injected_chunk_id.clone().or_else(|| debug_id(&self)).ok_or_else(|| {
            anyhow!(
                "Chunk ID or debug ID not found in {}. Run 'sourcemap inject' before 'sourcemap upload', enable native debug IDs in the bundler, or use 'sourcemap process' to do both.",
                self.source.inner.path.display()
            )
        })?;
        let release_id = self.sourcemap.get_release_id();
        let source_content = self.source.inner.content.clone();
        let sourcemap_content = serde_json::to_string(&self.sourcemap.inner.content)?;

        let content_hash = match release_mode {
            ReleaseMode::Event => {
                let identity_variant: &[u8] = if injected_chunk_id.is_some() {
                    // Read the variant before the removal, which erases the evidence.
                    let snippet_variant: &[u8] = if self.source.has_release_snippet(&chunk_id) {
                        b"with-release"
                    } else {
                        b"chunk-id-only"
                    };
                    self.remove_chunk_id_with(chunk_id.clone(), options.adjustment)?;
                    snippet_variant
                } else {
                    b"native-debug-id"
                };
                without_file_path_in_file_field(&mut self.sourcemap.inner.content);
                let pristine_map = serde_json::to_string(&self.sourcemap.inner.content)?;
                let pristine_source = without_file_paths(&self.source.inner.content);
                // JSON serialization never contains a raw NUL, so it unambiguously separates
                // the parts (same framing as `stable_chunk_id`).
                Some(content_hash([
                    pristine_source.as_bytes(),
                    b"\0".as_slice(),
                    pristine_map.as_bytes(),
                    b"\0".as_slice(),
                    identity_variant,
                ]))
            }
            ReleaseMode::SymbolSet => None,
        };

        let data = SourceAndMap {
            minified_source: source_content,
            sourcemap: sourcemap_content,
        };

        let data = write_symbol_data(data)?;

        Ok(SymbolSetUpload {
            chunk_id,
            data,
            release_id,
            content_hash,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn normalize(text: &str) -> String {
        without_file_paths(text).replace(FILE_PATH_TOKEN, "<path>")
    }

    #[test]
    fn replaces_script_file_paths() {
        assert_eq!(
            normalize(
                r#"import("./one-BrAf3own.js");const d=["assets/one-BrAf3own.js","https://cdn.example.com/a/b-X_1.mjs"];
//# sourceMappingURL=index-C3e2Htc9.js.map"#
            ),
            r#"import("<path>");const d=["<path>","https:<path>"];
//# sourceMappingURL=<path>.map"#
        );
    }

    #[test]
    fn replaces_directory_names_with_the_path() {
        assert_eq!(
            normalize(r#"import("../Bx9_a1c2/one.cjs")"#),
            r#"import("<path>")"#
        );
        assert_eq!(
            normalize(r#"require("C:\\ci\\Bx9_a1c2\\one.js")"#),
            normalize(r#"require("C:\\ci\\Zq0_w9e8\\one.js")"#)
        );
    }

    #[test]
    fn leaves_other_extensions_and_bare_extensions_alone() {
        let text = r#"["index.json","index.jsx","a.js_b",".js",x.jsonp,"js"]"#;
        assert_eq!(normalize(text), text);
        assert!(matches!(without_file_paths(text), Cow::Borrowed(_)));
    }

    #[test]
    fn handles_repeated_extensions_and_multibyte_text() {
        assert_eq!(normalize("a.jsx.js x.js.map"), "<path> <path>.map");
        assert_eq!(normalize("é日.js 😀 é.mjs"), "<path> 😀 <path>");
        // An emoji is not a path character, so the path starts after it.
        assert_eq!(normalize("😀js.js"), "😀<path>");
    }

    #[test]
    fn empty_sourcemap_is_a_wrapper_only_below_the_size_threshold() {
        // posthog-cli and hog-worker report the two cases differently, so both must draw the
        // line at the same byte.
        let empty_map =
            serde_json::json!({"version": 3, "sources": [], "names": [], "mappings": ""});
        let pair = |source_bytes: usize, map: serde_json::Value| {
            SourcePair::from_parts(
                PathBuf::from("app.js"),
                ";".repeat(source_bytes),
                PathBuf::from("app.js.map"),
                serde_json::from_value(map).expect("Failed to build SourceMapContent"),
            )
        };

        assert_eq!(
            pair(WRAPPER_JS_SIZE_THRESHOLD_BYTES - 1, empty_map.clone()).empty_sourcemap(),
            Some(EmptySourcemap::Wrapper)
        );
        assert_eq!(
            pair(WRAPPER_JS_SIZE_THRESHOLD_BYTES, empty_map).empty_sourcemap(),
            Some(EmptySourcemap::Suspect)
        );
        assert_eq!(
            pair(1, serde_json::json!({"version": 3, "mappings": "AAAA"})).empty_sourcemap(),
            None
        );
    }

    #[test]
    fn replaces_only_the_file_field_of_a_map() {
        // A source can share a chunk's name, and frames resolve to it, so it stays.
        let mut map: SourceMapContent = serde_json::from_value(serde_json::json!({
            "version": 3,
            "file": "assets/index.js",
            "sources": ["../src/index.js"],
            "mappings": "AAAA",
        }))
        .expect("Failed to build SourceMapContent");
        without_file_path_in_file_field(&mut map);

        assert_eq!(map.fields["file"], FILE_PATH_TOKEN);
        assert_eq!(
            map.fields["sources"],
            serde_json::json!(["../src/index.js"])
        );
    }
}
