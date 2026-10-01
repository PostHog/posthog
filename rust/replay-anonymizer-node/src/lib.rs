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

mod dedup;
mod image_batch;
mod pixels;
mod url_batch;

use std::cell::RefCell;
use std::collections::HashSet;
use std::sync::{Arc, RwLock};

use dedup::RefDedupCache;
use image_batch::ImageBatch;
use neon::context::Lock;
use neon::prelude::*;
use neon::types::buffer::TypedArray;
use pixels::{LayoutError, PlaneOrder};
use posthog_replay_anonymizer::snapshot::AnonymizedMessage;
use posthog_replay_anonymizer::{
    is_public_host, politeness_key, snapshot, try_canonicalize, AllowLists, FailKind,
    ImageCollection, ImagePolicy, PhaseTimings, UrlCollection,
};
use serde::Deserialize;
use url_batch::{JobTemplate, RecordLimits, UrlBatch};

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

/// The caller counts the refs a produce lane's cache left out as collected, so the domain count is
/// taken before they are left out.
#[derive(Default)]
struct Collected {
    images: Option<ImageBatch>,
    urls: Option<UrlBatch>,
    deduped_images: usize,
    deduped_urls: usize,
    collected_url_domains: usize,
}

struct Anonymized {
    lines: Vec<u8>,
    meta: String,
    route: &'static str,
    collected: Collected,
}

