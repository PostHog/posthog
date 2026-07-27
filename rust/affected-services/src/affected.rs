use std::collections::HashSet;

use anyhow::{Context, Result};
use determinator::rules::DeterminatorRules;
use determinator::Determinator;
use guppy::graph::{DependencyDirection, PackageGraph};
use serde::Serialize;

use crate::images::{
    build_binary_to_crate_map, map_crates_to_images, non_crate_images_affected, ImageConfig,
};
use crate::RULES_TOML;
const WORKSPACE_PREFIX: &str = "rust/";

#[derive(Debug, Serialize)]
pub struct AffectedResult {
    pub rebuild_all: bool,
    pub images: Vec<String>,
    pub crates: Vec<String>,
    pub directly_changed: Vec<String>,
}

/// Convert repo-root-relative paths to workspace-relative paths.
///
/// `rust/capture/src/main.rs` → `capture/src/main.rs`
/// `proto/personhog.proto`    → `../proto/personhog.proto`
fn to_workspace_relative(repo_path: &str) -> String {
    if let Some(rest) = repo_path.strip_prefix(WORKSPACE_PREFIX) {
        rest.to_string()
    } else {
        format!("../{repo_path}")
    }
}

pub fn compute_affected(
    changed_files: &[String],
    old_graph: Option<&PackageGraph>,
    new_graph: &PackageGraph,
    images: &[ImageConfig],
) -> Result<AffectedResult> {
    let rules =
        DeterminatorRules::parse(RULES_TOML).context("failed to parse determinator rules")?;

    let workspace_paths: Vec<String> = changed_files
        .iter()
        .map(|f| to_workspace_relative(f))
        .collect();

    // When no old graph is available (single-graph fallback) and Cargo.lock
    // changed, the determinator can't diff resolved dependencies — it sees
    // old == new. Force a full rebuild to be safe.
    if old_graph.is_none()
        && changed_files
            .iter()
            .any(|f| f == "rust/Cargo.lock" || f == "Cargo.lock")
    {
        let mut all_images: Vec<String> = images.iter().map(|i| i.image.clone()).collect();
        all_images.sort();
        let mut all_crates: Vec<String> = new_graph
            .workspace()
            .iter()
            .map(|p| p.name().to_string())
            .collect();
        all_crates.sort();
        return Ok(AffectedResult {
            rebuild_all: true,
            images: all_images,
            crates: all_crates,
            directly_changed: Vec::new(),
        });
    }

    let old = old_graph.unwrap_or(new_graph);
    let mut det = Determinator::new(old, new_graph);
    det.set_rules(&rules)
        .context("failed to set determinator rules")?;
    det.add_changed_paths(workspace_paths.iter().map(|s| s.as_str()));
    let result = det.compute();

    let workspace_size = new_graph.workspace().iter().count();
    let affected_count = result.affected_set.len();
    let rebuild_all = affected_count == workspace_size;

    let bin_to_crate = build_binary_to_crate_map(new_graph);

    let affected_names: HashSet<String> = result
        .affected_set
        .packages(DependencyDirection::Forward)
        .map(|p| p.name().to_string())
        .collect();

    let directly_changed_names: HashSet<String> = result
        .path_changed_set
        .packages(DependencyDirection::Forward)
        .map(|p| p.name().to_string())
        .collect();

    if rebuild_all {
        let mut all_images: Vec<String> = images.iter().map(|i| i.image.clone()).collect();
        all_images.sort();
        let mut all_crates: Vec<String> = affected_names.into_iter().collect();
        all_crates.sort();
        return Ok(AffectedResult {
            rebuild_all: true,
            images: all_images,
            crates: all_crates,
            directly_changed: Vec::new(),
        });
    }

    let mut affected_images = map_crates_to_images(&affected_names, &bin_to_crate, images);
    for img in non_crate_images_affected(changed_files) {
        if !affected_images.contains(&img) {
            affected_images.push(img);
        }
    }
    affected_images.sort();

    let mut crates: Vec<String> = affected_names.into_iter().collect();
    crates.sort();
    let mut directly: Vec<String> = directly_changed_names.into_iter().collect();
    directly.sort();

    Ok(AffectedResult {
        rebuild_all: false,
        images: affected_images,
        crates,
        directly_changed: directly,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn workspace_relative_strips_rust_prefix() {
        assert_eq!(
            to_workspace_relative("rust/capture/src/main.rs"),
            "capture/src/main.rs"
        );
    }

    #[test]
    fn workspace_relative_adds_parent_for_external() {
        assert_eq!(
            to_workspace_relative("proto/personhog.proto"),
            "../proto/personhog.proto"
        );
    }

    #[test]
    fn workspace_relative_github_files() {
        assert_eq!(
            to_workspace_relative(".github/rust-images.yml"),
            "../.github/rust-images.yml"
        );
    }

    #[test]
    fn rules_parse_successfully() {
        DeterminatorRules::parse(RULES_TOML).expect("rules TOML should parse");
    }
}
