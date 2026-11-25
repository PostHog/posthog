//! Cross-platform async channel primitives for native and WASM targets.

#[cfg(not(target_family = "wasm"))]
pub use smol::channel::{Receiver, Sender, unbounded};

#[cfg(target_family = "wasm")]
pub use async_channel::{Receiver, Sender, unbounded};
