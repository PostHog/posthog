use std::collections::HashSet;

use affected_services::affected::compute_affected;
use affected_services::graph::{build_old_package_graph, build_package_graph, find_repo_root};
use affected_services::images::{
    build_binary_to_crate_map, parse_images_yaml, ImageConfig, NON_CRATE_IMAGE_TRIGGERS,
};
use guppy::graph::PackageGraph;

fn load_test_fixtures() -> (PackageGraph, Vec<ImageConfig>) {
    let repo_root = find_repo_root().expect("must be in a git repo");
    let graph = build_package_graph(&repo_root.join("rust")).expect("cargo metadata");
    let images =
        parse_images_yaml(&repo_root.join(".github/rust-images.yml")).expect("images YAML");
    (graph, images)
}

// ── Structural tests ─────────────────────────────────────────────

#[test]
fn file_in_workspace_crate_affects_that_crate() {
    let (graph, images) = load_test_fixtures();
    let member = graph.workspace().iter().next().unwrap();
    let fake_path = format!(
        "rust/{}/src/lib.rs",
        member.source().workspace_path().unwrap()
    );
    let result = compute_affected(&[fake_path], None, &graph, &images).unwrap();
    assert!(!result.rebuild_all);
    assert!(
        result.crates.contains(&member.name().to_string()),
        "changing a file in {} should mark it affected",
        member.name()
    );
}

#[test]
fn directly_changed_is_subset_of_crates() {
    let (graph, images) = load_test_fixtures();
    let member = graph.workspace().iter().next().unwrap();
    let fake_path = format!(
        "rust/{}/src/lib.rs",
        member.source().workspace_path().unwrap()
    );
    let result = compute_affected(&[fake_path], None, &graph, &images).unwrap();
    let crates: HashSet<&str> = result.crates.iter().map(|s| s.as_str()).collect();
    for dc in &result.directly_changed {
        assert!(
            crates.contains(dc.as_str()),
            "directly_changed entry {dc} must appear in crates"
        );
    }
}

#[test]
fn rebuild_all_marks_every_workspace_crate() {
    let (graph, images) = load_test_fixtures();
    let result = compute_affected(&["rust/Cargo.lock".into()], None, &graph, &images).unwrap();
    assert!(result.rebuild_all);
    let workspace_count = graph.workspace().iter().count();
    assert_eq!(
        result.crates.len(),
        workspace_count,
        "rebuild_all should include all {} workspace crates",
        workspace_count
    );
}

#[test]
fn file_outside_workspace_produces_no_crates() {
    let (graph, images) = load_test_fixtures();
    let result = compute_affected(&["README.md".into()], None, &graph, &images).unwrap();
    assert!(!result.rebuild_all);
    assert!(result.crates.is_empty());
    assert!(result.images.is_empty());
}

#[test]
fn multi_file_is_union() {
    let (graph, images) = load_test_fixtures();
    let members: Vec<_> = graph.workspace().iter().collect();
    let (a, b) = (&members[0], &members[1]);
    let path_a = format!("rust/{}/src/lib.rs", a.source().workspace_path().unwrap());
    let path_b = format!("rust/{}/src/lib.rs", b.source().workspace_path().unwrap());

    let result_a = compute_affected(std::slice::from_ref(&path_a), None, &graph, &images).unwrap();
    let result_b = compute_affected(std::slice::from_ref(&path_b), None, &graph, &images).unwrap();
    let result_both = compute_affected(&[path_a, path_b], None, &graph, &images).unwrap();

    let union: HashSet<&str> = result_a
        .crates
        .iter()
        .chain(&result_b.crates)
        .map(|s| s.as_str())
        .collect();
    let combined: HashSet<&str> = result_both.crates.iter().map(|s| s.as_str()).collect();
    assert_eq!(
        union, combined,
        "multi-file result should be the union of individual results"
    );
}

// ── Concrete tests ───────────────────────────────────────────────
//
// Update these when adding/removing/renaming services.

#[test]
fn every_image_resolves_to_a_workspace_binary() {
    let (graph, images) = load_test_fixtures();
    let bin_to_crate = build_binary_to_crate_map(&graph);
    for img in &images {
        let bin_name = img.bin.as_deref().unwrap_or(&img.image);
        if NON_CRATE_IMAGE_TRIGGERS
            .iter()
            .any(|&(name, _)| name == img.image)
        {
            continue;
        }
        assert!(
            bin_to_crate.contains_key(bin_name),
            "image '{}' references binary '{}' which doesn't exist in the workspace",
            img.image,
            bin_name,
        );
    }
}

