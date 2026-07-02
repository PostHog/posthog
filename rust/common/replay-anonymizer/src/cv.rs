//! Decode/scrub/re-encode per-event `cv` compression (gzip stored as latin-1 codepoints).
//! Mirrors `anonymize/cv.ts`.

use std::io::{Read, Write};

use anyhow::{bail, Context, Result};
use flate2::read::GzDecoder;
use flate2::write::GzEncoder;
use flate2::Compression;
use simd_json::prelude::Writable;
use simd_json::value::owned::Object;
use simd_json::{OwnedValue, StaticNode};

use crate::allow_lists::AllowLists;
use crate::dom::{scrub_full_snapshot, scrub_mutation};
use crate::json::as_object_mut;

/// PostHog wire format: each gzip byte stored as its U+00XX codepoint (latin-1).
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
    bytes.iter().map(|&b| b as char).collect()
}

// Cap decompressed `cv` size so a gzip bomb can't OOM the worker thread.
const MAX_DECOMPRESSED_BYTES: u64 = 256 * 1024 * 1024;

fn decompress_string(s: &str) -> Result<OwnedValue> {
    let raw = latin1_to_bytes(s)?;
    let mut json = Vec::new();
    GzDecoder::new(&raw[..])
        .take(MAX_DECOMPRESSED_BYTES + 1)
        .read_to_end(&mut json)
        .context("gunzip cv data")?;
    if json.len() as u64 > MAX_DECOMPRESSED_BYTES {
        bail!("cv payload decompresses beyond {MAX_DECOMPRESSED_BYTES} bytes");
    }
    let value = simd_json::to_owned_value(&mut json).context("parse cv payload")?;
    Ok(value)
}

fn compress_to_string(value: &OwnedValue) -> Result<String> {
    let json = value.encode();
    let mut gz = GzEncoder::new(Vec::new(), Compression::default());
    gz.write_all(json.as_bytes()).context("gzip cv payload")?;
    let zipped = gz.finish().context("finish gzip")?;
    Ok(bytes_to_latin1(&zipped))
}

/// Scrub a `cv`-compressed FullSnapshot event in place. Returns whether it changed.
pub fn scrub_compressed_full_snapshot(allow: &AllowLists, event: &mut Object) -> Result<bool> {
    match event.get("data") {
        Some(OwnedValue::String(s)) => {
            let s = s.clone();
            let mut payload = decompress_string(&s)?;
            if !scrub_full_snapshot(allow, &mut payload) {
                return Ok(false);
            }
            event.insert(
                "data".to_string(),
                OwnedValue::String(compress_to_string(&payload)?),
            );
            Ok(true)
        }
        Some(_) => {
            // Not actually whole-blob compressed — scrub as a plain object.
            let data = event.get_mut("data").unwrap();
            Ok(scrub_full_snapshot(allow, data))
        }
        None => Ok(false),
    }
}

enum Sub {
    Skip,                // absent -> leave absent
    Restore(OwnedValue), // null / empty-string -> put back verbatim
    Array,               // plain array -> scrubbed in place
    Compressed(String),  // gzipped string -> recompress on change, else keep original
}

/// Scrub a `cv`-compressed Mutation event in place. Returns whether it changed.
pub fn scrub_compressed_mutation(allow: &AllowLists, event: &mut Object) -> Result<bool> {
    let Some(data) = event.get_mut("data").and_then(as_object_mut) else {
        return Ok(false);
    };

    // Sub-fields are gzipped strings on the wire but may arrive as plain arrays; handle both. We move
    // each out of `data`, scrub via a synthetic mutation, then always put a value back (even when
    // nothing changed) so no sub-field is dropped.
    let keys = ["texts", "attributes", "adds"];
    let mut synthetic = Object::default();
    let mut plan: Vec<Sub> = Vec::with_capacity(keys.len());

    for key in keys {
        let sub = match data.remove(key) {
            None => Sub::Skip,
            Some(v @ OwnedValue::Static(StaticNode::Null)) => Sub::Restore(v),
            Some(OwnedValue::String(s)) if s.is_empty() => Sub::Restore(OwnedValue::String(s)),
            Some(OwnedValue::String(s)) => {
                let decoded = decompress_string(&s)?;
                if !matches!(decoded, OwnedValue::Array(_)) {
                    // Fail closed: a decodable-but-non-array sub-field is malformed.
                    bail!("cv mutation sub-field did not decode to an array");
                }
                synthetic.insert(key.to_string(), decoded);
                Sub::Compressed(s)
            }
            Some(arr @ OwnedValue::Array(_)) => {
                synthetic.insert(key.to_string(), arr);
                Sub::Array
            }
            Some(_) => bail!("cv mutation sub-field is neither a gzipped string nor an array"),
        };
        plan.push(sub);
    }

    let mut synthetic_val = OwnedValue::Object(Box::new(synthetic));
    let changed = scrub_mutation(allow, &mut synthetic_val);
    let synthetic = as_object_mut(&mut synthetic_val).expect("synthetic is an object");

    // event.data was invalidated by the reborrow above; re-fetch it.
    let data = event.get_mut("data").and_then(as_object_mut).unwrap();
    for (key, sub) in keys.iter().zip(plan) {
        match sub {
            Sub::Skip => {}
            Sub::Restore(v) => {
                data.insert(key.to_string(), v);
            }
            Sub::Array => {
                let arr = synthetic
                    .remove(*key)
                    .unwrap_or(OwnedValue::Array(Box::default()));
                data.insert(key.to_string(), arr);
            }
            Sub::Compressed(orig) => {
                let arr = synthetic
                    .remove(*key)
                    .unwrap_or(OwnedValue::Array(Box::default()));
                if changed {
                    data.insert(
                        key.to_string(),
                        OwnedValue::String(compress_to_string(&arr)?),
                    );
                } else {
                    // Nothing changed — keep the original bytes rather than re-gzipping.
                    data.insert(key.to_string(), OwnedValue::String(orig));
                }
            }
        }
    }

    Ok(changed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json::{as_array, as_object, as_str};

    #[test]
    fn compressed_mutation_scrubs_then_re_gzips_and_preserves_subfields() {
        let allow = AllowLists::new(["keep"], Vec::<String>::new());
        let texts: OwnedValue =
            simd_json::to_owned_value(&mut br#"[{"id":5,"value":"keep secret"}]"#.to_vec())
                .unwrap();
        let texts_gz = compress_to_string(&texts).unwrap();

        let mut data = Object::default();
        data.insert("source".to_string(), OwnedValue::Static(StaticNode::U64(0)));
        data.insert("texts".to_string(), OwnedValue::String(texts_gz));
        let mut event = Object::default();
        event.insert("data".to_string(), OwnedValue::Object(Box::new(data)));

        let changed = scrub_compressed_mutation(&allow, &mut event).unwrap();
        assert!(changed);

        let data = as_object(event.get("data").unwrap()).unwrap();
        // Still a gzipped string, and it round-trips to the scrubbed value.
        let out_gz = as_str(data.get("texts").unwrap()).unwrap();
        let decoded = decompress_string(out_gz).unwrap();
        let value = as_str(
            as_object(&as_array(&decoded).unwrap()[0])
                .unwrap()
                .get("value")
                .unwrap(),
        )
        .unwrap();
        assert_eq!(value, "keep ******");
        // Absent sub-fields stay absent (not resurrected as empty).
        assert!(!data.contains_key("attributes"));
        assert!(!data.contains_key("adds"));
    }
}
