//! Neon native addon exposing the `posthog-replay-anonymizer` scrubbers to Node for the ml-mirror
//! pipeline.
//!
//! The production surface is the byte-buffer pipeline in `posthog_replay_anonymizer::snapshot`: the
//! decompressed Kafka payload goes in, ready-to-write JSONL block lines plus envelope/per-event
//! metadata come out — Rust owns the parse, the scrub, and the serialize, so no JSON crosses the FFI
//! boundary as a string. Behavior is pinned by the shared JSON fixtures in the core crate's
//! `tests/fixtures/`, which the Jest suite runs against through this addon.
//!
//! It also carries the image-scrub sidecar's pixel layout conversions (`pixels`), which fill model
//! inputs in place in typed arrays that the sidecar allocates, and the produce lanes' ref dedup
//! caches (`dedup`), which hold their entries outside the V8 heap.

mod brotli;
mod dedup;
mod pixels;

use std::collections::HashSet;
use std::sync::{Arc, RwLock};

use dedup::{image_ref_key, transport_url_key, DedupKey, RefDedupCache};
use neon::context::Lock;
use neon::prelude::*;
use neon::types::buffer::TypedArray;
use pixels::{LayoutError, PlaneOrder};
use posthog_replay_anonymizer::collect::{image_ref, url_ref};
use posthog_replay_anonymizer::snapshot::{AnonymizedMessage, ImageEntry};
use posthog_replay_anonymizer::{
    is_public_host, politeness_key, snapshot, try_canonicalize, AllowLists, FailKind,
    ImageCollection, ImagePolicy, PhaseTimings, UrlCollection,
};
use serde::Deserialize;

// The fail-closed contract depends on `catch_unwind` containing panics on untrusted input. Under
// `panic = "abort"` that becomes a no-op and one crafted message aborts the whole worker, so fail
// the build if the workspace release profile ever switches to abort.
#[cfg(all(panic = "abort", not(test)))]
compile_error!(
    "replay-anonymizer-node requires panic=unwind: catch_unwind is the fail-closed guard"
);

/// Deferred-parallel image scrubbing is the production default; `REPLAY_ANONYMIZER_PARALLEL_IMAGES=0`
/// (or `false`) is the rollback lever to the inline path. Worker count comes from
/// `REPLAY_ANONYMIZER_IMAGE_THREADS` (see the core crate's `images` module).
static IMAGE_POLICY: std::sync::OnceLock<ImagePolicy> = std::sync::OnceLock::new();

fn image_policy() -> ImagePolicy {
    *IMAGE_POLICY.get_or_init(|| {
        // Forgiving parse: this is an incident rollback lever, so common falsy spellings count.
        let disabled = std::env::var("REPLAY_ANONYMIZER_PARALLEL_IMAGES").is_ok_and(|v| {
            matches!(
                v.trim().to_ascii_lowercase().as_str(),
                "0" | "false" | "off" | "no"
            )
        });
        if disabled {
            ImagePolicy::Inline
        } else {
            ImagePolicy::Parallel
        }
    })
}

// The allow lists are immutable per process; set once at startup via `initAnonymizer`.
static ALLOW: RwLock<Option<AllowLists>> = RwLock::new(None);

#[derive(Deserialize)]
struct AllowInput {
    #[serde(default)]
    text: Vec<String>,
    #[serde(default)]
    url: Vec<String>,
}

fn init_anonymizer(mut cx: FunctionContext) -> JsResult<JsNull> {
    let json = cx.argument::<JsString>(0)?.value(&mut cx);
    let input: AllowInput = serde_json::from_str(&json)
        .or_else(|e| cx.throw_error(format!("invalid allow lists json: {e}")))?;
    let allow = AllowLists::new(input.text, input.url);
    *ALLOW.write().expect("allow lists lock poisoned") = Some(allow);
    Ok(cx.null())
}

/// The collected refs a produce lane's cache dropped before the meta was serialized. The caller
/// still counts them as collected, so the domain count is taken before the drop.
#[derive(Debug, Default, Clone, Copy)]
struct ProducedRefDrops {
    images: usize,
    urls: usize,
    collected_url_domains: usize,
}

