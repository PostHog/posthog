//! Client for a local workspace service.
use anyhow::{Context, Result, bail};
use meep_protocol::Rpc;
use serde_json::{Value, json};
use std::{io::Read, path::Path, time::Duration};
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    net::UnixStream,
};

pub const HOST_TOKEN: &str = "host-auth.token";
pub fn host_token(dir: &Path) -> Result<String> {
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(dir.join(HOST_TOKEN))
        .context("Host authentication is unavailable; restart the local service")?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.mode() & 0o077 != 0 || meta.uid() != unsafe { libc::geteuid() } {
        bail!("Unsafe host authentication file");
    }
    let mut token = String::new();
    Read::by_ref(&mut file)
        .take(65)
        .read_to_string(&mut token)?;
    if token.len() != 64 || !token.bytes().all(|b| b.is_ascii_hexdigit()) {
        bail!("Invalid host authentication");
    }
    Ok(token)
}

/// Send one request to the workspace socket. The caller selects the response timeout.
pub async fn request(dir: &Path, mut rpc: Rpc, timeout: Duration) -> Result<Value> {
    if rpc.session_token.is_none() {
        rpc.params
            .as_object_mut()
            .context("Expected object parameters")?
            .insert("_host_auth".to_owned(), json!(host_token(dir)?));
    }
    let mut frame = serde_json::to_vec(&rpc)?;
    frame.push(b'\n');
    anyhow::ensure!(
        frame.len() <= crate::broker::MAX_RPC_BYTES,
        "Local request is too large"
    );
    tokio::time::timeout(timeout, async {
        let mut socket = UnixStream::connect(dir.join("broker.sock")).await?;
        socket.write_all(&frame).await?;
        const MAX_REPLY_BYTES: usize = 64 * 1024 * 1024;
        let mut line = Vec::new();
        BufReader::new(socket.take((MAX_REPLY_BYTES + 1) as u64))
            .read_until(b'\n', &mut line)
            .await?;
        anyhow::ensure!(
            line.len() <= MAX_REPLY_BYTES && line.last() == Some(&b'\n'),
            "Invalid local reply frame"
        );
        let response: Value = serde_json::from_slice(&line)?;
        if let Some(error) = response.get("error") {
            bail!("{}", error.as_str().unwrap_or("Local request failed"));
        }
        response
            .get("result")
            .cloned()
            .context("Missing local result")
    })
    .await?
}
