use anyhow::{Context, Result, ensure};
use std::{
    os::{
        fd::AsRawFd,
        unix::fs::{FileTypeExt, MetadataExt, PermissionsExt},
    },
    path::PathBuf,
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{UnixListener, UnixStream},
};

pub fn caller_closed(socket: &UnixStream) -> bool {
    // A stream can still have readable bytes after its caller goes away.
    // A zero-byte send checks the other direction without consuming those
    // bytes or treating a half-closed writer as an abandoned request.
    let sent = unsafe {
        libc::send(
            socket.as_raw_fd(),
            std::ptr::null(),
            0,
            libc::MSG_DONTWAIT | libc::MSG_NOSIGNAL,
        )
    };
    sent < 0
        && matches!(
            std::io::Error::last_os_error().raw_os_error(),
            Some(libc::EPIPE | libc::ECONNRESET | libc::ENOTCONN)
        )
}

/// Give overloaded callers a reply without admitting their requests.
#[derive(Default)]
pub struct BusyReplies(tokio::task::JoinSet<()>);

impl BusyReplies {
    pub fn reject(&mut self, mut stream: UnixStream, reply: &'static [u8]) {
        while self.0.try_join_next().is_some() {}
        if self.0.len() < 32 {
            self.0.spawn(async move {
                let sent = tokio::time::timeout(Duration::from_millis(100), async {
                    // Let the caller finish its first write before closing.
                    let mut prefix = [0; 4096];
                    let _prefix_len = stream.read(&mut prefix).await?;
                    stream.write_all(reply).await
                })
                .await;
                match sent {
                    Ok(Ok(())) => {}
                    Ok(Err(e)) => eprintln!("Could not send the busy reply: {e}"),
                    Err(_) => eprintln!("The busy reply timed out"),
                }
            });
        } else {
            use std::io::Write;
            if let Err(error) = stream
                .into_std()
                .and_then(|mut socket| socket.write_all(reply))
            {
                eprintln!("Could not send the busy reply: {error}");
            }
        }
    }
}

pub struct Socket {
    path: PathBuf,
    identity: (u64, u64),
    pub listener: UnixListener,
}

impl Socket {
    pub fn bind(path: PathBuf) -> Result<Self> {
        // Serialize stale socket recovery by competing hosts in the same workspace.
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(std::path::Path::new("."));
        let directory = std::fs::File::open(parent)?;
        if unsafe { libc::flock(directory.as_raw_fd(), libc::LOCK_EX) } != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        match path.symlink_metadata() {
            Ok(meta) => {
                ensure!(
                    meta.file_type().is_socket() && meta.uid() == unsafe { libc::geteuid() },
                    "Local socket must be owned by the current user"
                );
                match std::os::unix::net::UnixStream::connect(&path) {
                    Ok(_) => anyhow::bail!("Local socket is already in use"),
                    Err(error) if error.kind() == std::io::ErrorKind::ConnectionRefused => {}
                    Err(error) => return Err(error.into()),
                }
                std::fs::remove_file(&path)?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        let listener = UnixListener::bind(&path).context("Could not bind the local socket")?;
        let meta = path.symlink_metadata()?;
        let socket = Self {
            path,
            identity: (meta.dev(), meta.ino()),
            listener,
        };
        std::fs::set_permissions(&socket.path, std::fs::Permissions::from_mode(0o600))?;
        Ok(socket)
    }
}

impl Drop for Socket {
    fn drop(&mut self) {
        if self.path.symlink_metadata().is_ok_and(|meta| {
            meta.file_type().is_socket() && self.identity == (meta.dev(), meta.ino())
        }) && let Err(error) = std::fs::remove_file(&self.path)
            && error.kind() != std::io::ErrorKind::NotFound
        {
            eprintln!("Could not remove the local socket: {error}");
        }
    }
}