struct Anonymized {
    lines: Vec<u8>,
    meta: String,
    route: &'static str,
    image_bytes: Vec<u8>,
    drops: ProducedRefDrops,
}

/// The off-thread outcome: anonymized output, a classified failure (dlq/drop reason + detail), or
/// an unclassified error (panic, missing init) that the caller must treat as `anonymize_failed`.
type TaskOutcome = Result<Result<Anonymized, (&'static str, String)>, String>;

struct DedupCacheHandle(Arc<RefDedupCache>);

impl Finalize for DedupCacheHandle {}

/// The produce lanes' caches, consulted without marking. A ref the cache already holds was
/// produced by an earlier message, so it never crosses into JS. A ref it does not hold is claimed
/// at produce time, after the checks that can still stop the produce.
struct ProducedRefFilter {
    images: Option<(Arc<RefDedupCache>, String)>,
    urls: Option<(Arc<RefDedupCache>, Option<String>, u64)>,
}

impl ProducedRefFilter {
    fn apply(&self, out: &mut AnonymizedMessage) -> ProducedRefDrops {
        let mut drops = ProducedRefDrops {
            collected_url_domains: out
                .meta
                .urls
                .iter()
                .map(|entry| entry.domain.as_str())
                .collect::<HashSet<_>>()
                .len(),
            ..Default::default()
        };
        if let Some((cache, team_id)) = &self.images {
            drops.images =
                drop_produced_images(cache, team_id, &mut out.meta.images, &mut out.image_bytes);
        }
        if let Some((cache, namespace, time_bucket)) = &self.urls {
            drops.urls = cache.retain_absent(&mut out.meta.urls, |entry| {
                transport_url_key(
                    &url_reference(namespace.as_deref(), &entry.hash),
                    &entry.url,
                    *time_bucket,
                )
            });
        }
        drops
    }
}

fn url_reference(namespace: Option<&str>, hash: &str) -> String {
    match namespace {
        Some(namespace) => format!("imageurl:{namespace}:{hash}"),
        None => url_ref(hash),
    }
}

/// Drops the entries the cache holds and repacks the bytes of the rest, so the bytes of an image
/// already produced never reach the JS heap's external memory.
fn drop_produced_images(
    cache: &RefDedupCache,
    team_id: &str,
    entries: &mut Vec<ImageEntry>,
    bytes: &mut Vec<u8>,
) -> usize {
    let dropped = cache.retain_absent(entries, |entry| {
        image_ref_key(&image_ref(team_id, &entry.hash))
    });
    if dropped > 0 {
        let mut packed = Vec::with_capacity(entries.iter().map(|entry| entry.len).sum());
        for entry in entries.iter_mut() {
            let start = packed.len();
            packed.extend_from_slice(&bytes[entry.offset..entry.offset + entry.len]);
            entry.offset = start;
        }
        *bytes = packed;
    }
    dropped
}

fn opt_dedup_cache_arg(
    cx: &mut FunctionContext,
    index: usize,
) -> NeonResult<Option<Arc<RefDedupCache>>> {
    match cx.argument_opt(index) {
        Some(v) if v.is_a::<JsUndefined, _>(cx) || v.is_a::<JsNull, _>(cx) => Ok(None),
        Some(v) => Ok(Some(
            v.downcast_or_throw::<JsBox<DedupCacheHandle>, _>(cx)?
                .0
                .clone(),
        )),
        None => Ok(None),
    }
}

fn time_bucket_arg(cx: &mut FunctionContext, index: usize) -> NeonResult<u64> {
    let bucket = cx.argument::<JsNumber>(index)?.value(cx);
    if !(bucket.is_finite() && bucket >= 0.0 && bucket.fract() == 0.0) {
        return cx.throw_range_error(format!(
            "time bucket must be a non-negative integer, got {bucket}"
        ));
    }
    Ok(bucket as u64)
}

/// The outcome plus the JSON phase timings, reported on every arm including panics.
type TaskResult = (TaskOutcome, Option<String>);

fn anonymize_kafka_payload_ffi(mut cx: FunctionContext) -> JsResult<JsPromise> {
    // One copy on the event loop: the buffer's bytes move into the task (they can't be borrowed
    // across threads, and simd-json needs a mutable scratch anyway). Decompression happens inside
    // the task too — gunzip of a multi-MB payload has no business on the event loop.
    let buf = cx.argument::<JsBuffer>(0)?;
    let raw = buf.as_slice(&cx).to_vec();
    let content_encoding: Option<String> = cx
        .argument_opt(1)
        .and_then(|v| v.downcast::<JsString, _>(&mut cx).ok())
        .map(|s| s.value(&mut cx));
    // Present + non-empty (both of them) enables the image-collection lane, keyed to this
    // raw team ID and per-team content-HMAC key. A present-but-non-string argument, or one
    // of the pair without the other, must fail loudly (the caller drops the message) rather than
    // silently disable or mis-key collection; only absent/undefined/null mean "collection off".
    let opt_string_arg = |cx: &mut FunctionContext, index: usize| -> NeonResult<Option<String>> {
        Ok(match cx.argument_opt(index) {
            Some(v) if v.is_a::<JsUndefined, _>(cx) || v.is_a::<JsNull, _>(cx) => None,
            Some(v) => Some(v.downcast_or_throw::<JsString, _>(cx)?.value(cx)),
            None => None,
        }
        .filter(|s| !s.is_empty()))
    };
    let team_id = opt_string_arg(&mut cx, 2)?;
    let content_key = opt_string_arg(&mut cx, 3)?;
    let url_key = opt_string_arg(&mut cx, 4)?;
    let reference_namespace = opt_string_arg(&mut cx, 5)?;
    let image_dedup = opt_dedup_cache_arg(&mut cx, 6)?;
    let url_dedup = match opt_dedup_cache_arg(&mut cx, 7)? {
        Some(cache) => Some((cache, time_bucket_arg(&mut cx, 8)?)),
        None => None,
    };
    if team_id.is_none() && content_key.is_some() {
        return cx.throw_error("contentKey requires teamId");
    }
    let image_collection = match (team_id.clone(), content_key) {
        (Some(team_id), Some(content_key)) => Some(ImageCollection {
            team_id,
            content_key,
        }),
        _ => None,
    };
    let produced_ref_filter = ProducedRefFilter {
        images: image_collection
            .as_ref()
            .zip(image_dedup)
            .map(|(collection, cache)| (cache, collection.team_id.clone())),
        urls: url_key
            .as_ref()
            .zip(url_dedup)
            .map(|(_, (cache, time_bucket))| (cache, reference_namespace.clone(), time_bucket)),
    };
    let url_collection = url_key.map(|url_key| UrlCollection {
        url_key,
        reference_namespace,
    });
    // Created on the JS thread so every offset shares one monotonic origin: the task-start mark
    // becomes the threadpool queue wait, and no wall clock is involved.
    let timings = PhaseTimings::new();
    let promise = cx
        .task(move || -> TaskResult {
            timings.task_started();
            // The sink stays outside the catch_unwind so partial timings survive a panic.
            // Contain any panic on untrusted input so it fails closed (the caller drops the message)
            // rather than risking process abort.
            let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let guard = ALLOW
                    .read()
                    .map_err(|_| "allow lists lock poisoned".to_string())?;
                let allow = guard.as_ref().ok_or_else(|| {
                    "anonymizer not initialized (call initAnonymizer first)".to_string()
                })?;
                timings.decompress_started();
                let mut payload =
                    match snapshot::decompress_payload(raw, content_encoding.as_deref()) {
                        Ok(p) => p,
                        Err(f) => return Ok(Err((f.kind.reason(), f.detail))),
                    };
                timings.decompress_finished();
                timings.scrub_started();
                let scrubbed = snapshot::anonymize_kafka_payload_collecting(
                    allow,
                    &mut payload,
                    snapshot::AnonymizeOpts {
                        image_policy: image_policy(),
                        ..Default::default()
                    },
                    Some(&timings),
                    image_collection,
                    url_collection,
                );
                timings.scrub_finished();
                match scrubbed {
                    Ok(mut out) => {
                        let drops = produced_ref_filter.apply(&mut out);
                        timings.mark("serialize_meta");
                        let meta = serde_json::to_string(&out.meta)
                            .map_err(|e| format!("serialize meta: {e}"))?;
                        timings.mark("done");
                        Ok(Ok(Anonymized {
                            lines: out.lines,
                            meta,
                            route: out.route.as_str(),
                            image_bytes: out.image_bytes,
                            drops,
                        }))
                    }
                    Err(f) => Ok(Err((f.kind.reason(), f.detail))),
                }
            }))
            .unwrap_or_else(|_| Err("panic while anonymizing".to_string()));
            (outcome, serde_json::to_string(&timings.snapshot()).ok())
        })
        .promise(|mut cx, (result, timings_json): TaskResult| {
            let obj = cx.empty_object();
            match timings_json {
                Some(json) => {
                    let timings = cx.string(json);
                    obj.set(&mut cx, "timings", timings)?;
                }
                None => {
                    let null = cx.null();
                    obj.set(&mut cx, "timings", null)?;
                }
            }
            let set_failure = |cx: &mut TaskContext<'_>,
                               obj: &Handle<'_, JsObject>,
                               reason: &str,
                               detail: String|
             -> NeonResult<()> {
                let failed = cx.boolean(true);
                obj.set(cx, "failed", failed)?;
                let reason = cx.string(reason);
                obj.set(cx, "reason", reason)?;
                let error = cx.string(detail);
                obj.set(cx, "error", error)?;
                let null = cx.null();
                obj.set(cx, "lines", null)?;
                let null = cx.null();
                obj.set(cx, "meta", null)?;
                let null = cx.null();
                obj.set(cx, "route", null)?;
                let null = cx.null();
                obj.set(cx, "images", null)?;
                Ok(())
            };
            match result {
                Ok(Ok(Anonymized {
                    lines,
                    meta,
                    route,
                    image_bytes,
                    drops,
                })) => {
                    let deduped_images = cx.number(drops.images as f64);
                    obj.set(&mut cx, "dedupedImageCount", deduped_images)?;
                    let deduped_urls = cx.number(drops.urls as f64);
                    obj.set(&mut cx, "dedupedUrlCount", deduped_urls)?;
                    let url_domains = cx.number(drops.collected_url_domains as f64);
                    obj.set(&mut cx, "collectedUrlDomainCount", url_domains)?;
                    let failed = cx.boolean(false);
                    obj.set(&mut cx, "failed", failed)?;
                    let null = cx.null();
                    obj.set(&mut cx, "reason", null)?;
                    let null = cx.null();
                    obj.set(&mut cx, "error", null)?;
                    // Externally-backed: the JS Buffer wraps the Vec directly (freed by the GC's
                    // finalizer) instead of copying the whole JSONL block across the boundary.
                    let lines = JsBuffer::external(&mut cx, lines);
                    obj.set(&mut cx, "lines", lines)?;
                    let meta = cx.string(meta);
                    obj.set(&mut cx, "meta", meta)?;
                    let route = cx.string(route);
                    obj.set(&mut cx, "route", route)?;
                    if image_bytes.is_empty() {
                        let null = cx.null();
                        obj.set(&mut cx, "images", null)?;
                    } else {
                        let images = JsBuffer::external(&mut cx, image_bytes);
                        obj.set(&mut cx, "images", images)?;
                    }
                }
                Ok(Err((reason, detail))) => set_failure(&mut cx, &obj, reason, detail)?,
                // Fail closed: an unclassified error still drops the message.
                Err(msg) => set_failure(&mut cx, &obj, FailKind::AnonymizeFailed.reason(), msg)?,
            }
            Ok(obj)
        });
    Ok(promise)
}