/// The off-thread outcome: anonymized output, a classified failure (dlq/drop reason + detail), or
/// an unclassified error (panic, missing init) that the caller must treat as `anonymize_failed`.
type TaskOutcome = Result<Result<Anonymized, (&'static str, String)>, String>;

struct DedupCacheHandle(Arc<RefDedupCache>);

impl Finalize for DedupCacheHandle {}

struct ImageBatchHandle(RefCell<ImageBatch>);

impl Finalize for ImageBatchHandle {}

struct UrlBatchHandle(RefCell<UrlBatch>);

impl Finalize for UrlBatchHandle {}

/// The cache is consulted without marking. A ref it does not hold is claimed at produce time,
/// after the checks that can still stop the produce.
struct CollectionLane<N, P> {
    namespace: N,
    produced: Option<P>,
}

type ProducedUrls = (Arc<RefDedupCache>, u64);

struct CollectionLanes {
    images: Option<CollectionLane<String, Arc<RefDedupCache>>>,
    urls: Option<CollectionLane<Option<String>, ProducedUrls>>,
}

impl CollectionLanes {
    fn take_collected(&self, out: &mut AnonymizedMessage) -> Collected {
        let image_entries = std::mem::take(&mut out.meta.images);
        let image_bytes = std::mem::take(&mut out.image_bytes);
        let url_entries = std::mem::take(&mut out.meta.urls);
        let mut collected = Collected {
            collected_url_domains: url_entries
                .iter()
                .map(|entry| entry.domain.as_str())
                .collect::<HashSet<_>>()
                .len(),
            ..Default::default()
        };
        if let Some(lane) = &self.images {
            (collected.images, collected.deduped_images) = ImageBatch::collect(
                &lane.namespace,
                image_entries,
                &image_bytes,
                lane.produced.as_deref(),
            );
        }
        if let Some(lane) = &self.urls {
            (collected.urls, collected.deduped_urls) = UrlBatch::collect(
                lane.namespace.as_deref(),
                url_entries,
                lane.produced
                    .as_ref()
                    .map(|(cache, time_bucket)| (cache.as_ref(), *time_bucket)),
            );
        }
        collected
    }
}

fn opt_string_arg(cx: &mut FunctionContext, index: usize) -> NeonResult<Option<String>> {
    match cx.argument_opt(index) {
        Some(v) if v.is_a::<JsUndefined, _>(cx) || v.is_a::<JsNull, _>(cx) => Ok(None),
        Some(v) => Ok(Some(v.downcast_or_throw::<JsString, _>(cx)?.value(cx))),
        None => Ok(None),
    }
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
    let opt_non_empty_string_arg =
        |cx: &mut FunctionContext, index: usize| -> NeonResult<Option<String>> {
            Ok(opt_string_arg(cx, index)?.filter(|s| !s.is_empty()))
        };
    let team_id = opt_non_empty_string_arg(&mut cx, 2)?;
    let content_key = opt_non_empty_string_arg(&mut cx, 3)?;
    let url_key = opt_non_empty_string_arg(&mut cx, 4)?;
    let reference_namespace = opt_non_empty_string_arg(&mut cx, 5)?;
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
    let collection_lanes = CollectionLanes {
        images: image_collection.as_ref().map(|collection| CollectionLane {
            namespace: collection.team_id.clone(),
            produced: image_dedup,
        }),
        urls: url_key.as_ref().map(|_| CollectionLane {
            namespace: reference_namespace.clone(),
            produced: url_dedup,
        }),
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
                        let collected = collection_lanes.take_collected(&mut out);
                        timings.mark("serialize_meta");
                        let meta = serde_json::to_string(&out.meta)
                            .map_err(|e| format!("serialize meta: {e}"))?;
                        timings.mark("done");
                        Ok(Ok(Anonymized {
                            lines: out.lines,
                            meta,
                            route: out.route.as_str(),
                            collected,
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
                obj.set(cx, "imageBatch", null)?;
                let null = cx.null();
                obj.set(cx, "urlBatch", null)?;
                Ok(())
            };
            match result {
                Ok(Ok(Anonymized {
                    lines,
                    meta,
                    route,
                    collected,
                })) => {
                    let deduped_images = cx.number(collected.deduped_images as f64);
                    obj.set(&mut cx, "dedupedImageCount", deduped_images)?;
                    let deduped_urls = cx.number(collected.deduped_urls as f64);
                    obj.set(&mut cx, "dedupedUrlCount", deduped_urls)?;
                    let url_domains = cx.number(collected.collected_url_domains as f64);
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
                    let image_batch = image_batch_object(&mut cx, collected.images)?;
                    obj.set(&mut cx, "imageBatch", image_batch)?;
                    let url_batch = url_batch_object(&mut cx, collected.urls)?;
                    obj.set(&mut cx, "urlBatch", url_batch)?;
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

fn buffer_array_arg(cx: &mut FunctionContext, index: usize) -> NeonResult<Vec<Vec<u8>>> {
    let values = cx.argument::<JsArray>(index)?.to_vec(cx)?;
    values
        .into_iter()
        .map(|value| {
            let buffer = value.downcast_or_throw::<JsBuffer, _>(cx)?;
            Ok(buffer.as_slice(cx).to_vec())
        })
        .collect()
}

fn dedup_cache_arg(cx: &mut FunctionContext, index: usize) -> NeonResult<Arc<RefDedupCache>> {
    Ok(cx.argument::<JsBox<DedupCacheHandle>>(index)?.0.clone())
}

const MAX_SAFE_INTEGER: f64 = 9_007_199_254_740_991.0;

/// A safe integer converts to `u64` exactly and prints as `JSON.stringify` prints it.
fn safe_integer_arg(
    cx: &mut FunctionContext,
    index: usize,
    name: &str,
    minimum: u64,
) -> NeonResult<u64> {
    let value = cx.argument::<JsNumber>(index)?.value(cx);
    if !(value.is_finite()
        && value.fract() == 0.0
        && value >= minimum as f64
        && value <= MAX_SAFE_INTEGER)
    {
        return cx.throw_range_error(format!(
            "{name} must be a safe integer of at least {minimum}, got {value}"
        ));
    }
    Ok(value as u64)
}

fn string_array<'cx, C: Context<'cx>, S: AsRef<str>>(
    cx: &mut C,
    values: impl IntoIterator<Item = S>,
) -> JsResult<'cx, JsArray> {
    let array = cx.empty_array();
    for (index, value) in (0u32..).zip(values) {
        let value = cx.string(value);
        array.set(cx, index, value)?;
    }
    Ok(array)
}

fn owned_buffer<'cx, C: Context<'cx>>(cx: &mut C, bytes: Vec<u8>) -> JsResult<'cx, JsBuffer> {
    // An empty Vec owns no allocation, so there is nothing to hand to an external buffer.
    if bytes.is_empty() {
        return JsBuffer::new(cx, 0);
    }
    Ok(JsBuffer::external(cx, bytes))
}

fn owned_buffer_array<'cx, C: Context<'cx>>(
    cx: &mut C,
    values: Vec<Vec<u8>>,
) -> JsResult<'cx, JsArray> {
    let array = cx.empty_array();
    for (index, value) in (0u32..).zip(values) {
        let value = owned_buffer(cx, value)?;
        array.set(cx, index, value)?;
    }
    Ok(array)
}

fn batch_object<'cx, C: Context<'cx>, H: Finalize + 'static>(
    cx: &mut C,
    count: usize,
    first_ref: Handle<'cx, JsString>,
    handle: H,
) -> JsResult<'cx, JsValue> {
    let object = cx.empty_object();
    let handle = cx.boxed(handle);
    object.set(cx, "handle", handle)?;
    let count = cx.number(count as f64);
    object.set(cx, "count", count)?;
    object.set(cx, "firstRef", first_ref)?;
    Ok(object.upcast())
}

fn image_batch_object<'cx, C: Context<'cx>>(
    cx: &mut C,
    batch: Option<ImageBatch>,
) -> JsResult<'cx, JsValue> {
    let Some(batch) = batch else {
        return Ok(cx.null().upcast());
    };
    let first_ref = cx.string(batch.first_ref());
    let count = batch.count();
    batch_object(cx, count, first_ref, ImageBatchHandle(RefCell::new(batch)))
}

fn url_batch_object<'cx, C: Context<'cx>>(
    cx: &mut C,
    batch: Option<UrlBatch>,
) -> JsResult<'cx, JsValue> {
    let Some(batch) = batch else {
        return Ok(cx.null().upcast());
    };
    let first_ref = cx.string(batch.first_ref());
    let count = batch.count();
    batch_object(cx, count, first_ref, UrlBatchHandle(RefCell::new(batch)))
}

