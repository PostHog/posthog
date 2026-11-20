use std::path::Path;

use anyhow::Result;

use crate::sourcemaps::{
    constant::CHUNK_ID_NAMESPACE,
    content::AdjustmentOptions,
    source_pairs::{DebugIdIssue, SourcePair},
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InjectAction {
    Injected,
    /// The pair kept or replaced its chunk id, and its release changed.
    ReleaseUpdated,
    Unchanged,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InjectedPair {
    pub action: InjectAction,
    pub chunk_id: String,
}

/// Event-mode injection (`--release-mode=event`): content-addressed chunk ids plus an optional
/// `_posthogReleaseId` payload. A bundler-emitted debug id, when present, is adopted as the
/// chunk id so one id identifies the chunk across the whole toolchain.
pub fn inject_pairs(
    mut pairs: Vec<SourcePair>,
    release_id: Option<&str>,
) -> Result<Vec<SourcePair>> {
    for pair in &mut pairs {
        inject_pair(
            pair,
            release_id,
            AdjustmentOptions::default(),
            &mut |path, issue| issue.log(path),
        )?;
    }

    Ok(pairs)
}

/// Event-mode injection of one pair. `on_debug_id_issue` receives the source path and each fault
/// found in the bundler's debug ids, before the pair changes, so the caller words the warning.
pub fn inject_pair(
    pair: &mut SourcePair,
    release_id: Option<&str>,
    options: AdjustmentOptions,
    on_debug_id_issue: &mut dyn FnMut(&Path, DebugIdIssue),
) -> Result<InjectedPair> {
    let Some(chunk_id) = pair.get_chunk_id() else {
        let chunk_id = adopted_debug_id(pair, on_debug_id_issue)
            .unwrap_or_else(|| stable_chunk_id(&pair.source.inner.content));
        pair.add_chunk_id_with(chunk_id.clone(), release_id, options)?;

        return Ok(InjectedPair {
            action: InjectAction::Injected,
            chunk_id,
        });
    };

    // Already injected: the chunk id is content-addressed and the content didn't change,
    // so keep it — but refresh the embedded release id when a different release resolved,
    // or a re-run over an existing dist would keep reporting the old release on every
    // event. When no release resolves, leave the pair untouched: failing to resolve is
    // missing information (e.g. no git context), not evidence the embedded id is stale.
    let unchanged = |chunk_id: String| InjectedPair {
        action: InjectAction::Unchanged,
        chunk_id,
    };
    let Some(release_id) = release_id else {
        return Ok(unchanged(chunk_id));
    };
    if pair.get_injected_release_id().as_deref() == Some(release_id) {
        return Ok(unchanged(chunk_id));
    }

    pair.remove_chunk_id_with(chunk_id.clone(), options)?;
    pair.add_chunk_id_with(chunk_id.clone(), Some(release_id), options)?;

    Ok(InjectedPair {
        action: InjectAction::ReleaseUpdated,
        chunk_id,
    })
}

/// A bundler-emitted ECMA-426 debug id is already content-derived, so adopt it as the chunk id
/// instead of deriving our own. Non-UUID values are refused: the id flows into upload rows and
/// SDK events, and a malformed one is worse than a derived one.
fn adopted_debug_id(
    pair: &SourcePair,
    on_debug_id_issue: &mut dyn FnMut(&Path, DebugIdIssue),
) -> Option<String> {
    let source_path = &pair.source.inner.path;
    let (debug_id, mismatch) = pair.resolve_debug_id();
    if let Some(mismatch) = mismatch {
        on_debug_id_issue(source_path, mismatch);
    }

    let debug_id = debug_id?;
    if uuid::Uuid::parse_str(&debug_id).is_err() {
        on_debug_id_issue(source_path, DebugIdIssue::Malformed { debug_id });
        return None;
    }
    Some(debug_id)
}

/// Symbol-set-mode injection (the default): a random per-build chunk id and the created release
/// id stamped into the sourcemap. Regenerates the chunk id whenever the release id changes or is
/// missing.
pub fn inject_pairs_legacy(
    mut pairs: Vec<SourcePair>,
    created_release_id: Option<String>,
) -> Result<Vec<SourcePair>> {
    for pair in &mut pairs {
        inject_pair_legacy(
            pair,
            created_release_id.as_deref(),
            AdjustmentOptions::default(),
            || uuid::Uuid::now_v7().to_string(),
        )?;
    }

    Ok(pairs)
}

/// Whether symbol-set-mode injection gives the pair a new chunk id. A pair whose release changed
/// gets one, because PostHog binds a symbol set to one release.
pub fn needs_new_chunk_id(pair: &SourcePair, release_id: Option<&str>) -> bool {
    pair.get_release_id().as_deref() != release_id || pair.get_chunk_id().is_none()
}

/// Symbol-set-mode injection of one pair. `new_chunk_id` runs only when the pair needs a new id,
/// see [`needs_new_chunk_id`]. posthog-cli mints a UUIDv7 there, and hog-worker returns the id
/// hog generated, so the id hog reports is the one written.
pub fn inject_pair_legacy(
    pair: &mut SourcePair,
    release_id: Option<&str>,
    options: AdjustmentOptions,
    new_chunk_id: impl FnOnce() -> String,
) -> Result<InjectedPair> {
    let previous_chunk_id = pair.get_chunk_id();
    // We only update release ids and chunk ids when the release id changed or is not present
    if !needs_new_chunk_id(pair, release_id) {
        return Ok(InjectedPair {
            action: InjectAction::Unchanged,
            chunk_id: previous_chunk_id.expect("a pair that needs no chunk id has one"),
        });
    }

    pair.set_release_id(release_id.map(str::to_string));

    let chunk_id = new_chunk_id();
    let action = if let Some(previous_chunk_id) = previous_chunk_id {
        pair.update_chunk_id_with(previous_chunk_id, chunk_id.clone(), options)?;
        InjectAction::ReleaseUpdated
    } else {
        pair.add_chunk_id_with(chunk_id.clone(), None, options)?;
        InjectAction::Injected
    };

    Ok(InjectedPair { action, chunk_id })
}

/// Deterministically derive a chunk id from the pristine minified source (UUIDv5). Identical
/// builds produce identical ids on every machine and rebuild, so uploads dedupe instead of
/// minting a per-build random id.
///
/// The sourcemap is deliberately not part of the identity. It carries `sourcesContent`, so a
/// comment-only edit rewrites the map while the minified code stays byte-identical, and folding
/// the map in would mint a new chunk for code that never changed. The map still reaches the
/// server, because the upload hashes the payload it sends: a map-only change is a content
/// change, and event mode overwrites the stored symbol set with the newer map.
pub fn stable_chunk_id(source_content: &str) -> String {
    uuid::Uuid::new_v5(&CHUNK_ID_NAMESPACE, source_content.as_bytes()).to_string()
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use super::*;
    use crate::sourcemaps::content::SourceMapContent;

    const SOURCE: &str = "console.log(1);\n//# sourceMappingURL=app.js.map\n";

    fn pair(source: &str, map: serde_json::Value) -> SourcePair {
        SourcePair::from_parts(
            PathBuf::from("app.js"),
            source.to_string(),
            PathBuf::from("app.js.map"),
            serde_json::from_value::<SourceMapContent>(map).unwrap(),
        )
    }

    fn plain_map() -> serde_json::Value {
        serde_json::json!({
            "version": 3,
            "sources": ["app.ts"],
            "sourcesContent": ["console.log(1)\n"],
            "names": [],
            "mappings": "AAAA",
        })
    }

    #[test]
    fn stable_chunk_id_tracks_the_minified_source() {
        let id = stable_chunk_id("code();");

        assert_eq!(id, stable_chunk_id("code();"));
        assert_ne!(id, stable_chunk_id("other();"));
    }

    #[test]
    fn adjustment_content_does_not_change_the_injected_pair() {
        // hog-worker injects with `include_content: false` and posthog-cli with `true`. A
        // difference in the pair they write would make one tool's upload conflict with the
        // other's.
        let inject = |include_content: bool| {
            let mut pair = pair(SOURCE, plain_map());
            inject_pair(
                &mut pair,
                Some("release"),
                AdjustmentOptions { include_content },
                &mut |_, _| {},
            )
            .unwrap();

            (
                pair.source.inner.content,
                serde_json::to_string(&pair.sourcemap.inner.content).unwrap(),
            )
        };

        assert_eq!(inject(true), inject(false));
    }

    #[test]
    fn inject_pair_reports_each_step_of_a_release_change() {
        let mut pair = pair(SOURCE, plain_map());
        let mut inject = |release_id: Option<&str>| {
            inject_pair(
                &mut pair,
                release_id,
                AdjustmentOptions::default(),
                &mut |_, _| {},
            )
            .unwrap()
        };

        let first = inject(Some("one"));
        let same_release = inject(Some("one"));
        let no_release = inject(None);
        let new_release = inject(Some("two"));

        assert_eq!(first.action, InjectAction::Injected);
        assert_eq!(first.chunk_id, stable_chunk_id(SOURCE));
        assert_eq!(same_release.action, InjectAction::Unchanged);
        assert_eq!(no_release.action, InjectAction::Unchanged);
        assert_eq!(new_release.action, InjectAction::ReleaseUpdated);
        assert_eq!(new_release.chunk_id, first.chunk_id);
    }

    #[test]
    fn inject_pair_hands_debug_id_faults_to_the_caller() {
        let mut map = plain_map();
        map["debugId"] = "c96bfa94-ca84-4f98-8d5e-f15adba692ca".into();
        let mut pair = pair(&format!("{SOURCE}//# debugId=not-a-uuid\n"), map);
        let mut issues = Vec::new();

        let injected = inject_pair(
            &mut pair,
            None,
            AdjustmentOptions::default(),
            &mut |path, issue| issues.push((path.to_path_buf(), issue)),
        )
        .unwrap();

        let path = PathBuf::from("app.js");
        assert_eq!(
            issues,
            vec![
                (
                    path.clone(),
                    DebugIdIssue::Mismatch {
                        source_id: "not-a-uuid".to_string(),
                        map_id: "c96bfa94-ca84-4f98-8d5e-f15adba692ca".to_string(),
                    }
                ),
                (
                    path,
                    DebugIdIssue::Malformed {
                        debug_id: "not-a-uuid".to_string(),
                    }
                ),
            ]
        );
        assert_ne!(injected.chunk_id, "not-a-uuid");
    }

    #[test]
    fn inject_pair_legacy_uses_the_callers_chunk_id_only_when_the_release_changes() {
        let mut pair = pair(SOURCE, plain_map());
        let mut inject = |release_id: Option<&str>, chunk_id: &str| {
            inject_pair_legacy(&mut pair, release_id, AdjustmentOptions::default(), || {
                chunk_id.to_string()
            })
            .unwrap()
        };

        let first = inject(Some("one"), "chunk-a");
        let same_release = inject(Some("one"), "chunk-b");
        let new_release = inject(Some("two"), "chunk-c");

        assert_eq!(
            (first.action, first.chunk_id.as_str()),
            (InjectAction::Injected, "chunk-a")
        );
        assert_eq!(
            (same_release.action, same_release.chunk_id.as_str()),
            (InjectAction::Unchanged, "chunk-a")
        );
        assert_eq!(
            (new_release.action, new_release.chunk_id.as_str()),
            (InjectAction::ReleaseUpdated, "chunk-c")
        );
        assert_eq!(pair.get_release_id().as_deref(), Some("two"));
    }
}
