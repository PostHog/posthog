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
    // Compute the actual merge base so we don't pick up unrelated master
    // commits when the PR base SHA is behind the branch's rebase point.
    let merge_base_out = Command::new("git")
        .args(["merge-base", base_ref, "HEAD"])
        .output()
        .context("failed to run git merge-base")?;
    let diff_base = if merge_base_out.status.success() {
        String::from_utf8(merge_base_out.stdout)?.trim().to_string()
    } else {
        base_ref.to_string()
    };

    let out = Command::new("git")
        .args(["diff", "--name-only", &format!("{diff_base}...HEAD")])
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

        // Read the current sparse checkout setting so we can restore it after
        // creating the worktree. Without this, CI's sparse checkout config
        // would be inherited by the worktree and produce an incomplete checkout.
        let prev_sparse = Command::new("git")
            .args(["config", "--local", "core.sparseCheckout"])
            .output()
            .ok()
            .filter(|o| o.status.success())
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string());

        if prev_sparse.as_deref() == Some("true") {
            let _ = Command::new("git")
                .args(["config", "--local", "core.sparseCheckout", "false"])
                .output();
        }

        let out = Command::new("git")
            .args(["worktree", "add", "--detach", path_s.as_ref(), base_ref])
            .output()
            .context("failed to create git worktree")?;

        // Restore the original sparse checkout setting
        match prev_sparse.as_deref() {
            Some(val) => {
                let _ = Command::new("git")
                    .args(["config", "--local", "core.sparseCheckout", val])
                    .output();
            }
            None => {
                let _ = Command::new("git")
                    .args(["config", "--local", "--unset", "core.sparseCheckout"])
                    .output();
            }
        }

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
