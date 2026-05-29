use std::collections::{HashMap, HashSet, VecDeque};
use std::io::BufRead;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{Context, Result};
use cargo_metadata::{DependencyKind, Metadata, MetadataCommand};
use clap::{Parser, ValueEnum};
use serde::Serialize;

const REBUILD_ALL_FILES: &[&str] = &[
    "rust/Cargo.toml",
    "rust/Cargo.lock",
    "rust/Dockerfile",
    "rust/Dockerfile.sqlx-migrate",
    ".github/rust-images.yml",
];

const REBUILD_ALL_PREFIXES: &[&str] = &["rust/.cargo/", "rust/.sqlx/"];

const EXTERNAL_CRATE_TRIGGERS: &[(&str, &[&str])] =
    &[("proto/", &["personhog-proto", "kafka-assigner-proto"])];

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

fn get_cargo_metadata(workspace_dir: &Path) -> Result<Metadata> {
    MetadataCommand::new()
        .current_dir(workspace_dir)
        .exec()
        .context("failed to run cargo metadata")
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

// ── Graph construction ─────────────────────────────────────────────

fn build_directory_to_crate_map(metadata: &Metadata, repo_root: &Path) -> HashMap<String, String> {
    let members: HashSet<_> = metadata.workspace_members.iter().collect();
    let repo_root_str = repo_root.to_string_lossy();

    let mut map = HashMap::new();
    for pkg in &metadata.packages {
        if !members.contains(&pkg.id) {
            continue;
        }
        let crate_dir = pkg.manifest_path.parent().unwrap();
        let crate_dir_str = crate_dir.as_str();
        if let Some(rel) = crate_dir_str.strip_prefix(repo_root_str.as_ref()) {
            let rel = rel.trim_start_matches('/');
            map.insert(rel.to_string(), pkg.name.clone());
        }
    }
    map
}

fn build_reverse_dep_graph(metadata: &Metadata) -> HashMap<String, HashSet<String>> {
    let members: HashSet<_> = metadata.workspace_members.iter().collect();
    let id_to_name: HashMap<_, _> = metadata
        .packages
        .iter()
        .filter(|p| members.contains(&p.id))
        .map(|p| (&p.id, p.name.as_str()))
        .collect();

    let mut reverse: HashMap<String, HashSet<String>> = id_to_name
        .values()
        .map(|name| (name.to_string(), HashSet::new()))
        .collect();

    if let Some(resolve) = &metadata.resolve {
        for node in &resolve.nodes {
            let Some(depender) = id_to_name.get(&node.id) else {
                continue;
            };
            for dep in &node.deps {
                let Some(dep_name) = id_to_name.get(&dep.pkg) else {
                    continue;
                };
                let is_dev_only = !dep.dep_kinds.is_empty()
                    && dep
                        .dep_kinds
                        .iter()
                        .all(|dk| dk.kind == DependencyKind::Development);
                if !is_dev_only {
                    if let Some(set) = reverse.get_mut(*dep_name) {
                        set.insert(depender.to_string());
                    }
                }
            }
        }
    }
    reverse
}

fn build_binary_to_crate_map(metadata: &Metadata) -> HashMap<String, String> {
    let members: HashSet<_> = metadata.workspace_members.iter().collect();
    let mut map = HashMap::new();
    for pkg in &metadata.packages {
        if !members.contains(&pkg.id) {
            continue;
        }
        for target in &pkg.targets {
            if target.is_bin() {
                map.insert(target.name.clone(), pkg.name.clone());
            }
        }
    }
    map
}

// ── Core logic ─────────────────────────────────────────────────────

fn classify_changed_files(
    files: &[String],
    dir_to_crate: &HashMap<String, String>,
) -> (HashSet<String>, bool) {
    if files.is_empty() {
        return (HashSet::new(), false);
    }

    let mut changed = HashSet::new();

    for f in files {
        if REBUILD_ALL_FILES.iter().any(|&r| r == f) {
            return (HashSet::new(), true);
        }
        if REBUILD_ALL_PREFIXES.iter().any(|p| f.starts_with(p)) {
            return (HashSet::new(), true);
        }
        for &(prefix, crates) in EXTERNAL_CRATE_TRIGGERS {
            if f.starts_with(prefix) {
                changed.extend(crates.iter().map(|s| s.to_string()));
            }
        }
        let mut best_len = 0;
        let mut best_crate = None;
        for (dir, crate_name) in dir_to_crate {
            let prefix = format!("{dir}/");
            if f.starts_with(&prefix) && dir.len() > best_len {
                best_len = dir.len();
                best_crate = Some(crate_name.clone());
            }
        }
        if let Some(c) = best_crate {
            changed.insert(c);
        }
    }
    (changed, false)
}

fn walk_reverse_deps(
    seeds: &HashSet<String>,
    reverse: &HashMap<String, HashSet<String>>,
) -> HashSet<String> {
    let mut visited = seeds.clone();
    let mut queue: VecDeque<String> = seeds.iter().cloned().collect();

    while let Some(crate_name) = queue.pop_front() {
        if let Some(dependents) = reverse.get(&crate_name) {
            for dep in dependents {
                if visited.insert(dep.clone()) {
                    queue.push_back(dep.clone());
                }
            }
        }
    }
    visited
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

fn compute_affected(
    changed_files: &[String],
    metadata: &Metadata,
    images: &[ImageConfig],
    repo_root: &Path,
) -> AffectedResult {
    let dir_to_crate = build_directory_to_crate_map(metadata, repo_root);
    let reverse_graph = build_reverse_dep_graph(metadata);
    let bin_to_crate = build_binary_to_crate_map(metadata);

    let (directly_changed, rebuild_all) = classify_changed_files(changed_files, &dir_to_crate);

    if rebuild_all {
        let mut all_images: Vec<String> = images.iter().map(|i| i.image.clone()).collect();
        all_images.sort();
        let mut all_crates: Vec<String> = reverse_graph.keys().cloned().collect();
        all_crates.sort();
        return AffectedResult {
            rebuild_all: true,
            images: all_images,
            crates: all_crates,
            directly_changed: Vec::new(),
        };
    }

    let all_affected = walk_reverse_deps(&directly_changed, &reverse_graph);
    let mut affected_images = map_crates_to_images(&all_affected, &bin_to_crate, images);

    for img in non_crate_images_affected(changed_files) {
        if !affected_images.contains(&img) {
            affected_images.push(img);
        }
    }
    affected_images.sort();

    let mut crates: Vec<String> = all_affected.into_iter().collect();
    crates.sort();
    let mut directly: Vec<String> = directly_changed.into_iter().collect();
    directly.sort();

    AffectedResult {
        rebuild_all: false,
        images: affected_images,
        crates,
        directly_changed: directly,
    }
}

// ── Dump mode ──────────────────────────────────────────────────────

fn dump_graph(metadata: &Metadata, images: &[ImageConfig], repo_root: &Path) {
    let reverse = build_reverse_dep_graph(metadata);
    let bin_to_crate = build_binary_to_crate_map(metadata);

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

    let mut crate_names: Vec<&String> = reverse.keys().collect();
    crate_names.sort();

    for crate_name in &crate_names {
        let dependents = reverse.get(*crate_name).unwrap();
        let mut tags = Vec::new();
        if let Some(bins) = crate_to_bins.get(crate_name.as_str()) {
            let mut bins = bins.clone();
            bins.sort();
            tags.push(format!("bins: {}", bins.join(", ")));
        }
        if deployable_crates.contains(crate_name.as_str()) {
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
            let mut deps: Vec<&String> = dependents.iter().collect();
            deps.sort();
            deps.iter()
                .map(|s| s.as_str())
                .collect::<Vec<_>>()
                .join(", ")
        };

        println!("  {crate_name}{tag_str}");
        println!("    depended on by: {dep_str}");
    }

    println!();
    println!("TRANSITIVE IMPACT (crates affecting >2 others)");
    println!("{}", "=".repeat(70));

    let mut impacts: Vec<(&str, usize, Vec<String>)> = Vec::new();
    for crate_name in &crate_names {
        let seeds = HashSet::from([crate_name.to_string()]);
        let affected = walk_reverse_deps(&seeds, &reverse);
        let affected_images = map_crates_to_images(&affected, &bin_to_crate, images);
        let dep_count = affected.len() - 1;
        if dep_count > 2 {
            impacts.push((crate_name.as_str(), dep_count, affected_images));
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

    let dir_to_crate = build_directory_to_crate_map(metadata, repo_root);
    let _ = dir_to_crate; // used only in other modes

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

// ── Main ───────────────────────────────────────────────────────────

fn main() -> Result<()> {
    let cli = Cli::parse();

    let repo_root = find_repo_root()?;
    let workspace_dir = cli.workspace_dir.unwrap_or_else(|| repo_root.join("rust"));
    let images_file = cli
        .images_file
        .unwrap_or_else(|| repo_root.join(".github/rust-images.yml"));

    let metadata = get_cargo_metadata(&workspace_dir)?;
    let images = parse_images_yaml(&images_file)?;

    if cli.dump_graph {
        dump_graph(&metadata, &images, &repo_root);
        return Ok(());
    }

    let changed_files = if let Some(files) = cli.files {
        files
    } else if cli.stdin {
        std::io::stdin()
            .lock()
            .lines()
            .map_while(Result::ok)
            .filter(|l| !l.is_empty())
            .collect()
    } else if let Some(base_ref) = &cli.base_ref {
        get_changed_files(base_ref)?
    } else {
        anyhow::bail!("one of --base-ref, --files, --stdin, or --dump-graph is required");
    };

    let result = compute_affected(&changed_files, &metadata, &images, &repo_root);

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

    fn dir_map() -> HashMap<String, String> {
        HashMap::from([
            ("rust/capture".into(), "capture".into()),
            ("rust/capture-logs".into(), "capture-logs".into()),
            ("rust/common/kafka".into(), "common-kafka".into()),
            ("rust/feature-flags".into(), "feature-flags".into()),
        ])
    }

    #[test]
    fn rebuild_all_on_cargo_lock() {
        let (_, rebuild) = classify_changed_files(&["rust/Cargo.lock".into()], &dir_map());
        assert!(rebuild);
    }

    #[test]
    fn rebuild_all_on_cargo_config() {
        let (_, rebuild) = classify_changed_files(&["rust/.cargo/config.toml".into()], &dir_map());
        assert!(rebuild);
    }

    #[test]
    fn maps_file_to_owning_crate() {
        let (changed, rebuild) =
            classify_changed_files(&["rust/capture/src/main.rs".into()], &dir_map());
        assert!(!rebuild);
        assert_eq!(changed, HashSet::from(["capture".into()]));
    }

    #[test]
    fn longest_prefix_wins() {
        let mut map = dir_map();
        map.insert("rust/common".into(), "common-parent".into());
        let (changed, _) = classify_changed_files(&["rust/common/kafka/src/lib.rs".into()], &map);
        assert_eq!(changed, HashSet::from(["common-kafka".into()]));
    }

    #[test]
    fn external_trigger_maps_proto_to_crates() {
        let (changed, rebuild) =
            classify_changed_files(&["proto/personhog.proto".into()], &dir_map());
        assert!(!rebuild);
        assert!(changed.contains("personhog-proto"));
        assert!(changed.contains("kafka-assigner-proto"));
    }

    #[test]
    fn transitive_walk() {
        let reverse = HashMap::from([
            (
                "common-kafka".into(),
                HashSet::from(["capture".into(), "cymbal".into()]),
            ),
            ("capture".into(), HashSet::from(["capture-logs".into()])),
            ("cymbal".into(), HashSet::new()),
            ("capture-logs".into(), HashSet::new()),
        ]);

        let affected = walk_reverse_deps(&HashSet::from(["common-kafka".into()]), &reverse);

        assert_eq!(
            affected,
            HashSet::from([
                "common-kafka".into(),
                "capture".into(),
                "capture-logs".into(),
                "cymbal".into(),
            ])
        );
    }

    #[test]
    fn walk_handles_cycles() {
        let reverse = HashMap::from([
            ("a".into(), HashSet::from(["b".into()])),
            ("b".into(), HashSet::from(["a".into()])),
        ]);
        let affected = walk_reverse_deps(&HashSet::from(["a".into()]), &reverse);
        assert_eq!(affected, HashSet::from(["a".into(), "b".into()]));
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
    fn empty_files_returns_nothing() {
        let (changed, rebuild) = classify_changed_files(&[], &dir_map());
        assert!(!rebuild);
        assert!(changed.is_empty());
    }
}
