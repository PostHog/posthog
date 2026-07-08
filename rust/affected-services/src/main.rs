use std::io::BufRead;
use std::path::Path;

use anyhow::Result;
use clap::{Parser, ValueEnum};

use affected_services::affected::compute_affected;
use affected_services::dump::dump_graph;
use affected_services::graph::{
    build_old_package_graph, build_package_graph, find_repo_root, get_changed_files,
};
use affected_services::images::parse_images_yaml;

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
    workspace_dir: Option<std::path::PathBuf>,

    #[arg(long)]
    images_file: Option<std::path::PathBuf>,

    #[arg(long, value_enum, default_value = "json")]
    output: OutputFormat,
}

#[derive(Clone, ValueEnum)]
enum OutputFormat {
    Json,
    Images,
    Crates,
}

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