fn image_batch_new(mut cx: FunctionContext) -> JsResult<JsValue> {
    let namespace = cx.argument::<JsString>(0)?.value(&mut cx);
    let hashes = string_array_arg(&mut cx, 1)?;
    let images = buffer_array_arg(&mut cx, 2)?;
    if hashes.len() != images.len() {
        return cx.throw_range_error("expected one image per hash");
    }
    let batch = ImageBatch::from_images(&namespace, hashes.into_iter().zip(images).collect());
    image_batch_object(&mut cx, batch)
}

fn image_batch_claim(mut cx: FunctionContext) -> JsResult<JsObject> {
    let batch = cx.argument::<JsBox<ImageBatchHandle>>(0)?;
    let cache = dedup_cache_arg(&mut cx, 1)?;
    let claimed = batch.0.borrow_mut().claim(&cache);
    let Ok(claimed) = claimed else {
        return cx.throw_error("the image batch was already claimed");
    };
    let result = cx.empty_object();
    let refs = string_array(&mut cx, claimed.references)?;
    result.set(&mut cx, "refs", refs)?;
    let images = owned_buffer_array(&mut cx, claimed.images)?;
    result.set(&mut cx, "images", images)?;
    let bytes = cx.number(claimed.bytes as f64);
    result.set(&mut cx, "bytes", bytes)?;
    Ok(result)
}

fn image_batch_release(mut cx: FunctionContext) -> JsResult<JsUndefined> {
    let batch = cx.argument::<JsBox<ImageBatchHandle>>(0)?;
    let cache = dedup_cache_arg(&mut cx, 1)?;
    batch.0.borrow_mut().release(&cache);
    Ok(cx.undefined())
}

fn url_batch_new(mut cx: FunctionContext) -> JsResult<JsValue> {
    let namespace = opt_string_arg(&mut cx, 0)?;
    let hashes = string_array_arg(&mut cx, 1)?;
    let urls = string_array_arg(&mut cx, 2)?;
    let domains = string_array_arg(&mut cx, 3)?;
    if hashes.len() != urls.len() || hashes.len() != domains.len() {
        return cx.throw_range_error("expected one URL and one domain per hash");
    }
    let entries = hashes
        .into_iter()
        .zip(urls)
        .zip(domains)
        .map(|((hash, url), domain)| (hash, url, domain))
        .collect();
    let batch = UrlBatch::from_urls(namespace.as_deref(), entries);
    url_batch_object(&mut cx, batch)
}

