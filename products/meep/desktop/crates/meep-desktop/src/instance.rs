//! One native window per workspace, including Finder and direct CLI launches.
use anyhow::Result;
use std::{fs::File, os::fd::AsRawFd, path::Path};

pub struct UiLease(File);
impl Drop for UiLease {
    fn drop(&mut self) {
        // Release explicitly: a concurrent subprocess can briefly inherit a
        // descriptor between fork and exec, even with close-on-exec set.
        unsafe {
            libc::flock(self.0.as_raw_fd(), libc::LOCK_UN);
        }
    }
}
pub fn claim_ui(dir: &Path) -> Result<Option<UiLease>> {
    std::fs::create_dir_all(dir)?;
    let file = File::options()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(dir.join("ui.lock"))?;
    // The descriptor is retained for the entire GPUI event loop. The kernel
    // releases it on normal exit, crash, or renderer replacement.
    if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
        return Ok(Some(UiLease(file)));
    }
    let error = std::io::Error::last_os_error();
    if error.kind() == std::io::ErrorKind::WouldBlock {
        Ok(None)
    } else {
        Err(error.into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_instance_is_exclusive_per_workspace_and_released_on_exit() {
        let directory = tempfile::tempdir().expect("isolated workspace");
        let root = directory.path();
        let first = claim_ui(root).unwrap().unwrap();
        assert!(claim_ui(root).unwrap().is_none());
        let other = claim_ui(&root.join("other")).unwrap().unwrap();
        drop(first);
        let replacement = claim_ui(root).unwrap().unwrap();
        assert!(claim_ui(root).unwrap().is_none());
        drop((other, replacement));
    }
}
