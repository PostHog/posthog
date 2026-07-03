//! Decode/scrub/re-encode per-event `cv` compression (gzip stored as latin-1 codepoints).
//! Mirrors `anonymize/cv.ts`.

use anyhow::{bail, Context, Result};
use simd_json::borrowed::{Object, Value};
use simd_json::prelude::Writable;
use simd_json::StaticNode;

use crate::bytewalk;
use crate::context::Ctx;
use crate::dom::{
    scrub_full_snapshot, scrub_mutation_adds, scrub_mutation_attributes, scrub_mutation_texts,
};
use crate::gzip;
use crate::json::{as_array_mut, key, parse_untrusted, reject_if_too_deep, string_value};

/// PostHog wire format: each gzip byte stored as its U+00XX codepoint (latin-1).
///
/// Deliberately per-char: gzip bytes are high-entropy, so the ASCII/two-byte branch mispredicts
/// either way and a hand-rolled byte loop measured slower than `chars()` on the production corpus
/// (bounds checks with no exploitable run structure). The real saving here is structural — decoding
/// gzip bytes straight off the escaped wire span instead of via this UTF-8 string — see PERF_PLAN.
fn latin1_to_bytes(s: &str) -> Result<Vec<u8>> {
    let mut out = Vec::with_capacity(s.len());
    for c in s.chars() {
        let cp = c as u32;
        if cp > 0xFF {
            bail!("codepoint U+{cp:04X} > 0xFF in latin-1 gzip stream");
        }
        out.push(cp as u8);
    }
    Ok(out)
}

fn bytes_to_latin1(bytes: &[u8]) -> String {
    // Exact presize: one two-byte UTF-8 sequence per byte >= 0x80 (the count pass vectorizes).
    let extra = bytes.iter().filter(|&&b| b >= 0x80).count();
    let mut out = String::with_capacity(bytes.len() + extra);
    for &b in bytes {
        out.push(b as char);
    }
    out
}

/// Gunzip a latin-1-encoded `cv` string into raw JSON bytes, size-capped (the gzip codec rejects
/// streams whose footer claims more than its 256 MB bomb cap).
///
/// NOT depth-guarded: the byte walk that consumes this first bounds its own recursion (and copies
/// unwalked spans iteratively), so the whole-buffer depth scan — profiled at ~6% of the pipeline —
/// only runs where recursion actually happens, in front of the parse fallbacks below. This mirrors
/// the uncompressed stream path, whose all-walked case pays no depth scan either.
fn decompress_string(s: &str) -> Result<Vec<u8>> {
    let raw = latin1_to_bytes(s)?;
    gzip::gunzip(&raw).context("gunzip cv data")
}

fn compress_bytes(json: &[u8]) -> Result<String> {
    Ok(bytes_to_latin1(&gzip::gzip(json).context("gzip cv payload")?))
}

fn compress_value(value: &Value<'_>) -> Result<String> {
    compress_bytes(value.encode().as_bytes())
}

/// Scrub a `cv`-compressed FullSnapshot `data` value (a gzipped latin-1 string) in place. Returns
/// whether it changed. The caller has already checked the value is a string; non-string data routes
/// through the plain scrub instead.
pub fn scrub_compressed_full_snapshot(ctx: &Ctx<'_>, data: &mut Value<'_>) -> Result<bool> {
    let Value::String(s) = &*data else {
        bail!("compressed full snapshot data is not a string");
    };
    let mut scratch = decompress_string(s)?;
    // Byte-walk the decompressed payload first: it reuses the same walkers as the uncompressed
    // stream path, whose semantics the stream/tree differential suite pins. On decline (escaped or
    // duplicate keys, unexpected shapes, over-deep nesting) fall through to the parse below.
    let mut walked = Vec::with_capacity(scratch.len() + 64);
    match bytewalk::scrub_cv_snapshot(ctx, &scratch, &mut walked) {
        Some(false) => return Ok(false),
        Some(true) => {
            *data = string_value(compress_bytes(&walked)?);
            return Ok(true);
        }
        None => {}
    }
    // The parse and the tree scrub recurse per level where the walk above self-guarded, so an
    // over-deep payload must fail closed here — a stack overflow aborts the worker process, which
    // catch_unwind cannot contain.
    reject_if_too_deep(&scratch, "cv payload")?;
    // The decompressed payload lives in its own scratch buffer; the parsed tree borrows it and is
    // dropped (re-serialized) before anything is written back.
    let mut payload = parse_untrusted(&mut scratch).context("parse cv payload")?;
    if !scrub_full_snapshot(ctx, &mut payload) {
        return Ok(false);
    }
    let recompressed = compress_value(&payload)?;
    *data = string_value(recompressed);
    Ok(true)
}

