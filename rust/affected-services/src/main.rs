use std::collections::{HashMap, HashSet};
use std::io::BufRead;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{Context, Result};
use clap::{Parser, ValueEnum};
use determinator::Determinator;
use determinator::rules::DeterminatorRules;
use guppy::graph::{DependencyDirection, PackageGraph};
use guppy::MetadataCommand;
use serde::Serialize;

const RULES_TOML: &str = include_str!("../determinator-rules.toml");

const WORKSPACE_PREFIX: &str = "rust/";

const NON_CRATE_IMAGE_TRIGGERS: &[(&str, &[&str])] = &[(
    "sqlx-migrate",
    &[
        "rust/persons_migrations/",
        "rust/behavioral_cohorts_migrations/",
        "rust/cyclotron-core/migrations/",
        "rust/cyclotron-node-migrations/",
        "rust/flags_read_store_migrations/",
        "rust/bin/migrate-",
        "rust/Dockerfile.sqlx-migrate",
    ],
)];

#[derive(Debug, Default)]
struct ImageConfig {
    image: String,
    bin: Option<String>,
}

#[derive(Debug, Serialize)]
struct AffectedResult {
    rebuild_all: bool,
    images: Vec<String>,
    crates: Vec<String>,
    directly_changed: Vec<String>,
}

#[derive(Parser)]
#[command(about = "Compute affected Rust services from changed files")]
struct Cli {
    #[arg(long, conflicts_with_all = ["files", "stdin", "dump_graph"])]
    base_ref: Option<String>,

    #[arg(long, num_args = 1.., conflicts_with_all = ["base_ref", "stdin", "dump_graph"])]
    files: Option<Vec<String>>,

    #[arg(long, conflicts_with_all = ["base_ref", "files", "dump_graph"])]
    stdin: bool,

    #[arg(long, conflicts_with_all = ["base_ref", "files", "stdin"])]
    dump_graph: bool,

    #[arg(long)]
    workspace_dir: Option<PathBuf>,

    #[arg(long)]
    images_file: Option<PathBuf>,

    #[arg(long, value_enum, default_value = "json")]
    output: OutputFormat,
}

#[derive(Clone, ValueEnum)]
enum OutputFormat {
    Json,
    Images,
    Crates,
}

// ── I/O ────────────────────────────────────────────────────────────

fn find_repo_root() -> Result<PathBuf> {
    let out = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .output()
        .context("failed to run git")?;
    Ok(PathBuf::from(
        String::from_utf8(out.stdout)?.trim().to_string(),
    ))
}

fn get_changed_files(base_ref: &str) -> Result<Vec<String>> {
    let out = Command::new("git")
        .args(["diff", "--name-only", &format!("{base_ref}...HEAD")])
        .output()
        .context("failed to run git diff")?;
    anyhow::ensure!(
        out.status.success(),
        "git diff exited with {}: {}",
        out.status,
        String::from_utf8_lossy(&out.stderr).trim()
    );
    Ok(String::from_utf8(out.stdout)?
        .lines()
        .filter(|l| !l.is_empty())
        .map(String::from)
        .collect())
}

fn build_package_graph(workspace_dir: &Path) -> Result<PackageGraph> {
    let mut cmd = MetadataCommand::new();
    cmd.current_dir(workspace_dir);
    cmd.build_graph()
        .context("failed to build package graph from cargo metadata")
}

// ── Old graph from base revision ──────────────────────────────────

struct TempWorktree {
    path: PathBuf,
}

