//! Cached tiktoken cl100k_base encoder.
//!
//! `tiktoken_rs::cl100k_base()` rebuilds the entire BPE encoder on every call
//! (decoding ~100k vocabulary entries and constructing several HashMaps), which
//! costs ~50-200ms of CPU per invocation. We call it on hot paths — every signal
//! emission and every stacktrace truncation check — so we cache it once for the
//! lifetime of the process.

use once_cell::sync::Lazy;
use tiktoken_rs::{cl100k_base, CoreBPE};

pub static CL100K_BPE: Lazy<CoreBPE> =
    Lazy::new(|| cl100k_base().expect("cl100k_base encoder must be constructible"));

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cl100k_bpe_is_reused_across_calls() {
        // Two derefs should yield the same underlying instance (same address),
        // proving the encoder is initialized once and reused.
        let first: *const CoreBPE = &*CL100K_BPE;
        let second: *const CoreBPE = &*CL100K_BPE;
        assert_eq!(first, second);
    }

    #[test]
    fn cl100k_bpe_encodes_text() {
        let tokens = CL100K_BPE.encode_with_special_tokens("hello world");
        assert!(!tokens.is_empty());
    }
}
