//! Collector registry.
//!
//! Tier A (YAML) collectors compiled into the binary from `collectors/` at build time,
//! optionally overlaid at runtime by `--collectors-dir` (same `name` replaces, a new
//! name adds, `enabled: false` in an overlay file removes). Tier B (code) collectors
//! are registered below.

pub mod aurora_plans;
pub mod declarative;
pub mod logs;
pub mod query_stats;
pub mod statements;

use crate::collector::Collector;
use anyhow::{Context, Result};
use include_dir::{include_dir, Dir};
use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;

static EMBEDDED: Dir<'_> = include_dir!("$CARGO_MANIFEST_DIR/collectors");

pub struct Registry {
    collectors: Vec<Arc<dyn Collector>>,
}

impl Registry {
    pub fn load(overlay: Option<&Path>) -> Result<Self> {
        let mut by_name: BTreeMap<String, Arc<dyn Collector>> = BTreeMap::new();

        for f in EMBEDDED.files().filter(|f| is_yaml(f.path())) {
            let raw = f.contents_utf8().context("embedded collector not utf8")?;
            let c = declarative::SqlCollector::from_str(
                raw,
                &format!("embedded {}", f.path().display()),
            )?;
            by_name.insert(c.name().to_string(), Arc::new(c));
        }

        if let Some(dir) = overlay.filter(|d| d.exists()) {
            let mut paths: Vec<_> = std::fs::read_dir(dir)
                .with_context(|| format!("reading {}", dir.display()))?
                .filter_map(|e| e.ok())
                .map(|e| e.path())
                .filter(|p| is_yaml(p))
                .collect();
            paths.sort();
            for path in paths {
                let raw = std::fs::read_to_string(&path)?;
                let disabled: serde_yaml::Value = serde_yaml::from_str(&raw)?;
                let name = disabled
                    .get("name")
                    .and_then(|v| v.as_str())
                    .map(str::to_string);
                if disabled.get("enabled").and_then(|v| v.as_bool()) == Some(false) {
                    if let Some(n) = name {
                        tracing::info!(collector = n, "disabled by overlay");
                        by_name.remove(&n);
                    }
                    continue;
                }
                let c = declarative::SqlCollector::from_file(&path)?;
                tracing::info!(collector = c.name(), path = %path.display(), "overlay collector");
                by_name.insert(c.name().to_string(), Arc::new(c));
            }
        }

        // Tier B — code collectors.
        by_name.insert("query_stats".into(), Arc::new(query_stats::QueryStats));
        by_name.insert("aurora_plans".into(), Arc::new(aurora_plans::AuroraPlans));
        by_name.insert("logs".into(), Arc::new(logs::Logs::new()));

        Ok(Self {
            collectors: by_name.into_values().collect(),
        })
    }

    pub fn iter(&self) -> impl Iterator<Item = &Arc<dyn Collector>> {
        self.collectors.iter()
    }
    pub fn len(&self) -> usize {
        self.collectors.len()
    }
}

fn is_yaml(p: &Path) -> bool {
    p.extension()
        .map(|x| x == "yaml" || x == "yml")
        .unwrap_or(false)
}