#[test]
fn leaf_service_only_affects_itself_and_dependents() {
    let (graph, images) = load_test_fixtures();
    let result =
        compute_affected(&["rust/capture/src/main.rs".into()], None, &graph, &images).unwrap();
    assert!(!result.rebuild_all);
    assert_eq!(result.directly_changed, vec!["capture"]);
    assert_eq!(result.images, vec!["capture", "capture-logs"]);
}

#[test]
fn proto_change_maps_to_proto_crates() {
    let (graph, images) = load_test_fixtures();
    let result =
        compute_affected(&["proto/personhog.proto".into()], None, &graph, &images).unwrap();
    assert!(!result.rebuild_all);
    assert!(result.directly_changed.contains(&"personhog-proto".into()));
    assert!(result
        .directly_changed
        .contains(&"kafka-assigner-proto".into()));
    assert!(
        result.images.len() > 2,
        "proto change should propagate to multiple images"
    );
}

#[test]
fn migration_only_triggers_sqlx_migrate() {
    let (graph, images) = load_test_fixtures();
    let result = compute_affected(
        &["rust/persons_migrations/new.sql".into()],
        None,
        &graph,
        &images,
    )
    .unwrap();
    assert!(!result.rebuild_all);
    assert_eq!(result.images, vec!["sqlx-migrate"]);
    assert!(result.crates.is_empty());
}

#[test]
fn multi_binary_crate_produces_all_images() {
    let (graph, images) = load_test_fixtures();
    let result = compute_affected(
        &["rust/feature-flags/src/lib.rs".into()],
        None,
        &graph,
        &images,
    )
    .unwrap();
    assert!(!result.rebuild_all);
    assert!(result.images.contains(&"feature-flags".into()));
    assert!(result.images.contains(&"flags-cache-warmer".into()));
}

// ── Determinator two-graph tests ─────────────────────────────────

#[test]
fn same_old_and_new_graph_matches_none_fallback() {
    let (graph, images) = load_test_fixtures();
    let changed = vec!["rust/capture/src/main.rs".into()];

    let result_none = compute_affected(&changed, None, &graph, &images).unwrap();
    let result_some = compute_affected(&changed, Some(&graph), &graph, &images).unwrap();

    assert_eq!(result_none.crates, result_some.crates);
    assert_eq!(result_none.images, result_some.images);
    assert_eq!(result_none.rebuild_all, result_some.rebuild_all);
    assert_eq!(result_none.directly_changed, result_some.directly_changed);
}

#[test]
fn old_graph_no_changed_files_produces_empty() {
    let (graph, images) = load_test_fixtures();
    let result = compute_affected(&[], Some(&graph), &graph, &images).unwrap();
    assert!(!result.rebuild_all);
    assert!(result.crates.is_empty());
    assert!(result.images.is_empty());
}

#[test]
fn old_graph_rebuild_all_on_lockfile() {
    let (graph, images) = load_test_fixtures();
    let result =
        compute_affected(&["rust/Cargo.lock".into()], Some(&graph), &graph, &images).unwrap();
    assert!(result.rebuild_all);
    let workspace_count = graph.workspace().iter().count();
    assert_eq!(result.crates.len(), workspace_count);
}

#[test]
fn old_graph_leaf_service() {
    let (graph, images) = load_test_fixtures();
    let result = compute_affected(
        &["rust/capture/src/main.rs".into()],
        Some(&graph),
        &graph,
        &images,
    )
    .unwrap();
    assert!(!result.rebuild_all);
    assert_eq!(result.directly_changed, vec!["capture"]);
    assert!(result.crates.contains(&"capture".into()));
}

#[test]
fn old_graph_proto_propagation() {
    let (graph, images) = load_test_fixtures();
    let result = compute_affected(
        &["proto/personhog.proto".into()],
        Some(&graph),
        &graph,
        &images,
    )
    .unwrap();
    assert!(!result.rebuild_all);
    assert!(result.directly_changed.contains(&"personhog-proto".into()));
    assert!(
        result.images.len() > 2,
        "proto change should propagate to multiple images via old_graph path"
    );
}

#[test]
fn old_graph_from_master() {
    let repo_root = find_repo_root().expect("must be in a git repo");
    let old_graph = match build_old_package_graph("master", "rust") {
        Some(g) => g,
        None => {
            eprintln!("skipping: could not build old graph from master");
            return;
        }
    };
    let new_graph = build_package_graph(&repo_root.join("rust")).expect("cargo metadata");
    let images =
        parse_images_yaml(&repo_root.join(".github/rust-images.yml")).expect("images YAML");

    let result = compute_affected(
        &["rust/capture/src/main.rs".into()],
        Some(&old_graph),
        &new_graph,
        &images,
    )
    .unwrap();
    assert!(result.crates.contains(&"capture".into()));
}
