use std::collections::{HashMap, HashSet};

use determinator::rules::DeterminatorRules;
use determinator::Determinator;
use guppy::graph::{DependencyDirection, PackageGraph};

use crate::images::{build_binary_to_crate_map, map_crates_to_images, ImageConfig};
use crate::RULES_TOML;

pub fn dump_graph(graph: &PackageGraph, images: &[ImageConfig]) {
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
