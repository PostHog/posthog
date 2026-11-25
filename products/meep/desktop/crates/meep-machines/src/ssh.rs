//! OpenSSH connection-only transport for Unix hosts with a configured SSH identity.
use super::{Connector, Session};
use anyhow::{Context, Result, bail, ensure};
use async_trait::async_trait;
use std::os::unix::fs::PermissionsExt;
use std::{
    path::{Path, PathBuf},
    process::Stdio,
    time::Duration,
};
use tempfile::TempDir;
use tokio::{
    io::{AsyncRead, AsyncReadExt},
    process::{Child, Command},
    task::JoinHandle,
};

/// Accept an OpenSSH host alias, user@host or ssh://[user@]host[:port].
pub fn validate_target(target: &str) -> Result<()> {
    let invalid =
        || anyhow::anyhow!("Expected an SSH host alias, user@host, or ssh://[user@]host[:port]");
    ensure!(
        !target.is_empty() && target.len() <= 512 && !target.starts_with('-'),
        "{}",
        invalid()
    );
    let uri = target.strip_prefix("ssh://");
    let address = uri.unwrap_or(target);
    let host_port = match address.split_once('@') {
        Some((user, host)) => {
            ensure!(
                !user.is_empty()
                    && user
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || b"_.+-".contains(&c)),
                "{}",
                invalid()
            );
            host
        }
        None => address,
    };
    let valid_port = |s: &str| {
        s.bytes().all(|b| b.is_ascii_digit()) && s.parse::<u16>().is_ok_and(|port| port > 0)
    };
    if let Some(bracketed) = host_port.strip_prefix('[') {
        let (address, port) = bracketed.split_once(']').ok_or_else(invalid)?;
        ensure!(
            address.parse::<std::net::Ipv6Addr>().is_ok()
                && (port.is_empty()
                    || (uri.is_some() && port.strip_prefix(':').is_some_and(valid_port))),
            "{}",
            invalid()
        );
        return Ok(());
    }
    if uri.is_none() && host_port.parse::<std::net::Ipv6Addr>().is_ok() {
        return Ok(());
    }
    let host = match host_port.split_once(':') {
        Some((host, port)) if uri.is_some() && valid_port(port) => host,
        Some(_) => return Err(invalid()),
        None => host_port,
    };
    ensure!(
        !host.is_empty()
            && !host.starts_with('-')
            && host
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"_.-".contains(&c)),
        "{}",
        invalid()
    );
    Ok(())
}

pub struct OpenSsh {
    target: String,
    config: Option<PathBuf>,
}

impl OpenSsh {
    pub fn new(target: impl Into<String>) -> Result<Self> {
        let target = target.into();
        validate_target(&target)?;
        Ok(Self {
            target,
            config: None,
        })
    }

    /// Use a host-provided, trusted OpenSSH config for aliases, routing and credentials.
    pub fn with_config(mut self, config: impl Into<PathBuf>) -> Self {
        self.config = Some(config.into());
        self
    }

    fn command(&self, socket: &Path) -> Command {
        let mut ssh = Command::new("/usr/bin/ssh");
        if let Some(config) = &self.config {
            ssh.arg("-F").arg(config);
        }
        ssh.arg("-S")
            .arg(socket)
            .args([
                "-oBatchMode=yes",
                "-oStrictHostKeyChecking=yes",
                "-oUpdateHostKeys=no",
                "-oClearAllForwardings=yes",
                "-oForwardAgent=no",
                "-oTunnel=no",
                "-oForwardX11=no",
                "-oPermitLocalCommand=no",
                "-oControlPersist=no",
                "-oForkAfterAuthentication=no",
                "-oConnectTimeout=10",
                "-oServerAliveInterval=15",
                "-oServerAliveCountMax=3",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .kill_on_drop(true);
        ssh
    }
}

struct Master {
    child: Child,
    diagnostics: JoinHandle<std::io::Result<String>>,
    _dir: TempDir,
}

async fn stderr_tail(mut stderr: impl AsyncRead + Unpin) -> std::io::Result<String> {
    let mut buffer = [0; 2048];
    let mut tail = Vec::new();
    loop {
        let n = stderr.read(&mut buffer).await?;
        if n == 0 {
            return Ok(String::from_utf8_lossy(&tail).trim().to_owned());
        }
        tail.extend_from_slice(&buffer[..n]);
        tail.drain(..tail.len().saturating_sub(2048));
    }
}

#[async_trait]
impl Connector for OpenSsh {
    async fn connect(&self) -> Result<Box<dyn Session>> {
        // Short enough for a Unix socket on macOS even with a long application data path.
        let dir = tempfile::Builder::new()
            .prefix("meep-ssh-")
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir_in("/tmp")?;
        let socket = dir.path().join("control");
        let mut child = self
            .command(&socket)
            .args(["-M", "-N", "-T", "--", &self.target])
            .stderr(Stdio::piped())
            .spawn()
            .context("Starting OpenSSH")?;
        let stderr = child
            .stderr
            .take()
            .context("Missing OpenSSH error stream")?;
        let mut master = Master {
            child,
            diagnostics: tokio::spawn(stderr_tail(stderr)),
            _dir: dir,
        };
        let ready = async {
            loop {
                if socket.exists()
                    && self
                        .command(&socket)
                        .args(["-O", "check", "--", &self.target])
                        .status()
                        .await?
                        .success()
                {
                    return anyhow::Ok(());
                }
                tokio::time::sleep(Duration::from_millis(75)).await;
            }
        };
        tokio::select! {
            biased;
            ended = master.closed() => { ended?; bail!("OpenSSH exited during authentication"); }
            result = tokio::time::timeout(Duration::from_secs(30), ready) => { result.context("Timed out waiting for an authenticated SSH connection")??; }
        }
        Ok(Box::new(master))
    }
}

#[async_trait]
impl Session for Master {
    async fn closed(&mut self) -> Result<()> {
        let status = self.child.wait().await?;
        if !status.success() {
            // A proxy from the host's config may outlive ssh and retain stderr.
            let message =
                match tokio::time::timeout(Duration::from_secs(1), &mut self.diagnostics).await {
                    Ok(result) => result??,
                    Err(_) => "Error stream remained open".into(),
                };
            bail!("OpenSSH exited with {status}: {message}");
        }
        Ok(())
    }

    async fn disconnect(mut self: Box<Self>) -> Result<()> {
        self.child.kill().await?;
        Ok(())
    }
}

impl Drop for Master {
    fn drop(&mut self) {
        self.diagnostics.abort();
    }
}