/// The registrable domain of a host. It needs no initialized state, so a lane that only fetches
/// never calls `initAnonymizer`.
fn politeness_key_ffi(mut cx: FunctionContext) -> JsResult<JsString> {
    let host = cx.argument::<JsString>(0)?.value(&mut cx);
    Ok(cx.string(politeness_key(&host)))
}

/// Whether the fetch lane may send a request to a host. It needs no initialized state, so a lane
/// that only fetches never calls `initAnonymizer`.
fn is_public_host_ffi(mut cx: FunctionContext) -> JsResult<JsBoolean> {
    let host = cx.argument::<JsString>(0)?.value(&mut cx);
    Ok(cx.boolean(is_public_host(&host)))
}

/// The URL policy's verdict for one URL: its canonical forms, or under `decline` the label of the
/// rule that refused it. The fetch lane reads the label so that it can drop a beacon job without
/// rejecting the record that carries it.
fn try_canonicalize_url_ffi(mut cx: FunctionContext) -> JsResult<JsObject> {
    let raw = cx.argument::<JsString>(0)?.value(&mut cx);
    let result = cx.empty_object();
    match try_canonicalize(&raw) {
        Ok(canonical) => {
            let fetch = cx.string(canonical.fetch);
            result.set(&mut cx, "fetch", fetch)?;
            let dedup = cx.string(canonical.dedup);
            result.set(&mut cx, "dedup", dedup)?;
            let host = cx.string(canonical.host);
            result.set(&mut cx, "host", host)?;
            let domain = cx.string(canonical.domain);
            result.set(&mut cx, "domain", domain)?;
        }
        Err(decline) => {
            let label = cx.string(decline.label());
            result.set(&mut cx, "decline", label)?;
            let unwanted = cx.boolean(decline.is_unwanted());
            result.set(&mut cx, "unwanted", unwanted)?;
        }
    }
    Ok(result)
}