impl TempWorktree {
    fn create(base_ref: &str) -> Result<Self> {
        let path =
            std::env::temp_dir().join(format!("affected-services-{}", std::process::id()));
        let out = Command::new("git")
            .args([
                "worktree",
                "add",
                "--detach",
                &path.to_string_lossy(),
                base_ref,
            ])
            .output()
            .context("failed to create git worktree")?;
        anyhow::ensure!(
            out.status.success(),
            "git worktree add failed: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        );
        Ok(Self { path })
    }

    fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for TempWorktree {
    fn drop(&mut self) {
        let _ = Command::new("git")
            .args([
                "worktree",
                "remove",
                "--force",
                &self.path.to_string_lossy(),
            ])
            .status();
    }
}

fn build_old_package_graph(base_ref: &str, workspace_subdir: &str) -> Option<PackageGraph> {
    let worktree = match TempWorktree::create(base_ref) {
        Ok(w) => w,
        Err(e) => {
            eprintln!("warning: could not create worktree at {base_ref}: {e}");
            return None;
        }
    };

    let old_workspace = worktree.path().join(workspace_subdir);
    if !old_workspace.join("Cargo.toml").exists() {
        eprintln!("warning: {base_ref} has no {workspace_subdir}/Cargo.toml");
        return None;
    }

    let mut cmd = MetadataCommand::new();
    cmd.current_dir(&old_workspace);
    // --frozen: use Cargo.lock exactly, no network access
    cmd.other_options(["--frozen"]);
    match cmd.build_graph() {
        Ok(graph) => Some(graph),
        Err(e) => {
            eprintln!("warning: could not build old package graph: {e}");
            None
        }
    }
}

fn parse_images_yaml(path: &Path) -> Result<Vec<ImageConfig>> {
    let content = std::fs::read_to_string(path)
        .with_context(|| format!("failed to read {}", path.display()))?;
    let mut items = Vec::new();
    let mut current: Option<ImageConfig> = None;

    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        if line.starts_with("- ") {
            if let Some(item) = current.take() {
                items.push(item);
            }
            current = Some(ImageConfig::default());
            let rest = trimmed.strip_prefix("- ").unwrap_or(trimmed);
            if let Some(item) = current.as_mut() {
                apply_field(item, rest);
            }
        } else if let Some(ref mut item) = current {
            apply_field(item, trimmed);
        }
    }
    if let Some(item) = current {
        items.push(item);
    }
    Ok(items)
}

fn apply_field(config: &mut ImageConfig, line: &str) {
    if let Some((key, value)) = line.split_once(':') {
        let value = value.trim();
        match key.trim() {
            "image" => config.image = value.to_string(),
            "bin" => config.bin = Some(value.to_string()),
            _ => {}
        }
    }
}

// ── Path transformation ───────────────────────────────────────────

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

// ── Image mapping ─────────────────────────────────────────────────

fn build_binary_to_crate_map(graph: &PackageGraph) -> HashMap<String, String> {
    let mut map = HashMap::new();
    for member in graph.workspace().iter() {
        for target in member.build_targets() {
            if let guppy::graph::BuildTargetId::Binary(name) = target.id() {
                map.insert(name.to_string(), member.name().to_string());
            }
        }
    }
    map
}

fn map_crates_to_images(
    affected: &HashSet<String>,
    bin_to_crate: &HashMap<String, String>,
    images: &[ImageConfig],
) -> Vec<String> {
    let mut result: Vec<String> = images
        .iter()
        .filter_map(|img| {
            let bin_name = img.bin.as_deref().unwrap_or(&img.image);
            let owning_crate = bin_to_crate.get(bin_name)?;
            affected.contains(owning_crate).then(|| img.image.clone())
        })
        .collect();
    result.sort();
    result
}

fn non_crate_images_affected(files: &[String]) -> Vec<String> {
    let mut result = Vec::new();
    for &(image, prefixes) in NON_CRATE_IMAGE_TRIGGERS {
        if files
            .iter()
            .any(|f| prefixes.iter().any(|p| f.starts_with(p)))
        {
            result.push(image.to_string());
        }
    }
    result
}

// ── Core logic ────────────────────────────────────────────────────

fn compute_affected(
    changed_files: &[String],
    old_graph: Option<&PackageGraph>,
    new_graph: &PackageGraph,
    images: &[ImageConfig],
) -> Result<AffectedResult> {
    let rules = DeterminatorRules::parse(RULES_TOML)
        .context("failed to parse determinator rules")?;

    let workspace_paths: Vec<String> = changed_files
        .iter()
        .map(|f| to_workspace_relative(f))
        .collect();

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

// ── Dump mode ─────────────────────────────────────────────────────

fn dump_graph(graph: &PackageGraph, images: &[ImageConfig]) {
    let bin_to_crate = build_binary_to_crate_map(graph);

    let mut crate_to_bins: HashMap<&str, Vec<&str>> = HashMap::new();
    for (bin_name, crate_name) in &bin_to_crate {
        crate_to_bins
            .entry(crate_name.as_str())
            .or_default()
            .push(bin_name.as_str());
    }

    let deployable_crates: HashSet<&str> = images
        .iter()
        .filter_map(|img| {
            let bin_name = img.bin.as_deref().unwrap_or(&img.image);
            bin_to_crate.get(bin_name).map(|s| s.as_str())
        })
        .collect();

    println!("REVERSE DEPENDENCY GRAPH");
    println!("(crate → workspace crates that depend on it)");
    println!("{}", "=".repeat(70));

    let mut members: Vec<_> = graph.workspace().iter().collect();
    members.sort_by_key(|m| m.name().to_string());

    for member in &members {
        let name = member.name();

        let mut dependents: Vec<String> = Vec::new();
        for link in member.reverse_direct_links() {
            let from = link.from();
            if !graph.workspace().contains_name(from.name()) {
                continue;
            }
            let is_dev_only = !link.normal().is_present() && !link.build().is_present();
            if !is_dev_only {
                dependents.push(from.name().to_string());
            }
        }
        dependents.sort();

        let mut tags = Vec::new();
        if let Some(bins) = crate_to_bins.get(name) {
            let mut bins = bins.clone();
            bins.sort();
            tags.push(format!("bins: {}", bins.join(", ")));
        }
        if deployable_crates.contains(name) {
            tags.push("deployable".to_string());
        }
        let tag_str = if tags.is_empty() {
            String::new()
        } else {
            format!("  [{}]", tags.join(", "))
        };

        let dep_str = if dependents.is_empty() {
            "(leaf)".to_string()
        } else {
            dependents.join(", ")
        };

        println!("  {name}{tag_str}");
        println!("    depended on by: {dep_str}");
    }

    println!();
    println!("TRANSITIVE IMPACT (crates affecting >2 others)");
    println!("{}", "=".repeat(70));

    let rules = DeterminatorRules::parse(RULES_TOML).expect("rules should parse");

    let mut impacts: Vec<(&str, usize, Vec<String>)> = Vec::new();
    for member in &members {
        let name = member.name();
        let workspace_path = format!("{}/src/lib.rs", member.source().workspace_path().unwrap());
        let mut det = Determinator::new(graph, graph);
        det.set_rules(&rules).unwrap();
        det.add_changed_paths(std::iter::once(workspace_path.as_str()));
        let result = det.compute();

        let affected: HashSet<String> = result
            .affected_set
            .packages(DependencyDirection::Forward)
            .map(|p| p.name().to_string())
            .collect();
        let affected_images = map_crates_to_images(&affected, &bin_to_crate, images);
        let dep_count = affected.len().saturating_sub(1);
        if dep_count > 2 {
            impacts.push((name, dep_count, affected_images));
        }
    }
    impacts.sort_by(|a, b| b.1.cmp(&a.1));

    for (crate_name, dep_count, imgs) in &impacts {
        println!("  {crate_name} → {dep_count} crates, {} images", imgs.len());
        if !imgs.is_empty() {
            println!("    images: {}", imgs.join(", "));
        }
    }

    println!();
    println!("BINARY → CRATE → IMAGE MAPPING");
    println!("{}", "=".repeat(70));

    let mut sorted_images: Vec<&ImageConfig> = images.iter().collect();
    sorted_images.sort_by_key(|i| &i.image);

    for img in sorted_images {
        let bin_name = img.bin.as_deref().unwrap_or(&img.image);
        let owning = bin_to_crate
            .get(bin_name)
            .map(|s| s.as_str())
            .unwrap_or("???");
        let mut extra = String::new();
        if img.bin.is_some() {
            extra.push_str(&format!("  (bin={bin_name})"));
        }
        println!(
            "  image:{}  ←  crate:{owning}  ←  bin:{bin_name}{extra}",
            img.image
        );
    }
}

// ── Main ──────────────────────────────────────────────────────────

fn main() -> Result<()> {
    let cli = Cli::parse();

    let repo_root = find_repo_root()?;
    let workspace_dir = cli.workspace_dir.unwrap_or_else(|| repo_root.join("rust"));
    let images_file = cli
        .images_file
        .unwrap_or_else(|| repo_root.join(".github/rust-images.yml"));

    let new_graph = build_package_graph(&workspace_dir)?;
    let images = parse_images_yaml(&images_file)?;

    if cli.dump_graph {
        dump_graph(&new_graph, &images);
        return Ok(());
    }

    let (changed_files, old_graph) = if let Some(files) = cli.files {
        (files, None)
    } else if cli.stdin {
        let files = std::io::stdin()
            .lock()
            .lines()
            .map_while(Result::ok)
            .filter(|l| !l.is_empty())
            .collect();
        (files, None)
    } else if let Some(base_ref) = &cli.base_ref {
        let files = get_changed_files(base_ref)?;
        let workspace_subdir = workspace_dir
            .strip_prefix(&repo_root)
            .unwrap_or(Path::new("rust"))
            .to_string_lossy()
            .to_string();
        let old = build_old_package_graph(base_ref, &workspace_subdir);
        (files, old)
    } else {
        anyhow::bail!("one of --base-ref, --files, --stdin, or --dump-graph is required");
    };

    let result = compute_affected(&changed_files, old_graph.as_ref(), &new_graph, &images)?;

    match cli.output {
        OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&result)?),
        OutputFormat::Images => println!("{}", serde_json::to_string(&result.images)?),
        OutputFormat::Crates => println!("{}", serde_json::to_string(&result.crates)?),
    }
    Ok(())
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
    fn non_crate_migration_trigger() {
        let affected = non_crate_images_affected(&["rust/persons_migrations/new.sql".into()]);
        assert_eq!(affected, vec!["sqlx-migrate"]);
    }

