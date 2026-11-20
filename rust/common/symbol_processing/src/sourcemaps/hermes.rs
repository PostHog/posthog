use std::path::PathBuf;

use anyhow::{anyhow, Context, Result};
use tracing::info;

use crate::sourcemaps::{
    content::{SourceMapContent, SourceMapFile},
    source_pairs::SourcePair,
};

pub fn get_composed_map(pair: &SourcePair) -> Result<Option<SourceMapFile>> {
    let sourcemap_path = &pair.sourcemap.inner.path;

    // Look for composed map: change .bundle.map to .bundle.hbc.composed.map
    let composed_path = sourcemap_path
        .to_str()
        .and_then(|s| {
            if s.ends_with(".bundle.map") {
                Some(PathBuf::from(
                    s.replace(".bundle.map", ".bundle.hbc.composed.map"),
                ))
            } else if s.ends_with(".jsbundle.map") {
                Some(PathBuf::from(
                    s.replace(".jsbundle.map", ".jsbundle.hbc.composed.map"),
                ))
            } else {
                None
            }
        })
        .ok_or_else(|| anyhow!("Could not determine composed map path for {sourcemap_path:?}"))?;

    if !composed_path.exists() {
        info!(
            "Skipping {} - no composed map found at {}",
            sourcemap_path.display(),
            composed_path.display()
        );
        return Ok(None);
    }

    Ok(Some(SourceMapFile::load(&composed_path).context(
        format!("reading composed map at {composed_path:?}"),
    )?))
}

/// Carry the chunk identity and release from the packager map into the hermes-composed map.
/// Expo stamps only a `debugId` on the packager map, so the id must come from the upload
/// fallback — reading the stamped chunk id alone leaves the composed map id-less and the
/// upload silently empty.
pub fn clone_metadata(minified_map: &SourceMapFile, composed_map: &mut SourceMapFile) {
    clone_content_metadata(&minified_map.inner.content, &mut composed_map.inner.content);
}

pub fn clone_content_metadata(
    minified_map: &SourceMapContent,
    composed_map: &mut SourceMapContent,
) {
    if let Some(chunk_id) = minified_map.upload_chunk_id() {
        composed_map.chunk_id = Some(chunk_id);
    }

    // Copy the id even when there is none. A build that changes to event release mode then
    // clears the id a previous run stamped. Without this, the composed map uploads still bound
    // to that release.
    composed_map.release_id = minified_map.release_id.clone();
}

#[cfg(test)]
mod test {
    use super::clone_metadata;
    use crate::files::SourceFile;
    use crate::sourcemaps::content::SourceMapFile;
    use std::path::PathBuf;

    fn map_from(json: serde_json::Value) -> SourceMapFile {
        SourceMapFile {
            inner: SourceFile::new(
                PathBuf::from("main.jsbundle.map"),
                serde_json::from_value(json).unwrap(),
            ),
        }
    }

    #[test]
    fn clone_carries_a_debug_id_only_packager_map_into_the_composed_map() {
        // The Expo metro plugin stamps only `debugId` on the packager map. Clone must land
        // that id on the composed map, or `hermes upload` finds no id and uploads nothing
        // while the build stays green.
        let minified = map_from(serde_json::json!({
            "version": 3,
            "mappings": "AAAA",
            "sources": ["App.js"],
            "names": [],
            "debugId": "c96bfa94-ca84-4f98-8d5e-f15adba692ca",
            "release_id": "11111111-2222-4333-8444-555555555555",
        }));
        let mut composed = map_from(serde_json::json!({
            "version": 3,
            "mappings": "AAAA",
            "sources": ["App.js"],
            "names": [],
            "x_hermes_function_offsets": {},
        }));

        clone_metadata(&minified, &mut composed);

        assert_eq!(
            composed.get_chunk_id().as_deref(),
            Some("c96bfa94-ca84-4f98-8d5e-f15adba692ca")
        );
        assert_eq!(
            composed.get_release_id().as_deref(),
            Some("11111111-2222-4333-8444-555555555555")
        );
    }

    #[test]
    fn clone_clears_a_release_id_the_composed_map_still_carries() {
        // A build that changes to event release mode still has the previous run's release id on
        // the composed map. To copy only the ids that exist would upload it bound to that
        // release. That is the collision event mode prevents.
        let minified = map_from(serde_json::json!({
            "version": 3,
            "mappings": "AAAA",
            "sources": ["App.js"],
            "names": [],
            "debugId": "c96bfa94-ca84-4f98-8d5e-f15adba692ca",
        }));
        let mut composed = map_from(serde_json::json!({
            "version": 3,
            "mappings": "AAAA",
            "sources": ["App.js"],
            "names": [],
            "release_id": "11111111-2222-4333-8444-555555555555",
            "x_hermes_function_offsets": {},
        }));

        clone_metadata(&minified, &mut composed);

        assert_eq!(composed.get_release_id(), None);
    }
}
