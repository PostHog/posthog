use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use anyhow::{Context, Result};
use tokio::process::{Child, Command};

/// A spawned service child process with its log file.
pub struct ServiceProcess {
    pub name: String,
    child: Child,
    pub log_path: PathBuf,
}

impl ServiceProcess {
    pub fn spawn(
        name: &str,
        binary: &Path,
        envs: &[(&str, String)],
        log_dir: &Path,
    ) -> Result<Self> {
        let log_path = log_dir.join(format!("{name}.log"));
        let log_file = std::fs::File::create(&log_path)
            .with_context(|| format!("creating log file {}", log_path.display()))?;
        let stderr_file = log_file.try_clone().context("cloning log handle")?;

        let mut command = Command::new(binary);
        command
            .env_clear()
            // PATH and HOME survive so the binaries can resolve tools and
            // dotfiles (librdkafka, DNS, etc.) the way they do in dev.
            .envs(std::env::vars().filter(|(k, _)| k == "PATH" || k == "HOME"))
            .env("RUST_BACKTRACE", "1")
            .env("RUST_LOG", "info")
            .stdout(Stdio::from(log_file))
            .stderr(Stdio::from(stderr_file))
            .kill_on_drop(true);
        for (key, value) in envs {
            command.env(key, value);
        }

        let child = command
            .spawn()
            .with_context(|| format!("spawning {name} from {}", binary.display()))?;

        tracing::info!(
            service = name,
            pid = child.id(),
            log = %log_path.display(),
            "spawned"
        );

        Ok(Self {
            name: name.to_string(),
            child,
            log_path,
        })
    }

    /// Whether the process has exited. Returns the exit description if so.
    pub fn exited(&mut self) -> Option<String> {
        match self.child.try_wait() {
            Ok(Some(status)) => Some(status.to_string()),
            Ok(None) => None,
            Err(e) => Some(format!("unknown ({e})")),
        }
    }

    /// Ask the process to shut down gracefully (SIGTERM), then wait up to
    /// `grace` before killing it outright.
    pub async fn terminate(mut self, grace: Duration) -> Result<()> {
        if let Some(pid) = self.child.id() {
            // tokio's Child only exposes SIGKILL; SIGTERM goes through kill(1)
            // to avoid pulling in a signals dependency for one call.
            if let Err(e) = std::process::Command::new("kill")
                .args(["-TERM", &pid.to_string()])
                .status()
            {
                tracing::warn!(service = %self.name, error = %e, "failed to send SIGTERM");
            }
        }

        match tokio::time::timeout(grace, self.child.wait()).await {
            Ok(status) => {
                tracing::info!(service = %self.name, status = ?status.ok(), "exited");
            }
            Err(_) => {
                tracing::warn!(service = %self.name, "did not exit within grace period, killing");
                if let Err(e) = self.child.kill().await {
                    tracing::warn!(service = %self.name, error = %e, "failed to kill");
                }
            }
        }
        Ok(())
    }

    /// Return the last `lines` lines of the service's log, for error reports.
    pub fn log_tail(&self, lines: usize) -> String {
        let Ok(content) = std::fs::read_to_string(&self.log_path) else {
            return String::new();
        };
        let all: Vec<&str> = content.lines().collect();
        let start = all.len().saturating_sub(lines);
        all[start..].join("\n")
    }
}
