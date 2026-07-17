//! Session-replay anonymizer: PII-scrubs rrweb events for PostHog's ml-mirror pipelines.
//!
//! The scrubbers cover text/URL redaction, native image blur, and `cv` de/recompression. Behavior
//! is pinned by the shared JSON fixtures under `tests/fixtures/`, which both `tests/parity.rs` and
//! the Node addon's Jest suite (through `replay-anonymizer-node`) run against.
//!
//! The production surface is the byte-buffer pipeline in [`snapshot`]: the decompressed Kafka payload
//! goes in, ready-to-write JSONL block lines plus envelope/per-event metadata come out — this crate
//! owns the parse, the scrub, and the serialize.
//!
//! Scrubbing operates on untrusted input. The public entry points contain panics on pathological
//! payloads and convert them to errors (fail closed: the caller drops the message) — no
//! `catch_unwind` obligation on consumers. Caveat: under `panic = "abort"` the backstop cannot run
//! and a panic still kills the process; builds that must fail closed need `panic = "unwind"` (the
//! Node addon enforces this at compile time).
//!
//! # Supported API
//!
//! The stable crates.io surface is what this page documents: [`AllowLists`], [`Ctx`], the event
//! entry points ([`anonymize_message`], [`anonymize_event`], [`anonymize_line`] and friends), the
//! byte-buffer snapshot pipeline ([`anonymize_kafka_payload`] and friends), and the rrweb routing
//! constants in [`event`]. Everything `#[doc(hidden)]` stays `pub` only for this workspace (the
//! Node addon, the parity tests) — it is internal and may change or disappear in any release.

pub mod allow_lists;
#[doc(hidden)]
pub mod assets;
#[doc(hidden)]
pub mod blur;
#[doc(hidden)]
pub mod bytewalk;
#[doc(hidden)]
pub mod canvas;
pub mod context;
#[doc(hidden)]
pub mod css;
#[doc(hidden)]
pub mod cv;
#[doc(hidden)]
pub mod dom;
pub mod event;
#[doc(hidden)]
pub mod gzip;
#[doc(hidden)]
pub mod json;
#[doc(hidden)]
pub mod scan;
pub mod snapshot;
#[doc(hidden)]
pub mod text;
mod unwind;
#[doc(hidden)]
pub mod url;
#[doc(hidden)]
pub mod value;

pub use allow_lists::AllowLists;
pub use context::Ctx;
pub use event::{
    anonymize_event, anonymize_event_str, anonymize_line, anonymize_line_with_ctx,
    anonymize_message,
};
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
