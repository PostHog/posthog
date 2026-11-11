//! Per-message scrub context: the allow lists plus an image memo.
//!
//! Within one Kafka message the same image often recurs thousands of times (a canvas redrawing one
//! sprite, a repeated background). Its outcome is pure in its input, so we memoize it per message and
//! collapse that fan-out to a single decode and hash. Scope is one `anonymize_message` call; the
//! map is dropped when it returns.

use std::cell::{Cell, RefCell};
use std::collections::{BTreeMap, HashMap};

use anyhow::{bail, Result};
use serde::Serialize;

use crate::allow_lists::AllowLists;
use crate::assets::{is_numbered_placeholder, PLACEHOLDER_SRC};
use crate::collect::{
    collectable_data_uri_bytes, is_image_ref, CollectedImage, ImageCollection, ImageCollector,
    DROP_COLLECTION_OFF, DROP_MESSAGE_CAP, MAX_IMAGE_BYTES,
};
use crate::data_uri::blank_image_data_uri;
use crate::data_uri::ImageFallback;
use crate::timings::PhaseTimings;
use crate::url_collect::{CollectedUrl, UrlCollection, UrlCollector};

/// Cumulative decompressed-bytes budget across all cv payloads in one message: the per-payload
/// `compression::MAX_DECOMPRESSED_BYTES` cap bounds each field, this bounds their sum so many high-ratio
/// fields can't decompress gigabytes serially. Real messages total under 10 MB.
const CV_MESSAGE_DECOMPRESSION_BUDGET: usize = 256 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum ImageSource {
    CssProperty(&'static str),
    HtmlAttribute(&'static str),
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct CountCheckpoint {
    image_sources: usize,
    scrub_drops: usize,
    images: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct ImageSourceCount {
    pub source: &'static str,
    pub property: &'static str,
    pub kind: &'static str,
    pub count: u32,
}

/// Scrub context: the allow lists, the cv decompression budget, the image memo, and the optional
/// collection lanes.
pub struct Ctx<'a> {
    pub allow: &'a AllowLists,
    pub cv_budget: Cell<usize>,
    // key: the original data URI. value: its content ref, or why the scrub lane declined it.
    image_memo: RefCell<HashMap<String, Result<String, &'static str>>>,
    timings: Option<&'a PhaseTimings>,
    // `Some` routes images to the scrub lane. Without it every image is blanked.
    collector: Option<RefCell<ImageCollector>>,
    // `Some` routes remote image URLs to the fetch lane and emits refs beside the media placeholder.
    url_collector: Option<RefCell<UrlCollector>>,
    // Logs, not tallies, so a walk whose output is thrown away can take its entries back with it.
    image_source_log: RefCell<Vec<(ImageSource, &'static str)>>,
    scrub_drop_log: RefCell<Vec<&'static str>>,
    // Whether a well-formed ref already present in the *input* is left alone. Off unless the
    // caller vouches for the input's provenance; see `preserving_image_refs`.
    preserve_image_refs: bool,
}

impl<'a> Ctx<'a> {
    pub fn new(allow: &'a AllowLists) -> Self {
        Self::with_options(allow, None, None)
    }

    pub fn with_timings(allow: &'a AllowLists, timings: Option<&'a PhaseTimings>) -> Self {
        Self::with_options(allow, timings, None)
    }

    pub fn with_image_collection(
        allow: &'a AllowLists,
        image_collection: Option<ImageCollection>,
    ) -> Self {
        Self::with_options(allow, None, image_collection)
    }

    pub(crate) fn with_options(
        allow: &'a AllowLists,
        timings: Option<&'a PhaseTimings>,
        image_collection: Option<ImageCollection>,
    ) -> Self {
        Self {
            allow,
            cv_budget: Cell::new(CV_MESSAGE_DECOMPRESSION_BUDGET),
            image_memo: RefCell::new(HashMap::new()),
            timings,
            collector: image_collection.map(|c| RefCell::new(ImageCollector::new(c))),
            url_collector: None,
            image_source_log: RefCell::new(Vec::new()),
            scrub_drop_log: RefCell::new(Vec::new()),
            preserve_image_refs: false,
        }
    }

    /// Leave well-formed image refs already present in the input alone instead of scrubbing them.
    ///
    /// Off by default, and it must stay off for anything scrubbing untrusted capture input: the
    /// ref format is not a secret, so a page could set a media attribute to a forged one and have
    /// it copied into output unscrubbed. Enable it only where the input is known to be this
    /// anonymizer's own mirrored output being re-scrubbed — there a ref is a join key whose bytes
    /// were already scrubbed out of band, and re-scrubbing it destroys the only route back to them.
    pub fn preserving_image_refs(mut self) -> Self {
        self.preserve_image_refs = true;
        self
    }

    /// Whether an input-side ref may skip scrubbing (see [`Self::preserving_image_refs`]).
    pub(crate) fn keeps_image_refs(&self) -> bool {
        self.preserve_image_refs
    }

    /// Scrub one image data URI: the collection lane's content ref, whose original bytes ride back
    /// to the caller for the out-of-band scrub. An image the lane cannot take is replaced by
    /// `fallback` and counted, never passed through or scrubbed here.
    pub(crate) fn scrub_image(&self, original: &str, fallback: ImageFallback) -> String {
        // This anonymizer's own stand-ins, met again on a re-scrub, carry no page content. A numbered
        // placeholder's digits are free text a page could forge, so it is trusted only on a re-scrub.
        if original == PLACEHOLDER_SRC
            || original == blank_image_data_uri()
            || (self.keeps_image_refs() && is_numbered_placeholder(original))
        {
            return original.to_string();
        }
        match self.collect_image(original) {
            Ok(reference) => reference,
            Err(reason) => {
                self.record_scrub_drop(reason);
                match fallback {
                    ImageFallback::Blank => blank_image_data_uri(),
                    ImageFallback::Placeholder => PLACEHOLDER_SRC.to_string(),
                }
            }
        }
    }

    pub(crate) fn scrub_image_from(
        &self,
        original: &str,
        fallback: ImageFallback,
        source: ImageSource,
    ) -> String {
        let scrubbed = self.scrub_image(original, fallback);
        if is_image_ref(&scrubbed) {
            self.record_image_source(source, "inline");
        }
        scrubbed
    }

    fn timed<T>(&self, op: &'static str, f: impl FnOnce() -> T) -> T {
        match self.timings {
            Some(t) => t.time_op(op, f),
            None => f(),
        }
    }

    /// Route remote image URLs to the fetch lane. Off unless set, exactly like image collection.
    /// The media source keeps its placeholder either way.
    pub fn collecting_urls(mut self, url_collection: Option<UrlCollection>) -> Self {
        self.url_collector = url_collection.map(|c| RefCell::new(UrlCollector::new(c)));
        self
    }

    /// The fetch lane's ref for a remote image URL.
    ///
    /// `None` when collection is off, when the URL is not fetchable, or when the per-message cap
    /// is reached. The caller writes the placeholder regardless and stashes a returned ref beside
    /// it.
    pub(crate) fn collect_url(&self, original: &str) -> Option<String> {
        let collector = self.url_collector.as_ref()?;
        collector.borrow_mut().collect(original)
    }

    pub(crate) fn collects_urls(&self) -> bool {
        self.url_collector.is_some()
    }

    /// Count a URL the walker refused before it reached the policy, in the collector's own decline
    /// metric, so that the walker's refusals and the policy's refusals read on one panel. Like the
    /// policy's memoized declines it counts once per distinct URL in a message, so a repeated
    /// spacer, and a re-walk after the byte walker hands an event to the tree path, do not count
    /// twice.
    pub(crate) fn decline_url(&self, raw: &str, reason: &'static str) {
        if let Some(collector) = self.url_collector.as_ref() {
            collector.borrow_mut().decline_once(raw, reason);
        }
    }

    pub(crate) fn collect_url_from(&self, original: &str, source: ImageSource) -> Option<String> {
        let reference = self.collect_url(original)?;
        self.record_image_source(source, "url");
        Some(reference)
    }

    fn record_image_source(&self, source: ImageSource, kind: &'static str) {
        self.image_source_log.borrow_mut().push((source, kind));
    }

    pub(crate) fn record_scrub_drop(&self, reason: &'static str) {
        self.scrub_drop_log.borrow_mut().push(reason);
    }

    /// A point to roll the counts back to when a walk's output is discarded and the same content is
    /// walked again, so each occurrence is counted once.
    pub(crate) fn count_checkpoint(&self) -> CountCheckpoint {
        CountCheckpoint {
            image_sources: self.image_source_log.borrow().len(),
            scrub_drops: self.scrub_drop_log.borrow().len(),
            images: self
                .collector
                .as_ref()
                .map_or(0, |collector| collector.borrow().len()),
        }
    }

    pub(crate) fn restore_counts(&self, checkpoint: CountCheckpoint) {
        self.image_source_log
            .borrow_mut()
            .truncate(checkpoint.image_sources);
        self.scrub_drop_log
            .borrow_mut()
            .truncate(checkpoint.scrub_drops);
    }

    /// Unlike a re-walk, which collects the same bytes again under the same ref, a discarded walk
    /// leaves no ref in the output, so its images go too.
    pub(crate) fn discard_walk(&self, checkpoint: CountCheckpoint) {
        self.restore_counts(checkpoint);
        let Some(collector) = self.collector.as_ref() else {
            return;
        };
        let removed = collector.borrow_mut().truncate(checkpoint.images);
        if !removed.is_empty() {
            self.image_memo.borrow_mut().retain(|_, hit| match hit {
                Ok(reference) => !removed.contains(reference),
                // The freed room may now take an image the cap refused.
                Err(reason) => *reason != DROP_MESSAGE_CAP,
            });
        }
    }

    pub fn take_scrub_drops(&self) -> Vec<(&'static str, u32)> {
        let mut counts: BTreeMap<&'static str, u32> = BTreeMap::new();
        for reason in std::mem::take(&mut *self.scrub_drop_log.borrow_mut()) {
            let count = counts.entry(reason).or_default();
            *count = count.saturating_add(1);
        }
        counts.into_iter().collect()
    }

    pub fn take_image_source_counts(&self) -> Vec<ImageSourceCount> {
        let mut counts: BTreeMap<(ImageSource, &'static str), u32> = BTreeMap::new();
        for entry in std::mem::take(&mut *self.image_source_log.borrow_mut()) {
            let count = counts.entry(entry).or_default();
            *count = count.saturating_add(1);
        }
        counts
            .into_iter()
            .map(|((source, kind), count)| {
                let (source, property) = match source {
                    ImageSource::CssProperty(property) => ("css", property),
                    ImageSource::HtmlAttribute(property) => ("html", property),
                };
                ImageSourceCount {
                    source,
                    property,
                    kind,
                    count,
                }
            })
            .collect()
    }

    /// Drain the collected URLs (hash-sorted). Empty when URL collection was off.
    ///
    /// Takes the collector rather than `self`, because the caller drains the images afterwards and
    /// that call consumes the context. A second call therefore returns nothing, which is why this
    /// is not named `into_`.
    /// Counts by reason for the URLs the collector refused. Read before [`Self::take_collected_urls`],
    /// which takes the collector.
    pub fn take_url_declines(&self) -> Vec<(String, u32)> {
        match self.url_collector.as_ref() {
            Some(collector) => collector.borrow().into_declines(),
            None => Vec::new(),
        }
    }

    pub fn take_collected_urls(&mut self) -> Vec<CollectedUrl> {
        match self.url_collector.take() {
            Some(collector) => collector.into_inner().into_urls(),
            None => Vec::new(),
        }
    }

    /// Drain the collected images (hash-sorted). Empty when collection was off.
    pub fn into_collected_images(self) -> Vec<CollectedImage> {
        match self.collector {
            Some(collector) => collector.into_inner().into_images(),
            None => Vec::new(),
        }
    }

    /// Restore the full cv decompression budget. The budget bounds one message; per-line callers
    /// ([`crate::event::anonymize_line_with_ctx`]) reset it each call so a long session file
    /// cannot exhaust it, while the image memo keeps spanning the whole `Ctx`.
    pub fn reset_cv_budget(&self) {
        self.cv_budget.set(CV_MESSAGE_DECOMPRESSION_BUDGET);
    }

    /// The only budgeted cv decompression path — cv code must not call the [`crate::compression`]
    /// codecs directly. Magic-byte dispatch (gzip or zstd, unknown fails closed) lives in
    /// [`crate::compression::decompress_by_magic`]; this layers the cumulative budget on top.
    pub fn decompress_cv(&self, raw: &[u8]) -> Result<Vec<u8>> {
        let out = self.timed("cv", || crate::compression::decompress_by_magic(raw))?;
        match self.cv_budget.get().checked_sub(out.len()) {
            Some(rest) => self.cv_budget.set(rest),
            None => bail!("message exceeds the cumulative cv decompression budget"),
        }
        Ok(out)
    }

    /// The collection lane's ref for a data URI, or why the lane declined it. Both are memoized,
    /// so a sprite recurring thousands of times decodes and hashes once.
    fn collect_image(&self, original: &str) -> Result<String, &'static str> {
        let collector = self.collector.as_ref().ok_or(DROP_COLLECTION_OFF)?;
        if let Some(hit) = self.image_memo.borrow().get(original) {
            return hit.clone();
        }
        let max_image_bytes = collector.borrow().max_image_bytes();
        let outcome = collectable_data_uri_bytes(original, max_image_bytes)
            .and_then(|bytes| collector.borrow_mut().collect(bytes));
        self.image_memo
            .borrow_mut()
            .insert(original.to_string(), outcome.clone());
        outcome
    }

    /// Memoized when the lane is on, so the scrub that follows reuses this decode.
    pub(crate) fn can_collect_image(&self, original: &str) -> bool {
        match self.collector {
            Some(_) => self.collect_image(original).is_ok(),
            None => collectable_data_uri_bytes(original, MAX_IMAGE_BYTES).is_ok(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testkit::png_data_uri;

    #[test]
    fn decompress_cv_dispatches_on_magic_and_budgets_both_codecs() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let payload = b"x".repeat(1000);
        let gz = crate::compression::gzip(&payload).unwrap();
        let zs = crate::compression::compress_cv(&payload).unwrap();
        for compressed in [&gz, &zs] {
            let ctx = Ctx::new(&allow);
            assert_eq!(ctx.decompress_cv(compressed).unwrap(), payload);

            let ctx = Ctx::new(&allow);
            ctx.cv_budget.set(10);
            let err = ctx.decompress_cv(compressed).unwrap_err().to_string();
            assert!(err.contains("budget"), "got: {err}");
        }
    }

    #[test]
    fn decompress_cv_fails_closed_on_unknown_magic() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        assert!(ctx
            .decompress_cv(b"plainly not a compressed stream")
            .is_err());
        assert!(ctx.decompress_cv(b"").is_err());
    }

    #[test]
    fn a_discarded_walk_frees_the_message_cap_for_a_later_image() {
        use base64::Engine;
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::with_image_collection(
            &allow,
            Some(ImageCollection::new("42".to_string(), "k".repeat(32))),
        );
        let uri = |n: usize| {
            let payload = base64::engine::general_purpose::STANDARD.encode(n.to_be_bytes());
            format!("data:image/png;base64,{payload}")
        };
        let checkpoint = ctx.count_checkpoint();
        for n in 0..crate::collect::MAX_IMAGES_PER_MESSAGE {
            assert!(is_image_ref(
                &ctx.scrub_image(&uri(n), ImageFallback::Blank)
            ));
        }
        let late = uri(usize::MAX);
        assert_eq!(
            ctx.scrub_image(&late, ImageFallback::Blank),
            blank_image_data_uri()
        );
        ctx.discard_walk(checkpoint);
        assert!(is_image_ref(&ctx.scrub_image(&late, ImageFallback::Blank)));
        assert_eq!(ctx.into_collected_images().len(), 1);
    }

    #[test]
    fn this_anonymizers_own_stand_ins_are_never_collected() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let lane = || Some(ImageCollection::new("42".to_string(), "k".repeat(32)));
        let numbered = crate::assets::numbered_placeholder(7);
        let cases = [
            (
                Ctx::with_image_collection(&allow, lane()),
                PLACEHOLDER_SRC.to_string(),
                true,
            ),
            (
                Ctx::with_image_collection(&allow, lane()),
                blank_image_data_uri(),
                true,
            ),
            (
                Ctx::with_image_collection(&allow, lane()).preserving_image_refs(),
                numbered.clone(),
                true,
            ),
            // Untrusted input: the digits could carry anything, so it goes through the scrub.
            (Ctx::with_image_collection(&allow, lane()), numbered, false),
        ];
        for (ctx, original, kept) in cases {
            let scrubbed = ctx.scrub_image(&original, ImageFallback::Placeholder);
            assert_eq!(scrubbed == original, kept, "{original}");
            assert!(ctx.take_scrub_drops().is_empty());
            assert_eq!(ctx.into_collected_images().is_empty(), kept);
        }
    }

    #[test]
    fn an_image_the_lane_cannot_take_is_blanked_and_counted() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let png = png_data_uri(8, 8, [10, 20, 30, 255]);
        let lane = || Some(ImageCollection::new("42".to_string(), "k".repeat(32)));
        let tiny_lane = || {
            Some(ImageCollection {
                max_image_bytes: 16,
                ..ImageCollection::new("42".to_string(), "k".repeat(32))
            })
        };
        let cases = [
            (
                Ctx::new(&allow),
                png.clone(),
                crate::collect::DROP_COLLECTION_OFF,
            ),
            (
                Ctx::with_image_collection(&allow, lane()),
                "data:image/svg+xml;base64,bm90IHN2Zw==".to_string(),
                crate::collect::DROP_SVG,
            ),
            (
                Ctx::with_image_collection(&allow, tiny_lane()),
                png.clone(),
                crate::collect::DROP_TOO_LARGE,
            ),
        ];
        for (ctx, uri, reason) in cases {
            assert_eq!(
                ctx.scrub_image(&uri, ImageFallback::Blank),
                blank_image_data_uri(),
                "{reason}"
            );
            assert_eq!(
                ctx.scrub_image(&uri, ImageFallback::Placeholder),
                PLACEHOLDER_SRC,
                "{reason}"
            );
            assert_eq!(ctx.take_scrub_drops(), vec![(reason, 2)], "{reason}");
        }
    }
}
