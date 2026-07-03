//! Session-replay anonymizer: PII-scrubs rrweb events for the ml-mirror pipeline, exposed to Node as
//! a Neon native addon.
//!
//! The scrubbers are a Rust port of `nodejs/src/ingestion/pipelines/sessionreplay/anonymize/*.ts`
//! (the source of truth): text/URL redaction, native image blur, `cv` de/recompression. Parity with
//! the TS is asserted via shared JSON fixtures under `tests/fixtures/` (the same fixtures the Jest
//! suite runs against).
//!
//! The production surface is the byte-buffer pipeline in [`snapshot`]: the decompressed Kafka payload
//! goes in, ready-to-write JSONL block lines plus envelope/per-event metadata come out — Rust owns
//! the parse, the scrub, and the serialize, so no JSON crosses the FFI boundary as a string. The
//! crate builds both an `rlib` (for `cargo test`) and a `cdylib` (the `index.node` addon).

pub mod allow_lists;
pub mod assets;
pub mod blur;
pub mod canvas;
pub mod context;
pub mod css;
pub mod cv;
pub mod dom;
pub mod event;
pub mod json;
pub mod scan;
pub mod snapshot;
pub mod text;
pub mod url;
pub mod value;

pub use allow_lists::AllowLists;
pub use context::Ctx;
pub use event::{anonymize_event, anonymize_event_str, anonymize_message};
pub use snapshot::{
    anonymize_kafka_payload, anonymize_kafka_payload_opts, AnonymizeOpts, AnonymizedMessage,
    FailKind, Failure, Route,
};

/// Shared helpers for the image-neutralization tests across modules.
#[cfg(test)]
pub(crate) mod testkit {
    use base64::Engine;

    fn encode_png(w: u32, h: u32, color: [u8; 4]) -> Vec<u8> {
        let img =
            image::DynamicImage::ImageRgba8(image::RgbaImage::from_pixel(w, h, image::Rgba(color)));
        let mut buf = Vec::new();
        img.write_to(&mut std::io::Cursor::new(&mut buf), image::ImageFormat::Png)
            .unwrap();
        buf
    }

    /// Base64 of an encoded PNG (no `data:` prefix) — e.g. for a canvas Blob's ArrayBuffer.
    pub fn png_base64(w: u32, h: u32, color: [u8; 4]) -> String {
        base64::engine::general_purpose::STANDARD.encode(encode_png(w, h, color))
    }

    pub fn png_data_uri(w: u32, h: u32, color: [u8; 4]) -> String {
        format!("data:image/png;base64,{}", png_base64(w, h, color))
    }

    /// Base64 of `w*h` non-uniform RGBA pixels — e.g. for a canvas `ImageData` ArrayBuffer.
    pub fn rgba_base64(w: u32, h: u32) -> String {
        let mut raw = Vec::with_capacity((w * h * 4) as usize);
        for i in 0..(w * h) {
            let b = (i % 256) as u8;
            raw.extend_from_slice(&[b, b.wrapping_add(50), b.wrapping_add(100), 255]);
        }
        base64::engine::general_purpose::STANDARD.encode(raw)
    }
}

use std::sync::RwLock;

use neon::prelude::*;
use neon::types::buffer::TypedArray;
use serde::Deserialize;

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
    // across threads, and simd-json needs a mutable scratch anyway).
    let buf = cx.argument::<JsBuffer>(0)?;
    let mut payload = buf.as_slice(&cx).to_vec();
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
                match snapshot::anonymize_kafka_payload(allow, &mut payload) {
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