fn url_batch_claim(mut cx: FunctionContext) -> JsResult<JsNumber> {
    let batch = cx.argument::<JsBox<UrlBatchHandle>>(0)?;
    let cache = dedup_cache_arg(&mut cx, 1)?;
    let time_bucket = time_bucket_arg(&mut cx, 2)?;
    let claimed = batch.0.borrow_mut().claim(&cache, time_bucket);
    match claimed {
        Ok(count) => Ok(cx.number(count as f64)),
        Err(url_batch::OutOfOrder(message)) => cx.throw_error(message),
    }
}

fn url_batch_unique_refs(mut cx: FunctionContext) -> JsResult<JsArray> {
    let batch = cx.argument::<JsBox<UrlBatchHandle>>(0)?;
    let batch = batch.0.borrow();
    string_array(&mut cx, batch.unique_refs())
}

fn url_batch_build_records(mut cx: FunctionContext) -> JsResult<JsObject> {
    let batch = cx.argument::<JsBox<UrlBatchHandle>>(0)?;
    let excluded_refs: HashSet<String> = string_array_arg(&mut cx, 1)?.into_iter().collect();
    let session_id = opt_string_arg(&mut cx, 2)?;
    let first_seen_at_ms = safe_integer_arg(&mut cx, 3, "firstSeenAtMs", 0)?;
    let limits = RecordLimits {
        max_bytes: safe_integer_arg(&mut cx, 4, "maxRecordBytes", 1)? as usize,
        max_urls: safe_integer_arg(&mut cx, 5, "maxRecordUrls", 1)? as usize,
    };
    let job = JobTemplate::new(session_id.as_deref(), first_seen_at_ms);
    let built = batch
        .0
        .borrow_mut()
        .build_records(&excluded_refs, &job, limits);
    let built = match built {
        Ok(built) => built,
        Err(url_batch::OutOfOrder(message)) => return cx.throw_error(message),
    };
    let url_counts: Vec<u32> = built
        .records
        .iter()
        .map(|record| u32::try_from(record.url_count).unwrap_or(u32::MAX))
        .collect();
    let (keys, values): (Vec<String>, Vec<Vec<u8>>) = built
        .records
        .into_iter()
        .map(|record| (record.registrable_domain, record.value))
        .unzip();
    let result = cx.empty_object();
    let keys = string_array(&mut cx, keys)?;
    result.set(&mut cx, "keys", keys)?;
    let values = owned_buffer_array(&mut cx, values)?;
    result.set(&mut cx, "values", values)?;
    let url_counts = JsUint32Array::from_slice(&mut cx, &url_counts)?;
    result.set(&mut cx, "urlCounts", url_counts)?;
    let url_byte_lengths = JsUint32Array::from_slice(&mut cx, &built.url_byte_lengths)?;
    result.set(&mut cx, "urlByteLengths", url_byte_lengths)?;
    let domain_count = cx.number(built.domain_count as f64);
    result.set(&mut cx, "domainCount", domain_count)?;
    Ok(result)
}

fn url_batch_release(mut cx: FunctionContext) -> JsResult<JsUndefined> {
    let batch = cx.argument::<JsBox<UrlBatchHandle>>(0)?;
    let cache = dedup_cache_arg(&mut cx, 1)?;
    batch.0.borrow_mut().release(&cache);
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
    cx.export_function("refDedupCacheStats", ref_dedup_cache_stats)?;
    cx.export_function("imageBatchNew", image_batch_new)?;
    cx.export_function("imageBatchClaim", image_batch_claim)?;
    cx.export_function("imageBatchRelease", image_batch_release)?;
    cx.export_function("urlBatchNew", url_batch_new)?;
    cx.export_function("urlBatchClaim", url_batch_claim)?;
    cx.export_function("urlBatchUniqueRefs", url_batch_unique_refs)?;
    cx.export_function("urlBatchBuildRecords", url_batch_build_records)?;
    cx.export_function("urlBatchRelease", url_batch_release)?;
    Ok(())
}