enum InPlaceFailure {
    SharedMemory,
    Layout(LayoutError),
}

/// Runs `kernel` over the memory of both typed arrays, borrowed in place through one VM lock. The
/// lock's ledger refuses a destination that overlaps the source, which would otherwise alias the
/// kernel's `&[u8]` with its `&mut` slice.
fn run_on_borrowed<D: TypedArray>(
    lock: &Lock<'_, FunctionContext<'_>>,
    source: &JsUint8Array,
    destination: &mut D,
    kernel: impl FnOnce(&[u8], &mut [D::Item]) -> Result<(), LayoutError>,
) -> Result<(), InPlaceFailure> {
    let source = source
        .try_borrow(lock)
        .map_err(|_| InPlaceFailure::SharedMemory)?;
    let mut destination = destination
        .try_borrow_mut(lock)
        .map_err(|_| InPlaceFailure::SharedMemory)?;
    kernel(&source, &mut destination).map_err(InPlaceFailure::Layout)
}

fn convert_in_place<'cx, D: TypedArray>(
    cx: &mut FunctionContext<'cx>,
    source: Handle<'cx, JsUint8Array>,
    mut destination: Handle<'cx, D>,
    kernel: impl FnOnce(&[u8], &mut [D::Item]) -> Result<(), LayoutError>,
) -> JsResult<'cx, JsUndefined> {
    let converted = run_on_borrowed(&cx.lock(), &source, &mut *destination, kernel);
    match converted {
        Ok(()) => Ok(cx.undefined()),
        Err(InPlaceFailure::SharedMemory) => {
            cx.throw_error("the source and destination share memory")
        }
        Err(InPlaceFailure::Layout(error)) => cx.throw_range_error(error.to_string()),
    }
}

