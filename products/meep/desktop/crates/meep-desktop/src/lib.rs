//! Platform services a desktop host can adopt independently.
#[cfg(target_os = "macos")]
pub mod dock;
#[cfg(unix)]
pub mod instance;
#[cfg(target_os = "macos")]
pub mod updates;
