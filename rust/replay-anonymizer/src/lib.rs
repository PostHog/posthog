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
//! Scrubbing operates on untrusted input and may panic on pathological payloads; callers that must
//! fail closed (drop the message rather than crash) should wrap calls in `catch_unwind` under
//! `panic = "unwind"`, as `replay-anonymizer-node` does.

pub mod allow_lists;
pub mod assets;
pub mod blur;
pub mod bytewalk;
pub mod canvas;
pub mod context;
pub mod css;
pub mod cv;
pub mod dom;
pub mod event;
pub mod gzip;
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