    #[test]
    fn non_crate_no_false_positives() {
        let affected = non_crate_images_affected(&["rust/capture/src/main.rs".into()]);
        assert!(affected.is_empty());
    }

    #[test]
    fn image_mapping() {
        let affected = HashSet::from(["feature-flags".into()]);
        let bin_to_crate = HashMap::from([
            ("feature-flags".into(), "feature-flags".into()),
            ("warm-flags-cache".into(), "feature-flags".into()),
            ("capture".into(), "capture".into()),
        ]);
        let images = vec![
            ImageConfig {
                image: "feature-flags".into(),
                bin: None,
            },
            ImageConfig {
                image: "flags-cache-warmer".into(),
                bin: Some("warm-flags-cache".into()),
            },
            ImageConfig {
                image: "capture".into(),
                bin: None,
            },
        ];

        let result = map_crates_to_images(&affected, &bin_to_crate, &images);
        assert_eq!(result, vec!["feature-flags", "flags-cache-warmer"]);
    }

    #[test]
    fn rules_parse_successfully() {
        DeterminatorRules::parse(RULES_TOML).expect("rules TOML should parse");
    }

    // ── Integration tests against real workspace ──────────────────
    //
    // Two kinds of integration tests:
    //
    // 1. Structural — assert pipeline invariants that hold regardless of
    //    which services exist (subset relationships, union property, etc.)
    //
    // 2. Concrete — assert against the actual rust-images.yml and workspace.
    //    These intentionally break when a service is added/renamed/removed
    //    so the author verifies the wiring is correct.