fn plane_order_arg(cx: &mut FunctionContext, index: usize) -> NeonResult<PlaneOrder> {
    let order = cx.argument::<JsString>(index)?.value(cx);
    match order.as_str() {
        "rgb" => Ok(PlaneOrder::Rgb),
        "bgr" => Ok(PlaneOrder::Bgr),
        _ => cx.throw_type_error(format!("plane order must be 'rgb' or 'bgr', got '{order}'")),
    }
}

fn per_plane_arg(cx: &mut FunctionContext, index: usize) -> NeonResult<[f64; 3]> {
    let values = cx.argument::<JsArray>(index)?;
    if values.len(cx) != 3 {
        return cx.throw_range_error("expected one value per plane");
    }
    let mut per_plane = [0.0; 3];
    for (plane, value) in (0u32..).zip(per_plane.iter_mut()) {
        *value = values.get::<JsNumber, _, _>(cx, plane)?.value(cx);
    }
    Ok(per_plane)
}

fn rgb_to_chw_ffi(mut cx: FunctionContext) -> JsResult<JsUndefined> {
    let rgb = cx.argument::<JsUint8Array>(0)?;
    let chw = cx.argument::<JsFloat32Array>(1)?;
    let order = plane_order_arg(&mut cx, 2)?;
    convert_in_place(&mut cx, rgb, chw, |rgb, chw| {
        pixels::rgb_to_chw(rgb, chw, order)
    })
}

