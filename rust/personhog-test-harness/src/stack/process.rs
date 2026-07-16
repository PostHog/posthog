use std::path::{Path, PathBuf};
use std::process::{Command as StdCommand, Stdio};
use std::time::Duration;
use std::{env, fs};

use anyhow::{Context, Result};
use tokio::process::{Child, Command};

/// Everything needed to (re)spawn a service, retained so chaos events can
/// restart a process under the same identity.
struct ServiceSpec {
    name: String,
    binary: PathBuf,
    envs: Vec<(String, String)>,
    log_path: PathBuf,
}

impl ServiceSpec {
    fn spawn(&self) -> Result<Child> {
        // Append so a respawned service continues its predecessor's log.
        let log_file = fs::File::options()
            .create(true)
            .append(true)
            .open(&self.log_path)
            .with_context(|| format!("opening log file {}", self.log_path.display()))?;
        let stderr_file = log_file.try_clone().context("cloning log handle")?;

        let mut command = Command::new(&self.binary);
        command
            .env_clear()
            // PATH and HOME survive so the binaries can resolve tools and
            // dotfiles (librdkafka, DNS, etc.) the way they do in dev.
            .envs(env::vars().filter(|(k, _)| k == "PATH" || k == "HOME"))
            // No RUST_BACKTRACE and no colors: a service panic's message is
            // the signal, and fifty frames of runtime internals push it out
            // of the log tail that failure reports embed.
            .env("NO_COLOR", "1")
            .env("RUST_LOG", "info")
            .stdout(Stdio::from(log_file))
            .stderr(Stdio::from(stderr_file))
            .kill_on_drop(true);
        for (key, value) in &self.envs {
            command.env(key, value);
        }

        let child = command
            .spawn()
            .with_context(|| format!("spawning {} from {}", self.name, self.binary.display()))?;

        tracing::info!(
            service = %self.name,
            pid = child.id(),
            log = %self.log_path.display(),
            "spawned"
        );
        Ok(child)
    }
}

/// A spawned service child process with its log file and respawnable spec.
pub struct ServiceProcess {
    spec: ServiceSpec,
    child: Child,
}

impl ServiceProcess {
    pub fn spawn(
        name: &str,
        binary: &Path,
        envs: &[(&str, String)],
        log_dir: &Path,
    ) -> Result<Self> {
        let spec = ServiceSpec {
            name: name.to_string(),
            binary: binary.to_path_buf(),
            envs: envs
                .iter()
                .map(|(k, v)| (k.to_string(), v.clone()))
                .collect(),
            log_path: log_dir.join(format!("{name}.log")),
        };
        let child = spec.spawn()?;
        Ok(Self { spec, child })
    }

    pub fn name(&self) -> &str {
        &self.spec.name
    }

    pub fn log_path(&self) -> &Path {
        &self.spec.log_path
    }

    /// Whether the process has exited. Returns the exit description if so.
    pub fn exited(&mut self) -> Option<String> {
        match self.child.try_wait() {
            Ok(Some(status)) => Some(status.to_string()),
            Ok(None) => None,
            Err(e) => Some(format!("unknown ({e})")),
        }
    }

    /// Kill the current process (if still running) and start a fresh one
    /// from the same spec — a crash-restart under the same identity.
    pub async fn respawn(&mut self) -> Result<()> {
        self.kill_now().await;
        self.child = self.spec.spawn()?;
        Ok(())
    }

    fn signal(&self, signal: &str) {
        let Some(pid) = self.child.id() else {
            return;
        };
        // tokio's Child only exposes SIGKILL; other signals go through
        // kill(1) to avoid pulling in a signals dependency.
        if let Err(e) = StdCommand::new("kill")
            .args([signal, &pid.to_string()])
            .status()
        {
            tracing::warn!(service = %self.spec.name, signal, error = %e, "failed to signal");
        }
    }

    /// Send SIGTERM without waiting — the process drains and exits on its
    /// own schedule (used by chaos graceful shutdowns, where traffic keeps
    /// flowing while the leader hands its partitions off).
    pub fn sigterm(&self) {
        self.signal("-TERM");
    }

    /// SIGSTOP — freeze the process without killing it. To its peers it is
    /// unreachable but not gone: connections hang, heartbeats stop, and the
    /// process resumes exactly where it was on SIGCONT.
    pub fn sigstop(&self) {
        self.signal("-STOP");
    }

    /// SIGCONT — wake a stopped process.
    pub fn sigcont(&self) {
        self.signal("-CONT");
    }

    /// SIGKILL immediately — a crash, not a shutdown.
    pub async fn kill_now(&mut self) {
        if let Err(e) = self.child.kill().await {
            tracing::warn!(service = %self.spec.name, error = %e, "failed to kill");
        }
    }

    /// Ask the process to shut down gracefully (SIGTERM), then wait up to
    /// `grace` before killing it outright.
    pub async fn terminate(mut self, grace: Duration) -> Result<()> {
        // A stopped process cannot handle SIGTERM; wake it first so
        // teardown does not hang on a paused zombie.
        self.sigcont();
        self.sigterm();

        match tokio::time::timeout(grace, self.child.wait()).await {
            Ok(status) => {
                tracing::info!(service = %self.spec.name, status = ?status.ok(), "exited");
            }
            Err(_) => {
                tracing::warn!(service = %self.spec.name, "did not exit within grace period, killing");
                if let Err(e) = self.child.kill().await {
                    tracing::warn!(service = %self.spec.name, error = %e, "failed to kill");
                }
            }
        }
        Ok(())
    }

    /// Return the last `lines` lines of the service's log, for error reports.
    pub fn log_tail(&self, lines: usize) -> String {
        let Ok(content) = fs::read_to_string(&self.spec.log_path) else {
            return String::new();
        };
        let all: Vec<&str> = content.lines().collect();
        let start = all.len().saturating_sub(lines);
        strip_ansi(&all[start..].join("\n"))
    }
}

/// Strip ANSI escape sequences. Failure reports embed log tails inside the
/// harness's own log output, where raw escapes render as `\x1b[2m` soup;
/// spawned services get NO_COLOR but this guards logs written by anything
/// that ignores it.
fn strip_ansi(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    let mut chars = input.chars().peekable();
    while let Some(c) = chars.next() {
        if c != '\x1b' {
            out.push(c);
            continue;
        }
        // CSI sequences (ESC '[' ... final byte in @..~) are all tracing
        // emits; a bare ESC before anything else just gets dropped.
        if chars.peek() == Some(&'[') {
            chars.next();
            for c in chars.by_ref() {
                if ('\x40'..='\x7e').contains(&c) {
                    break;
                }
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::strip_ansi;

    #[test]
    fn strip_ansi_removes_csi_sequences_and_keeps_text() {
        let colored = "\x1b[2m2026-07-15\x1b[0m \x1b[32m INFO\x1b[0m plain \x1b[3mkey\x1b[0m\x1b[2m=\x1b[0mvalue";
        assert_eq!(strip_ansi(colored), "2026-07-15  INFO plain key=value");
        assert_eq!(strip_ansi("no escapes"), "no escapes");
    }
}
