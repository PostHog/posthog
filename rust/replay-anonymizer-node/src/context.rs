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

/// Cumulative decompressed-bytes budget across all cv payloads in one message: the per-payload
/// `gzip::MAX_DECOMPRESSED_BYTES` cap bounds each field, this bounds their sum so many high-ratio
/// fields can't decompress gigabytes serially. Real messages total under 10 MB.
const CV_MESSAGE_DECOMPRESSION_BUDGET: usize = 256 * 1024 * 1024;

pub struct Ctx<'a> {
    pub allow: &'a AllowLists,
    pub cv_budget: Cell<usize>,
    // key: the original data URI (data-image blur), or `raw:{w}x{h}:{base64}` (raw RGBA pixelate).
    // value: the blurred result, or `None` when blurring failed (caller falls back to a blank pixel).
    blur_cache: RefCell<HashMap<String, Option<String>>>,
}

impl<'a> Ctx<'a> {
    pub fn new(allow: &'a AllowLists) -> Self {
        Self {
            allow,
            cv_budget: Cell::new(CV_MESSAGE_DECOMPRESSION_BUDGET),
            blur_cache: RefCell::new(HashMap::new()),
        }
    }

    /// The only budgeted cv decompression path — cv code must not call `gzip::gunzip` directly.
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
