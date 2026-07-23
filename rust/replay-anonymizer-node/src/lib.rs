//! Neon native addon exposing the `posthog-replay-anonymizer` scrubbers to Node for the ml-mirror
//! pipeline.
//!
//! The production surface is the byte-buffer pipeline in `posthog_replay_anonymizer::snapshot`: the
//! decompressed Kafka payload goes in, ready-to-write JSONL block lines plus envelope/per-event
//! metadata come out — Rust owns the parse, the scrub, and the serialize, so no JSON crosses the FFI
//! boundary as a string. Behavior is pinned by the shared JSON fixtures in the core crate's
//! `tests/fixtures/`, which the Jest suite runs against through this addon.

use std::sync::RwLock;

use neon::prelude::*;
use neon::types::buffer::TypedArray;
use posthog_replay_anonymizer::{snapshot, AllowLists, FailKind, ImagePolicy, PhaseTimings};
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

/// The off-thread outcome: anonymized output, a classified failure (dlq/drop reason + detail), or an
/// unclassified error (panic, missing init) that the caller must treat as `anonymize_failed`.
type TaskOutcome = Result<Result<(Vec<u8>, String, &'static str), (&'static str, String)>, String>;

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
                let scrubbed = snapshot::anonymize_kafka_payload_timed(
                    allow,
                    &mut payload,
                    snapshot::AnonymizeOpts {
                        image_policy: image_policy(),
                        ..Default::default()
                    },
                    Some(&timings),
                );
                timings.scrub_finished();
                match scrubbed {
                    Ok(out) => {
                        timings.mark("serialize_meta");
                        let meta = serde_json::to_string(&out.meta)
                            .map_err(|e| format!("serialize meta: {e}"))?;
                        timings.mark("done");
                        Ok(Ok((out.lines, meta, out.route.as_str())))
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
                Ok(())
            };
            match result {
                Ok(Ok((lines, meta, route))) => {
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
                }
                Ok(Err((reason, detail))) => set_failure(&mut cx, &obj, reason, detail)?,
                // Fail closed: an unclassified error still drops the message.
                Err(msg) => set_failure(&mut cx, &obj, FailKind::AnonymizeFailed.reason(), msg)?,
            }
            Ok(obj)
        });
    Ok(promise)
}

#[neon::main]
fn main(mut cx: ModuleContext) -> NeonResult<()> {
    cx.export_function("initAnonymizer", init_anonymizer)?;
    cx.export_function("anonymizeKafkaPayload", anonymize_kafka_payload_ffi)?;
    Ok(())
}
