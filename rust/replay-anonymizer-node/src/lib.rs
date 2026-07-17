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
use posthog_replay_anonymizer::{snapshot, AllowLists, FailKind};
use serde::Deserialize;

// The fail-closed contract depends on `catch_unwind` containing panics on untrusted input. Under
// `panic = "abort"` that becomes a no-op and one crafted message aborts the whole worker, so fail
// the build if the workspace release profile ever switches to abort.
#[cfg(all(panic = "abort", not(test)))]
compile_error!(
    "replay-anonymizer-node requires panic=unwind: catch_unwind is the fail-closed guard"
);

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
    // A present-but-non-string argument must fail loudly (the caller drops the message), not
    // silently disable first-party collapsing; only absent/undefined/null mean "no hosts".
    let first_party_hosts_json: Option<String> = match cx.argument_opt(2) {
        Some(v) if v.is_a::<JsUndefined, _>(&mut cx) || v.is_a::<JsNull, _>(&mut cx) => None,
        Some(v) => Some(v.downcast_or_throw::<JsString, _>(&mut cx)?.value(&mut cx)),
        None => None,
    };
    let promise = cx
        .task(move || -> TaskOutcome {
            // Contain any panic on untrusted input so it fails closed (the caller drops the message)
            // rather than risking process abort.
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let guard = ALLOW
                    .read()
                    .map_err(|_| "allow lists lock poisoned".to_string())?;
                let allow = guard.as_ref().ok_or_else(|| {
                    "anonymizer not initialized (call initAnonymizer first)".to_string()
                })?;
                // A malformed host list fails closed (message dropped), never silently unscrubbed.
                let first_party_hosts: Vec<String> = match &first_party_hosts_json {
                    Some(json) => {
                        let hosts: Vec<String> = serde_json::from_str(json)
                            .map_err(|e| format!("invalid first-party hosts json: {e}"))?;
                        hosts
                            .iter()
                            .map(|h| h.trim().to_ascii_lowercase())
                            .filter(|h| !h.is_empty())
                            .collect()
                    }
                    None => Vec::new(),
                };
                let mut payload =
                    match snapshot::decompress_payload(raw, content_encoding.as_deref()) {
                        Ok(p) => p,
                        Err(f) => return Ok(Err((f.kind.reason(), f.detail))),
                    };
                match snapshot::anonymize_kafka_payload_opts(
                    allow,
                    &mut payload,
                    snapshot::AnonymizeOpts::default(),
                    first_party_hosts,
                ) {
                    Ok(out) => {
                        let meta = serde_json::to_string(&out.meta)
                            .map_err(|e| format!("serialize meta: {e}"))?;
                        Ok(Ok((out.lines, meta, out.route.as_str())))
                    }
                    Err(f) => Ok(Err((f.kind.reason(), f.detail))),
                }
            }))
            .unwrap_or_else(|_| Err("panic while anonymizing".to_string()))
        })
        .promise(|mut cx, result: TaskOutcome| {
            let obj = cx.empty_object();
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