fn rgb_to_normalized_chw_ffi(mut cx: FunctionContext) -> JsResult<JsUndefined> {
    let rgb = cx.argument::<JsUint8Array>(0)?;
    let chw = cx.argument::<JsFloat32Array>(1)?;
    let order = plane_order_arg(&mut cx, 2)?;
    let mean = per_plane_arg(&mut cx, 3)?;
    let std = per_plane_arg(&mut cx, 4)?;
    convert_in_place(&mut cx, rgb, chw, |rgb, chw| {
        pixels::rgb_to_normalized_chw(rgb, chw, order, mean, std)
    })
}

fn rgb_to_rgba_ffi(mut cx: FunctionContext) -> JsResult<JsUndefined> {
    let rgb = cx.argument::<JsUint8Array>(0)?;
    let rgba = cx.argument::<JsUint8Array>(1)?;
    convert_in_place(&mut cx, rgb, rgba, pixels::rgb_to_rgba)
}

fn ref_dedup_cache_new(mut cx: FunctionContext) -> JsResult<JsBox<DedupCacheHandle>> {
    let capacity = cx.argument::<JsNumber>(0)?.value(&mut cx);
    if !(capacity.is_finite() && capacity >= 0.0 && capacity.fract() == 0.0) {
        return cx.throw_range_error(format!(
            "ref cache capacity must be 0 or a positive integer, got {capacity}"
        ));
    }
    Ok(cx.boxed(DedupCacheHandle(Arc::new(RefDedupCache::new(
        capacity as usize,
    )))))
}

fn string_array_arg(cx: &mut FunctionContext, index: usize) -> NeonResult<Vec<String>> {
    let values = cx.argument::<JsArray>(index)?.to_vec(cx)?;
    values
        .into_iter()
        .map(|value| Ok(value.downcast_or_throw::<JsString, _>(cx)?.value(cx)))
        .collect()
}

fn image_ref_keys_arg(cx: &mut FunctionContext) -> NeonResult<Vec<DedupKey>> {
    Ok(string_array_arg(cx, 1)?
        .iter()
        .map(|reference| image_ref_key(reference))
        .collect())
}

fn transport_url_keys_arg(cx: &mut FunctionContext) -> NeonResult<Vec<DedupKey>> {
    let references = string_array_arg(cx, 1)?;
    let urls = string_array_arg(cx, 2)?;
    if references.len() != urls.len() {
        return cx.throw_range_error("expected one URL per ref");
    }
    let time_bucket = time_bucket_arg(cx, 3)?;
    Ok(references
        .iter()
        .zip(&urls)
        .map(|(reference, url)| transport_url_key(reference, url, time_bucket))
        .collect())
}

fn claimed_array<'cx>(cx: &mut FunctionContext<'cx>, claimed: Vec<bool>) -> JsResult<'cx, JsArray> {
    let array = cx.empty_array();
    for (index, claimed) in (0u32..).zip(claimed) {
        let claimed = cx.boolean(claimed);
        array.set(cx, index, claimed)?;
    }
    Ok(array)
}

fn ref_dedup_cache_claim_refs(mut cx: FunctionContext) -> JsResult<JsArray> {
    let cache = cx.argument::<JsBox<DedupCacheHandle>>(0)?.0.clone();
    let keys = image_ref_keys_arg(&mut cx)?;
    claimed_array(&mut cx, cache.claim(&keys))
}

fn ref_dedup_cache_release_refs(mut cx: FunctionContext) -> JsResult<JsUndefined> {
    let cache = cx.argument::<JsBox<DedupCacheHandle>>(0)?.0.clone();
    cache.release(&image_ref_keys_arg(&mut cx)?);
    Ok(cx.undefined())
}

