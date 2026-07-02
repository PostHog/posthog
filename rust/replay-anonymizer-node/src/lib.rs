//! Session-replay anonymizer: PII-scrubs parsed rrweb events for the ml-mirror pipeline, exposed to
//! Node as a Neon native addon.
//!
//! This is a Rust port of `nodejs/src/ingestion/pipelines/sessionreplay/anonymize/*.ts` (the source of
//! truth). It walks a parsed message's events in place, redacting text/URLs, blurring images natively,
//! and de/recompressing `cv` payloads. Parity with the TS is asserted via shared JSON fixtures under
//! `tests/fixtures/` (the same fixtures the Jest suite runs against). The crate builds both an `rlib`
//! (for `cargo test`) and a `cdylib` (the `index.node` addon).

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
pub mod text;
pub mod url;
pub mod value;

pub use allow_lists::AllowLists;
pub use context::Ctx;
pub use event::{anonymize_event, anonymize_event_str, anonymize_message};

use std::sync::RwLock;

use neon::prelude::*;
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

fn anonymize(mut cx: FunctionContext) -> JsResult<JsPromise> {
    let json = cx.argument::<JsString>(0)?.value(&mut cx);
    let promise = cx
        .task(move || -> Result<Option<String>, String> {
            // Contain any panic on untrusted input so it fails closed (rejected promise -> the caller
            // drops the message) rather than risking process abort.
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let guard = ALLOW
                    .read()
                    .map_err(|_| "allow lists lock poisoned".to_string())?;
                let allow = guard.as_ref().ok_or_else(|| {
                    "anonymizer not initialized (call initAnonymizer first)".to_string()
                })?;
                let mut bytes = json.into_bytes();
                anonymize_message(allow, &mut bytes).map_err(|e| e.to_string())
            }))
            .unwrap_or_else(|_| Err("panic while anonymizing".to_string()))
        })
        .promise(|mut cx, result: Result<Option<String>, String>| {
            let obj = cx.empty_object();
            match result {
                Ok(opt) => {
                    let failed = cx.boolean(false);
                    obj.set(&mut cx, "failed", failed)?;
                    // `data: null` means "nothing changed" — the caller keeps its original parse.
                    match opt {
                        Some(s) => {
                            let data = cx.string(s);
                            obj.set(&mut cx, "data", data)?;
                        }
                        None => {
                            let data = cx.null();
                            obj.set(&mut cx, "data", data)?;
                        }
                    }
                    let error = cx.null();
                    obj.set(&mut cx, "error", error)?;
                }
                Err(msg) => {
                    // Fail closed: report failure so the caller drops the message.
                    let failed = cx.boolean(true);
                    obj.set(&mut cx, "failed", failed)?;
                    let data = cx.null();
                    obj.set(&mut cx, "data", data)?;
                    let error = cx.string(msg);
                    obj.set(&mut cx, "error", error)?;
                }
            }
            Ok(obj)
        });
    Ok(promise)
}

#[neon::main]
fn main(mut cx: ModuleContext) -> NeonResult<()> {
    cx.export_function("initAnonymizer", init_anonymizer)?;
    cx.export_function("anonymize", anonymize)?;
    Ok(())
}