    fn load_test_fixtures() -> (PackageGraph, Vec<ImageConfig>) {
        let repo_root = find_repo_root().expect("must be in a git repo");
        let graph = build_package_graph(&repo_root.join("rust")).expect("cargo metadata");
        let images = parse_images_yaml(&repo_root.join(".github/rust-images.yml"))
            .expect("images YAML");
        (graph, images)
    }

    // ── Structural tests ─────────────────────────────────────────

    #[test]
    fn e2e_file_in_workspace_crate_affects_that_crate() {
        let (graph, images) = load_test_fixtures();
        let member = graph.workspace().iter().next().unwrap();
        let fake_path = format!("rust/{}/src/lib.rs", member.source().workspace_path().unwrap());
        let result =
            compute_affected(&[fake_path], None, &graph, &images).unwrap();
        assert!(!result.rebuild_all);
        assert!(
            result.crates.contains(&member.name().to_string()),
            "changing a file in {} should mark it affected",
            member.name()
        );
    }

    #[test]
    fn e2e_directly_changed_is_subset_of_crates() {
        let (graph, images) = load_test_fixtures();
        let member = graph.workspace().iter().next().unwrap();
        let fake_path = format!("rust/{}/src/lib.rs", member.source().workspace_path().unwrap());
        let result =
            compute_affected(&[fake_path], None, &graph, &images).unwrap();
        let crates: HashSet<&str> = result.crates.iter().map(|s| s.as_str()).collect();
        for dc in &result.directly_changed {
            assert!(
                crates.contains(dc.as_str()),
                "directly_changed entry {dc} must appear in crates"
            );
        }
    }

