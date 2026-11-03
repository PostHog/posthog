//! Neon native addon exposing the v4 URL policy, `replay_core_v4::url_policy`, the crawl history
//! rule, `replay_core_v4::fetch_history`, and the fetched image frame and references,
//! `replay_core_v4::fetched_image`, to the v4 image fetcher.
//!
//! The recorder writes and reads with those modules, and the fetcher must decide and seal the
//! same way, so the fetcher calls the modules rather than a second implementation. This crate is
//! glue only: each function converts its arguments and its result, and the rules stay in the core
//! crate.

use neon::prelude::*;
use neon::types::buffer::TypedArray;
use replay_core_v4::fetch_history::UrlHistory;
use replay_core_v4::fetched_image::{image_url_hash, image_url_ref, seal_fetched_image};
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

/// `null` also for a team id that a JavaScript number cannot hold exactly.
fn parse_v4_url_ref_ffi(mut cx: FunctionContext) -> JsResult<JsValue> {
    const MAX_SAFE_INTEGER: i64 = (1 << 53) - 1;
    let reference = cx.argument::<JsString>(0)?.value(&mut cx);
    let Some(parsed) =
        image_url_ref(&reference).filter(|parsed| parsed.team_id <= MAX_SAFE_INTEGER)
    else {
        return Ok(cx.null().upcast());
    };
    let result = cx.empty_object();
    let team_id = cx.number(parsed.team_id as f64);
    result.set(&mut cx, "teamId", team_id)?;
    let key_month = cx.string(parsed.key_month);
    result.set(&mut cx, "keyMonth", key_month)?;
    let hash = cx.string(parsed.hash);
    result.set(&mut cx, "hash", hash)?;
    Ok(result.upcast())
}

fn team_month_key(cx: &mut FunctionContext, index: usize) -> NeonResult<[u8; 32]> {
    let key = cx.argument::<JsBuffer>(index)?;
    match <[u8; 32]>::try_from(key.as_slice(cx)) {
        Ok(key) => Ok(key),
        Err(_) => cx.throw_range_error("a team month key is 32 bytes"),
    }
}

/// Seals off the event loop, because a fetched image can be megabytes.
fn seal_fetched_image_ffi(mut cx: FunctionContext) -> JsResult<JsPromise> {
    let key = team_month_key(&mut cx, 0)?;
    let reference = cx.argument::<JsString>(1)?.value(&mut cx);
    let image = cx.argument::<JsBuffer>(2)?.as_slice(&cx).to_vec();
    let promise = cx
        .task(move || seal_fetched_image(&key, &reference, &image))
        .promise(|mut cx, frame| match frame {
            Ok(frame) => Ok(JsBuffer::external(&mut cx, frame)),
            Err(error) => cx.throw_error(error.to_string()),
        });
    Ok(promise)
}

fn image_url_hash_ffi(mut cx: FunctionContext) -> JsResult<JsString> {
    let key = team_month_key(&mut cx, 0)?;
    let url = cx.argument::<JsString>(1)?.value(&mut cx);
    Ok(cx.string(image_url_hash(&key, &url)))
}

#[neon::main]
fn main(mut cx: ModuleContext) -> NeonResult<()> {
    cx.export_function("politenessKey", politeness_key_ffi)?;
    cx.export_function("isPublicHost", is_public_host_ffi)?;
    cx.export_function("tryCanonicalizeUrl", try_canonicalize_url_ffi)?;
    cx.export_function("urlJob", url_job_ffi)?;
    cx.export_function("isUrlHistoryValue", is_url_history_value_ffi)?;
    cx.export_function("parseV4UrlRef", parse_v4_url_ref_ffi)?;
    cx.export_function("sealFetchedImage", seal_fetched_image_ffi)?;
    cx.export_function("imageUrlHash", image_url_hash_ffi)?;
    Ok(())
}