// Per-sub-field scrub dispatch for the synthetic mutation pieces.
fn scrub_sub(ctx: &Ctx<'_>, sub_key: &str, arr: &mut Vec<Value<'_>>) -> bool {
    match sub_key {
        "texts" => scrub_mutation_texts(ctx, arr),
        "attributes" => scrub_mutation_attributes(ctx, arr),
        "adds" => scrub_mutation_adds(ctx, arr),
        _ => unreachable!("unknown cv mutation sub-field"),
    }
}

/// Scrub a `cv`-compressed Mutation `data` object in place. Returns whether it changed.
///
/// Sub-fields are gzipped strings on the wire but may arrive as plain arrays; handle both. Plain
/// arrays are scrubbed in place inside the event tree. Gzipped sub-fields are each decompressed
/// into their own scratch buffer, byte-walked (parse fallback on decline), and re-compressed only
/// when that sub-field itself changed; untouched sub-fields keep their original gzip string
/// verbatim. (The TS pipeline re-compresses every sub-field once any changed — but recompressing
/// an unchanged field re-encodes identical content, so keeping the original bytes produces the
/// same payload after gunzip while skipping the most expensive leg, level-6 recompression.)
pub fn scrub_compressed_mutation(ctx: &Ctx<'_>, data: &mut Object<'_>) -> Result<bool> {
    const KEYS: [(&str, bytewalk::CvMutationField); 3] = [
        ("texts", bytewalk::CvMutationField::Texts),
        ("attributes", bytewalk::CvMutationField::Attributes),
        ("adds", bytewalk::CvMutationField::Adds),
    ];

    let mut changed = false;
    // Changed gzipped sub-fields: (key, scrubbed JSON bytes) to re-compress and write back below.
    let mut recompress: Vec<(&'static str, Vec<u8>)> = Vec::new();

    for (sub_key, field) in KEYS {
        match data.get_mut(sub_key) {
            None => {}                                   // absent -> leave absent
            Some(Value::Static(StaticNode::Null)) => {}  // null -> keep verbatim
            Some(Value::String(s)) if s.is_empty() => {} // empty string -> keep verbatim
            Some(Value::String(s)) => {
                let mut scratch = decompress_string(s)?;
                let mut walked = Vec::with_capacity(scratch.len() + 64);
                match bytewalk::scrub_cv_mutation_field(ctx, field, &scratch, &mut walked) {
                    Some(false) => {}
                    Some(true) => {
                        changed = true;
                        recompress.push((sub_key, walked));
                    }
                    None => {
                        // As in the full-snapshot fallback: the parse recurses, the walk didn't.
                        reject_if_too_deep(&scratch, "cv mutation sub-field")?;
                        let mut decoded =
                            parse_untrusted(&mut scratch).context("parse cv mutation sub-field")?;
                        let Some(arr) = as_array_mut(&mut decoded) else {
                            // Fail closed: a decodable-but-non-array sub-field is malformed.
                            bail!("cv mutation sub-field did not decode to an array");
                        };
                        if scrub_sub(ctx, sub_key, arr) {
                            changed = true;
                            recompress.push((sub_key, decoded.encode().into_bytes()));
                        }
                    }
                }
            }
            Some(v @ Value::Array(_)) => {
                let arr = as_array_mut(v).expect("matched array");
                changed |= scrub_sub(ctx, sub_key, arr);
            }
            Some(_) => bail!("cv mutation sub-field is neither a gzipped string nor an array"),
        }
    }

    for (sub_key, json) in recompress {
        data.insert(key(sub_key), string_value(compress_bytes(&json)?));
    }

    Ok(changed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::allow_lists::AllowLists;
    use crate::context::Ctx;
    use crate::json::{as_array, as_object, as_str};
    use std::borrow::Cow;

    fn parse(json: &'static [u8]) -> Value<'static> {
        simd_json::to_borrowed_value(Vec::leak(json.to_vec())).unwrap()
    }

    fn compress_json(json: &[u8]) -> String {
        compress_bytes(json).unwrap()
    }

    fn decompress_value(s: &str) -> serde_json::Value {
        serde_json::from_slice(&decompress_string(s).unwrap()).unwrap()
    }

    #[test]
    fn compressed_mutation_scrubs_then_re_gzips_and_preserves_subfields() {
        let allow = AllowLists::new(["keep"], Vec::<String>::new());
        let texts_gz = compress_json(br#"[{"id":5,"value":"keep secret"}]"#);

        let mut data = Object::default();
        data.insert(Cow::Borrowed("source"), Value::Static(StaticNode::U64(0)));
        data.insert(Cow::Borrowed("texts"), string_value(texts_gz));

        let ctx = Ctx::new(&allow);
        let changed = scrub_compressed_mutation(&ctx, &mut data).unwrap();
        assert!(changed);

        // Still a gzipped string, and it round-trips to the scrubbed value.
        let out_gz = as_str(data.get("texts").unwrap()).unwrap();
        let decoded = decompress_value(out_gz);
        assert_eq!(decoded[0]["value"], "keep ******");
        // Absent sub-fields stay absent (not resurrected as empty).
        assert!(!data.contains_key("attributes"));
        assert!(!data.contains_key("adds"));
    }

    #[test]
    fn compressed_full_snapshot_round_trips_and_scrubs() {
        let allow = AllowLists::new(["keep"], Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let gz = compress_json(
            br#"{"node":{"type":0,"childNodes":[{"type":3,"textContent":"keep secret"}]},"initialOffset":{"top":0,"left":0}}"#,
        );
        let mut data = string_value(gz);

        assert!(scrub_compressed_full_snapshot(&ctx, &mut data).unwrap());

        let out_gz = as_str(&data).unwrap();
        let decoded = decompress_value(out_gz);
        assert_eq!(
            decoded["node"]["childNodes"][0]["textContent"],
            "keep ******"
        );
    }

    #[test]
    fn compressed_mutation_keeps_unchanged_subfields_byte_identical() {
        let allow = AllowLists::new(["keep"], Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let texts_gz = compress_json(br#"[{"id":5,"value":"keep secret"}]"#);
        // Nothing to scrub in `adds`: id-only node, no text/attributes.
        let adds_gz = compress_json(br#"[{"parentId":1,"nextId":null,"node":{"id":9,"type":2}}]"#);

        let mut data = Object::default();
        data.insert(Cow::Borrowed("source"), Value::Static(StaticNode::U64(0)));
        data.insert(Cow::Borrowed("texts"), string_value(texts_gz));
        data.insert(Cow::Borrowed("adds"), string_value(adds_gz.clone()));

        assert!(scrub_compressed_mutation(&ctx, &mut data).unwrap());

        let texts = decompress_value(as_str(data.get("texts").unwrap()).unwrap());
        assert_eq!(texts[0]["value"], "keep ******");
        // The untouched sub-field keeps its original gzip bytes — it is not re-compressed just
        // because a sibling changed.
        assert_eq!(as_str(data.get("adds").unwrap()).unwrap(), adds_gz);
    }

    #[test]
    fn compressed_mutation_with_escaped_keys_scrubs_via_parse_fallback() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        // The `value` key's first byte is a \u escape: the byte walker declines escaped keys,
        // so this only scrubs if the parse fallback still runs behind it.
        let texts_gz = compress_json(br#"[{"id":5,"\u0076alue":"topsecret stuff"}]"#);

        let mut data = Object::default();
        data.insert(Cow::Borrowed("source"), Value::Static(StaticNode::U64(0)));
        data.insert(Cow::Borrowed("texts"), string_value(texts_gz));

        assert!(scrub_compressed_mutation(&ctx, &mut data).unwrap());
        let texts = decompress_value(as_str(data.get("texts").unwrap()).unwrap());
        assert_eq!(texts[0]["value"], "********* *****");
    }

    #[test]
    fn compressed_full_snapshot_with_escaped_keys_scrubs_via_parse_fallback() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        // The `textContent` key's first byte is a \u escape (see the mutation fallback test
        // above).
        let gz = compress_json(
            br#"{"node":{"type":3,"\u0074extContent":"topsecret stuff"},"initialOffset":{"top":0,"left":0}}"#,
        );
        let mut data = string_value(gz);

        assert!(scrub_compressed_full_snapshot(&ctx, &mut data).unwrap());
        let decoded = decompress_value(as_str(&data).unwrap());
        assert_eq!(decoded["node"]["textContent"], "********* *****");
    }

    #[test]
    fn compressed_mutation_handles_a_plain_array_subfield() {
        let allow = AllowLists::new(["keep"], Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let mut data = Object::default();
        data.insert(Cow::Borrowed("source"), Value::Static(StaticNode::U64(0)));
        // Sub-field arrives as a plain array (not gzipped) — scrub in place, keep it an array.
        data.insert(
            Cow::Borrowed("texts"),
            parse(br#"[{"id":5,"value":"keep secret"}]"#),
        );

        assert!(scrub_compressed_mutation(&ctx, &mut data).unwrap());

        let texts = data.get("texts").unwrap();
        assert!(matches!(texts, Value::Array(_)), "stays a plain array");
        let value = as_str(
            as_object(&as_array(texts).unwrap()[0])
                .unwrap()
                .get("value")
                .unwrap(),
        )
        .unwrap();
        assert_eq!(value, "keep ******");
    }

    #[test]
    fn compressed_mutation_restores_null_and_empty_subfields() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let mut data = Object::default();
        data.insert(Cow::Borrowed("source"), Value::Static(StaticNode::U64(0)));
        data.insert(Cow::Borrowed("texts"), Value::Static(StaticNode::Null));
        data.insert(Cow::Borrowed("attributes"), string_value(String::new()));

        scrub_compressed_mutation(&ctx, &mut data).unwrap();

        assert!(matches!(
            data.get("texts"),
            Some(Value::Static(StaticNode::Null))
        ));
        assert_eq!(as_str(data.get("attributes").unwrap()).unwrap(), "");
    }

    #[test]
    fn compressed_mutation_fails_closed_on_non_array_subfield() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let mut data = Object::default();
        data.insert(Cow::Borrowed("source"), Value::Static(StaticNode::U64(0)));
        data.insert(
            Cow::Borrowed("texts"),
            string_value(compress_json(br#"{"a":1}"#)),
        );
        assert!(scrub_compressed_mutation(&ctx, &mut data).is_err());
    }

    #[test]
    fn compressed_payload_fails_closed_when_nested_too_deep() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        // A tiny gzip whose decompressed JSON nests past MAX_JSON_DEPTH must fail closed (Err), not
        // overflow the worker-thread stack — a stack overflow aborts the process, which catch_unwind
        // cannot contain, so it would bypass the fail-closed contract entirely. The payload is a valid,
        // balanced nested array: without the depth guard it parses fine and returns Ok(false), so this
        // test only passes because the guard rejects it up front.
        let n = crate::json::MAX_JSON_DEPTH + 10;
        let deep = format!("{}{}", "[".repeat(n), "]".repeat(n));
        let mut data = string_value(compress_json(deep.as_bytes()));
        assert!(scrub_compressed_full_snapshot(&ctx, &mut data).is_err());
    }

    #[test]
    fn compressed_mutation_fails_closed_on_non_latin1_stream() {
        let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
        let ctx = Ctx::new(&allow);
        let mut data = Object::default();
        data.insert(Cow::Borrowed("source"), Value::Static(StaticNode::U64(0)));
        // A codepoint > 0xFF can't be a latin-1 gzip byte — must fail closed, not silently pass.
        data.insert(
            Cow::Borrowed("texts"),
            string_value("\u{100}bad".to_string()),
        );
        assert!(scrub_compressed_mutation(&ctx, &mut data).is_err());
    }
}
