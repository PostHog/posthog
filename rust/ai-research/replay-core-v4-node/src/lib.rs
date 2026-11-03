//! Neon native addon exposing the v4 URL policy, `replay_core_v4::url_policy`, and the crawl
//! history rule, `replay_core_v4::fetch_history`, to the v4 image fetcher.
//!
//! The recorder collects URLs and drops jobs with those modules, and the fetcher must decide the
//! same way, so the fetcher calls the modules rather than a second implementation. This crate is
//! glue only: each function converts its arguments and its result, and the rules stay in the core
//! crate.

use neon::prelude::*;
use replay_core_v4::fetch_history::UrlHistory;
use replay_core_v4::url_policy::{is_public_host, politeness_key, try_canonicalize};

/// The registrable domain of a host.
fn politeness_key_ffi(mut cx: FunctionContext) -> JsResult<JsString> {
    let host = cx.argument::<JsString>(0)?.value(&mut cx);
    Ok(cx.string(politeness_key(&host)))
}

/// Whether the fetch lane may send a request to a host.
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

fn url_job_ffi(mut cx: FunctionContext) -> JsResult<JsString> {
    let next_fetch_at_ms = cx.argument::<JsNumber>(0)?.value(&mut cx);
    let stored_at_ms = cx
        .argument::<JsValue>(1)?
        .downcast::<JsNumber, _>(&mut cx)
        .ok()
        .map(|stored_at_ms| stored_at_ms.value(&mut cx));
    let now_ms = cx.argument::<JsNumber>(2)?.value(&mut cx);
    let history = UrlHistory {
        next_fetch_at_ms,
        stored_at_ms,
    };
    Ok(cx.string(history.job_at(now_ms).label()))
}

fn is_url_history_value_ffi(mut cx: FunctionContext) -> JsResult<JsBoolean> {
    let key = cx.argument::<JsString>(0)?.value(&mut cx);
    let value = cx.argument::<JsString>(1)?.value(&mut cx);
    Ok(cx.boolean(UrlHistory::parse(&key, &value).is_some()))
}

#[neon::main]
fn main(mut cx: ModuleContext) -> NeonResult<()> {
    cx.export_function("politenessKey", politeness_key_ffi)?;
    cx.export_function("isPublicHost", is_public_host_ffi)?;
    cx.export_function("tryCanonicalizeUrl", try_canonicalize_url_ffi)?;
    cx.export_function("urlJob", url_job_ffi)?;
    cx.export_function("isUrlHistoryValue", is_url_history_value_ffi)?;
    Ok(())
}
