use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{Context, Result};
use guppy::graph::PackageGraph;
use guppy::MetadataCommand;

pub fn find_repo_root() -> Result<PathBuf> {
    let out = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .output()
        .context("failed to run git")?;
    Ok(PathBuf::from(
        String::from_utf8(out.stdout)?.trim().to_string(),
    ))
}

pub fn get_changed_files(base_ref: &str) -> Result<Vec<String>> {
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

pub fn build_package_graph(workspace_dir: &Path) -> Result<PackageGraph> {
    let mut cmd = MetadataCommand::new();
    cmd.current_dir(workspace_dir);
    cmd.build_graph()
        .context("failed to build package graph from cargo metadata")
}

struct TempWorktree {
    path: PathBuf,
}

impl TempWorktree {
    fn create(base_ref: &str, sparse_paths: &[&str]) -> Result<Self> {
        let path = tempfile::Builder::new()
            .prefix("affected-services-")
            .tempdir()
            .context("failed to create temp directory")?
            .keep();
        let path_s = path.to_string_lossy();

        let out = Command::new("git")
            .args([
                "worktree",
                "add",
                "--detach",
                "--no-checkout",
                path_s.as_ref(),
                base_ref,
            ])
            .output()
            .context("failed to create git worktree")?;
        anyhow::ensure!(
            out.status.success(),
            "git worktree add failed: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        );

        // Configure sparse checkout on the worktree so we only materialize
        // the paths needed for cargo metadata, not the entire repo.
        let mut sparse_args = vec!["sparse-checkout", "set", "--no-cone"];
        sparse_args.extend_from_slice(sparse_paths);
        let sparse_out = Command::new("git")
            .args(["-C", path_s.as_ref()])
            .args(&sparse_args)
            .output()
            .context("failed to configure sparse checkout on worktree")?;
        anyhow::ensure!(
            sparse_out.status.success(),
            "git sparse-checkout set failed: {}",
            String::from_utf8_lossy(&sparse_out.stderr).trim()
        );

        let checkout_out = Command::new("git")
            .args(["-C", path_s.as_ref(), "checkout"])
            .output()
            .context("failed to checkout worktree")?;
        anyhow::ensure!(
            checkout_out.status.success(),
            "git checkout in worktree failed: {}",
            String::from_utf8_lossy(&checkout_out.stderr).trim()
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

pub fn build_old_package_graph(base_ref: &str, workspace_subdir: &str) -> Option<PackageGraph> {
    let worktree = match TempWorktree::create(base_ref, &[workspace_subdir]) {
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
    cmd.other_options(["--locked"]);
    match cmd.build_graph() {
        Ok(graph) => Some(graph),
        Err(e) => {
            eprintln!("warning: could not build old package graph: {e}");
            None
        }
    }
}