fn ref_dedup_cache_claim_transport_urls(mut cx: FunctionContext) -> JsResult<JsArray> {
    let cache = cx.argument::<JsBox<DedupCacheHandle>>(0)?.0.clone();
    let keys = transport_url_keys_arg(&mut cx)?;
    claimed_array(&mut cx, cache.claim(&keys))
}

fn ref_dedup_cache_release_transport_urls(mut cx: FunctionContext) -> JsResult<JsUndefined> {
    let cache = cx.argument::<JsBox<DedupCacheHandle>>(0)?.0.clone();
    cache.release(&transport_url_keys_arg(&mut cx)?);
    Ok(cx.undefined())
}

fn ref_dedup_cache_stats(mut cx: FunctionContext) -> JsResult<JsObject> {
    let stats = cx.argument::<JsBox<DedupCacheHandle>>(0)?.0.stats();
    let result = cx.empty_object();
    for (name, value) in [
        ("entries", stats.entries),
        ("evictions", stats.evictions),
        ("wouldHit", stats.would_hit),
        ("wouldMiss", stats.would_miss),
    ] {
        let value = cx.number(value as f64);
        result.set(&mut cx, name, value)?;
    }
    Ok(result)
}

fn compress_brotli_ffi(mut cx: FunctionContext) -> JsResult<JsPromise> {
    let input = cx.argument::<JsBuffer>(0)?.as_slice(&cx).to_vec();
    let quality = cx.argument::<JsNumber>(1)?.value(&mut cx);
    if !(quality.fract() == 0.0 && (2.0..=11.0).contains(&quality)) {
        return cx.throw_range_error(format!(
            "brotli quality must be an integer from 2 to 11, got {quality}"
        ));
    }
    let promise = cx
        .task(move || brotli::compress(&input, quality as u8))
        .promise(|mut cx, compressed| match compressed {
            Ok(compressed) => Ok(JsBuffer::external(&mut cx, compressed)),
            Err(error) => cx.throw_error(error),
        });
    Ok(promise)
}

#[neon::main]
fn main(mut cx: ModuleContext) -> NeonResult<()> {
    cx.export_function("initAnonymizer", init_anonymizer)?;
    cx.export_function("anonymizeKafkaPayload", anonymize_kafka_payload_ffi)?;
    cx.export_function("politenessKey", politeness_key_ffi)?;
    cx.export_function("isPublicHost", is_public_host_ffi)?;
    cx.export_function("tryCanonicalizeUrl", try_canonicalize_url_ffi)?;
    cx.export_function("rgbToChw", rgb_to_chw_ffi)?;
    cx.export_function("rgbToNormalizedChw", rgb_to_normalized_chw_ffi)?;
    cx.export_function("rgbToRgba", rgb_to_rgba_ffi)?;
    cx.export_function("refDedupCacheNew", ref_dedup_cache_new)?;
    cx.export_function("refDedupCacheClaimRefs", ref_dedup_cache_claim_refs)?;
    cx.export_function("refDedupCacheReleaseRefs", ref_dedup_cache_release_refs)?;
    cx.export_function(
        "refDedupCacheClaimTransportUrls",
        ref_dedup_cache_claim_transport_urls,
    )?;
    cx.export_function(
        "refDedupCacheReleaseTransportUrls",
        ref_dedup_cache_release_transport_urls,
    )?;
    cx.export_function("refDedupCacheStats", ref_dedup_cache_stats)?;
    cx.export_function("compressBrotli", compress_brotli_ffi)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(hash: &str, offset: usize, len: usize) -> ImageEntry {
        ImageEntry {
            hash: hash.to_string(),
            offset,
            len,
        }
    }

    #[test]
    fn dropping_a_produced_image_repacks_the_rest_under_their_own_hashes() {
        let cache = RefDedupCache::new(10);
        cache.claim(&[image_ref_key(&image_ref("7", "first"))]);
        let mut entries = vec![entry("first", 0, 3), entry("second", 3, 2)];
        let mut bytes = b"aaabb".to_vec();

        assert_eq!(
            drop_produced_images(&cache, "7", &mut entries, &mut bytes),
            1
        );

        assert_eq!(entries, vec![entry("second", 0, 2)]);
        assert_eq!(bytes, b"bb");
    }
}
