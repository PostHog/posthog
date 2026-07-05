//! Per-message scrub context: the allow lists plus a blur memo.
//!
//! Within one Kafka message the same image often recurs thousands of times (a canvas redrawing one
//! sprite, a repeated background). Blurring is pure in its input, so we memoize it per message and
//! collapse that fan-out to a single decode+blur — mirroring the TS `blurCache` (also scoped to one
//! message). Scope is one `anonymize_message` call; the map is dropped when it returns.

use std::cell::{Cell, RefCell};
use std::collections::HashMap;

use anyhow::{bail, Result};

use crate::allow_lists::AllowLists;
use crate::blur::{blur_image_data_uri, pixelate_raw_rgba};

/// Cumulative decompressed-bytes budget for all cv payloads in one message. Individual payloads
/// are capped by `gzip::MAX_DECOMPRESSED_BYTES`; this bounds the *sum*, so a message stuffed with
/// many high-ratio fields can't decompress gigabytes serially (a CPU/latency bomb even though each
/// buffer is freed between fields). Real messages total well under 10 MB decompressed; the budget
/// is sized with room for the byte walk's decline-and-reparse path charging a field twice.
const CV_MESSAGE_DECOMPRESSION_BUDGET: usize = 256 * 1024 * 1024;

pub struct Ctx<'a> {
    pub allow: &'a AllowLists,
    /// Remaining cv decompression budget for this message (see [`CV_MESSAGE_DECOMPRESSION_BUDGET`]).
    pub cv_budget: Cell<usize>,
    /// Re-emit every cv payload (changed or not) as zstd instead of gzip, keeping output blocks
    /// single-format (see `AnonymizeOpts::cv_zstd` — on in production, `false` is the gzip
    /// fallback).
    pub cv_zstd: bool,
    // key: the original data URI (data-image blur), or `raw:{w}x{h}:{base64}` (raw RGBA pixelate).
    // value: the blurred result, or `None` when blurring failed (caller falls back to a blank pixel).
    blur_cache: RefCell<HashMap<String, Option<String>>>,
}

impl<'a> Ctx<'a> {
    pub fn new(allow: &'a AllowLists) -> Self {
        Self {
            allow,
            cv_budget: Cell::new(CV_MESSAGE_DECOMPRESSION_BUDGET),
            cv_zstd: false,
            blur_cache: RefCell::new(HashMap::new()),
        }
    }

    pub fn with_cv_zstd(mut self, on: bool) -> Self {
        self.cv_zstd = on;
        self
    }

    /// Gunzip a cv payload, charging the message-cumulative budget. All cv decompression must go
    /// through here (not `gzip::gunzip` directly) so the budget can't be bypassed.
    pub fn gunzip_cv(&self, raw: &[u8]) -> Result<Vec<u8>> {
        let out = crate::gzip::gunzip(raw)?;
        match self.cv_budget.get().checked_sub(out.len()) {
            Some(rest) => self.cv_budget.set(rest),
            None => bail!("message exceeds the cumulative cv decompression budget"),
        }
        Ok(out)
    }

    // Borrow discipline: never hold a `blur_cache` borrow across the blur call — the compute runs
    // borrow-free, so a future blur helper that re-entered `Ctx` still couldn't double-borrow-panic.

    /// Blur a data-image URI, memoized on the URI. `None` → caller falls back to a blank/placeholder.
    pub fn blur_data_uri(&self, original: &str) -> Option<String> {
        if let Some(hit) = self.blur_cache.borrow().get(original) {
            return hit.clone();
        }
        let result = blur_image_data_uri(original);
        self.blur_cache
            .borrow_mut()
            .insert(original.to_string(), result.clone());
        result
    }

    /// Pixelate raw RGBA pixels, memoized on dimensions + bytes.
    pub fn pixelate_raw(&self, rgba_base64: &str, width: u32, height: u32) -> Option<String> {
        let key = format!("raw:{width}x{height}:{rgba_base64}");
        if let Some(hit) = self.blur_cache.borrow().get(&key) {
            return hit.clone();
        }
        let result = pixelate_raw_rgba(rgba_base64, width, height);
        self.blur_cache.borrow_mut().insert(key, result.clone());
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testkit::png_data_uri;

    #[test]
    fn blur_memo_is_stable_and_keyed_per_image() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let a = png_data_uri(100, 50, [10, 20, 30, 255]);
        let b = png_data_uri(40, 40, [200, 100, 50, 255]);
        // Same input → same result twice (a cache hit must not return something different).
        assert_eq!(ctx.blur_data_uri(&a), ctx.blur_data_uri(&a));
        // Distinct inputs → distinct results (guards against a cache-key collision serving A's blur for B).
        assert_ne!(ctx.blur_data_uri(&a), ctx.blur_data_uri(&b));
    }
}
