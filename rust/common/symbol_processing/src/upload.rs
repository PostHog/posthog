use tracing::warn;

use crate::files::content_hash;

/// How exceptions get associated with a release. The mode decides the content hash of a source
/// pair, see [`crate::sourcemaps::source_pairs::SourcePair::into_upload`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReleaseMode {
    SymbolSet,
    Event,
}

#[derive(Debug, Clone)]
pub struct SymbolSetUpload {
    pub chunk_id: String,
    pub release_id: Option<String>,

    pub data: Vec<u8>,

    /// Precomputed hash for the server's skip-identical-content check; `None` hashes `data`
    /// as-is. Set this when `data` contains bytes that vary between builds of identical code
    /// (e.g. an injected release id), so unchanged chunks still skip re-upload.
    pub content_hash: Option<String>,
}

impl SymbolSetUpload {
    pub fn cheap_clone(&self) -> Self {
        Self {
            chunk_id: self.chunk_id.clone(),
            release_id: self.release_id.clone(),
            data: vec![],
            content_hash: self.content_hash.clone(),
        }
    }

    /// The hash the upload protocol sends for this symbol set: the precomputed one when the
    /// builder set it, else the hash of the container bytes.
    pub fn resolved_content_hash(&self) -> String {
        self.content_hash
            .clone()
            .unwrap_or_else(|| content_hash([&self.data]))
    }
}

/// Coalesce uploads that share a chunk_id, keeping the first occurrence. The check and start
/// requests reject a batch with a repeated id, before they filter out the chunks the server
/// already has.
pub fn dedup_uploads_by_chunk_id(uploads: Vec<SymbolSetUpload>) -> Vec<SymbolSetUpload> {
    let mut seen = std::collections::HashSet::new();
    let mut deduped = Vec::with_capacity(uploads.len());
    for upload in uploads {
        if seen.insert(upload.chunk_id.clone()) {
            deduped.push(upload);
        } else {
            warn!(
                "Duplicate chunk id {} across symbol sets; keeping the first",
                upload.chunk_id
            );
        }
    }
    deduped
}
