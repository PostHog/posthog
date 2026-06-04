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
    fn create(base_ref: &str) -> Result<Self> {
        let path = tempfile::Builder::new()
            .prefix("affected-services-")
            .tempdir()
            .context("failed to create temp directory")?
            .keep();
        let path_s = path.to_string_lossy();

        // Disable sparse checkout before creating the worktree so it doesn't
        // inherit the parent's sparse-checkout filter (CI uses sparse checkout
        // for the main working tree).
        let _ = Command::new("git")
            .args(["config", "--local", "core.sparseCheckout", "false"])
            .output();

        let out = Command::new("git")
            .args(["worktree", "add", "--detach", path_s.as_ref(), base_ref])
            .output()
            .context("failed to create git worktree")?;

        // Re-enable sparse checkout for the parent worktree
        let _ = Command::new("git")
            .args(["config", "--local", "core.sparseCheckout", "true"])
            .output();

        anyhow::ensure!(
            out.status.success(),
            "git worktree add failed: {}",
            String::from_utf8_lossy(&out.stderr).trim()
        );

        eprintln!("debug[worktree]: created at {} for ref {base_ref}", path_s);
        if let Ok(log) = Command::new("git")
            .args(["-C", path_s.as_ref(), "log", "--oneline", "-1"])
            .output()
        {
            eprintln!(
                "debug[worktree]: HEAD = {}",
                String::from_utf8_lossy(&log.stdout).trim()
            );
        }

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
        if let Ok(ls) = Command::new("ls").arg(old_workspace.as_os_str()).output() {
            eprintln!(
                "debug[old_graph]: ls {}: {}",
                old_workspace.display(),
                String::from_utf8_lossy(&ls.stdout).trim()
            );
        }
        return None;
    }

    eprintln!(
        "debug[old_graph]: found {workspace_subdir}/Cargo.toml, running cargo metadata --locked"
    );

    let mut cmd = MetadataCommand::new();
    cmd.current_dir(&old_workspace);
    cmd.other_options(["--locked"]);
    match cmd.build_graph() {
        Ok(graph) => {
            eprintln!(
                "debug[old_graph]: success — {} workspace packages",
                graph.workspace().iter().count()
            );
            Some(graph)
        }
        Err(e) => {
            eprintln!("warning: could not build old package graph: {e}");
            None
        }
    }
}