    #[test]
    fn e2e_rebuild_all_marks_every_workspace_crate() {
        let (graph, images) = load_test_fixtures();
        let result =
            compute_affected(&["rust/Cargo.lock".into()], None, &graph, &images).unwrap();
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
    fn e2e_file_outside_workspace_produces_no_crates() {
        let (graph, images) = load_test_fixtures();
        let result = compute_affected(
            &["README.md".into()],
            None,
            &graph,
            &images,
        )
        .unwrap();
        assert!(!result.rebuild_all);
        assert!(result.crates.is_empty());
        assert!(result.images.is_empty());
    }

    #[test]
    fn e2e_multi_file_is_union() {
        let (graph, images) = load_test_fixtures();
        let members: Vec<_> = graph.workspace().iter().collect();
        let (a, b) = (&members[0], &members[1]);
        let path_a = format!("rust/{}/src/lib.rs", a.source().workspace_path().unwrap());
        let path_b = format!("rust/{}/src/lib.rs", b.source().workspace_path().unwrap());

        let result_a = compute_affected(&[path_a.clone()], None, &graph, &images).unwrap();
        let result_b = compute_affected(&[path_b.clone()], None, &graph, &images).unwrap();
        let result_both =
            compute_affected(&[path_a, path_b], None, &graph, &images).unwrap();

        let union: HashSet<&str> = result_a
            .crates
            .iter()
            .chain(&result_b.crates)
            .map(|s| s.as_str())
            .collect();
        let combined: HashSet<&str> =
            result_both.crates.iter().map(|s| s.as_str()).collect();
        assert_eq!(union, combined, "multi-file result should be the union of individual results");
    }

    // ── Concrete tests ───────────────────────────────────────────
    //
    // Update these when adding/removing/renaming services.

    /// Every image in rust-images.yml must resolve to a binary target in
    /// the workspace (except sqlx-migrate which is a non-crate image).
    #[test]
    fn every_image_resolves_to_a_workspace_binary() {
        let (graph, images) = load_test_fixtures();
        let bin_to_crate = build_binary_to_crate_map(&graph);
        for img in &images {
            let bin_name = img.bin.as_deref().unwrap_or(&img.image);
            if NON_CRATE_IMAGE_TRIGGERS.iter().any(|&(name, _)| name == img.image) {
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
    fn e2e_leaf_service_only_affects_itself_and_dependents() {
        let (graph, images) = load_test_fixtures();
        let result = compute_affected(
            &["rust/capture/src/main.rs".into()],
            None,
            &graph,
            &images,
        )
        .unwrap();
        assert!(!result.rebuild_all);
        assert_eq!(result.directly_changed, vec!["capture"]);
        assert_eq!(result.images, vec!["capture", "capture-logs"]);
    }

    #[test]
    fn e2e_proto_change_maps_to_proto_crates() {
        let (graph, images) = load_test_fixtures();
        let result = compute_affected(
            &["proto/personhog.proto".into()],
            None,
            &graph,
            &images,
        )
        .unwrap();
        assert!(!result.rebuild_all);
        assert!(result.directly_changed.contains(&"personhog-proto".into()));
        assert!(result.directly_changed.contains(&"kafka-assigner-proto".into()));
        assert!(result.images.len() > 2, "proto change should propagate to multiple images");
    }

    #[test]
    fn e2e_migration_only_triggers_sqlx_migrate() {
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
    fn e2e_multi_binary_crate_produces_all_images() {
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
}
