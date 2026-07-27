use std::collections::{HashMap, HashSet};
use std::path::Path;

use anyhow::{Context, Result};
use guppy::graph::PackageGraph;

pub const NON_CRATE_IMAGE_TRIGGERS: &[(&str, &[&str])] = &[(
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
pub struct ImageConfig {
    pub image: String,
    pub bin: Option<String>,
}

pub fn parse_images_yaml(path: &Path) -> Result<Vec<ImageConfig>> {
    let content = std::fs::read_to_string(path)
        .with_context(|| format!("failed to read {}", path.display()))?;
    parse_images_yaml_content(&content)
}

pub fn parse_images_yaml_content(content: &str) -> Result<Vec<ImageConfig>> {
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

pub fn build_binary_to_crate_map(graph: &PackageGraph) -> HashMap<String, String> {
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

pub fn map_crates_to_images(
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

pub fn non_crate_images_affected(files: &[String]) -> Vec<String> {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn simple_entry() {
        let yaml = "- image: capture\n  dockerfile: ./rust/Dockerfile\n";
        let items = parse_images_yaml_content(yaml).unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].image, "capture");
        assert!(items[0].bin.is_none());
    }

    #[test]
    fn with_bin_override() {
        let yaml = "- image: flags-cache-warmer\n  bin: warm-flags-cache\n";
        let items = parse_images_yaml_content(yaml).unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].image, "flags-cache-warmer");
        assert_eq!(items[0].bin.as_deref(), Some("warm-flags-cache"));
    }

    #[test]
    fn multiple_entries() {
        let yaml = "\
- image: capture
  dockerfile: ./rust/Dockerfile

- image: cymbal
  dockerfile: ./rust/Dockerfile

- image: flags-cache-warmer
  bin: warm-flags-cache
  dockerfile: ./rust/Dockerfile
";
        let items = parse_images_yaml_content(yaml).unwrap();
        assert_eq!(items.len(), 3);
        assert_eq!(items[0].image, "capture");
        assert_eq!(items[1].image, "cymbal");
        assert_eq!(items[2].image, "flags-cache-warmer");
        assert_eq!(items[2].bin.as_deref(), Some("warm-flags-cache"));
    }

    #[test]
    fn skips_comments_and_blank_lines() {
        let yaml = "\
# This is a comment
- image: capture

  # inline comment
  dockerfile: ./rust/Dockerfile

";
        let items = parse_images_yaml_content(yaml).unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].image, "capture");
    }

    #[test]
    fn ignores_unknown_fields() {
        let yaml = "- image: capture\n  dockerfile: ./rust/Dockerfile\n  project: abc123\n  features: some-feature\n  target: runtime-jumphost\n";
        let items = parse_images_yaml_content(yaml).unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].image, "capture");
        assert!(items[0].bin.is_none());
    }

    #[test]
    fn empty_input() {
        let items = parse_images_yaml_content("").unwrap();
        assert!(items.is_empty());
    }

    #[test]
    fn comments_only() {
        let items = parse_images_yaml_content("# just a comment\n# another one\n").unwrap();
        assert!(items.is_empty());
    }

    #[test]
    fn inline_image_on_dash_line() {
        let yaml = "- image: capture\n";
        let items = parse_images_yaml_content(yaml).unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].image, "capture");
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
}
