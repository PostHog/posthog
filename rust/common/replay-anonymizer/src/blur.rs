//! Downsample + blur media/canvas images — scene stays legible, faces/text don't.
//! Native Rust replacement for `anonymize/blur.ts` (which used `sharp`). Runs inline (synchronously);
//! output is never byte-identical to sharp, so tests assert structure (decodes to W x H PNG), not bytes.

use base64::Engine;
use image::{DynamicImage, GenericImageView, RgbaImage};

const DOWNSAMPLE_RATIO: f32 = 0.12;
const BLUR_SIGMA: f32 = 2.34;
const MAX_LONG_SIDE: f32 = 96.0;

// Bounds on decoding fully untrusted image bytes: a tiny compressed image can declare huge dimensions
// (a decompression bomb). Reject those to the blank/placeholder fallback rather than allocating GBs.
const MAX_IMAGE_SIDE: u32 = 16_384;
const MAX_IMAGE_ALLOC_BYTES: u64 = 256 * 1024 * 1024;

fn decode_limited(bytes: &[u8]) -> Option<DynamicImage> {
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(MAX_IMAGE_SIDE);
    limits.max_image_height = Some(MAX_IMAGE_SIDE);
    limits.max_alloc = Some(MAX_IMAGE_ALLOC_BYTES);
    let reader = image::ImageReader::new(std::io::Cursor::new(bytes))
        .with_guessed_format()
        .ok()?;
    let mut reader = reader;
    reader.limits(limits);
    reader.decode().ok()
}

/// A 1x1 transparent PNG: the fail-safe stand-in used when the real blur can't be produced.
pub const BLANK_PNG_BASE64: &str =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

pub fn blank_image_data_uri() -> String {
    format!("data:image/png;base64,{BLANK_PNG_BASE64}")
}

pub fn is_image_data_uri(s: &str) -> bool {
    s.starts_with("data:image/")
}

/// Scale to DOWNSAMPLE_RATIO, but never leave the long side above MAX_LONG_SIDE; floored at 1px.
fn target_dims(width: u32, height: u32) -> (u32, u32) {
    let w = width.max(1) as f32;
    let h = height.max(1) as f32;
    let scale = DOWNSAMPLE_RATIO.min(MAX_LONG_SIDE / w.max(h));
    (
        ((w * scale).round() as u32).max(1),
        ((h * scale).round() as u32).max(1),
    )
}

fn encode_png_base64(img: &DynamicImage) -> Option<String> {
    let mut buf = Vec::new();
    img.write_to(&mut std::io::Cursor::new(&mut buf), image::ImageFormat::Png)
        .ok()?;
    Some(base64::engine::general_purpose::STANDARD.encode(&buf))
}

/// Downsample a base64 image data URI to a fraction of its size + a blur, as a PNG; None if it can't.
pub fn blur_image_data_uri(s: &str) -> Option<String> {
    let rest = s.strip_prefix("data:")?;
    let (meta, payload) = rest.split_once(',')?;
    if !meta.contains("base64") || !meta.starts_with("image/") {
        return None;
    }
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(payload.as_bytes())
        .ok()?;
    let img = decode_limited(&bytes)?; // can't read the header / exceeds limits -> None
    let (w, h) = img.dimensions();
    let (tw, th) = target_dims(w, h);
    // Downsample (fit: fill) then Gaussian blur, mirroring the TS pipeline order.
    let out = img
        .resize_exact(tw, th, image::imageops::FilterType::Triangle)
        .blur(BLUR_SIGMA);
    let encoded = encode_png_base64(&out)?;
    Some(format!("data:image/png;base64,{encoded}"))
}

/// De-identify raw RGBA pixels: downsample + blur, then scale back to the original W x H, preserving
/// byte length (`4*W*H`) so it slots back into a `putImageData` ImageData. None if it can't.
pub fn pixelate_raw_rgba(base64_pixels: &str, width: u32, height: u32) -> Option<String> {
    let buf = base64::engine::general_purpose::STANDARD
        .decode(base64_pixels.as_bytes())
        .ok()?;
    let expected = (width as usize) * (height as usize) * 4;
    if buf.len() != expected {
        return None;
    }
    let img = RgbaImage::from_raw(width, height, buf)?;
    let dynamic = DynamicImage::ImageRgba8(img);
    let (sw, sh) = target_dims(width, height);
    let small = dynamic
        .resize_exact(sw, sh, image::imageops::FilterType::Triangle)
        .blur(BLUR_SIGMA);
    let restored = small.resize_exact(width, height, image::imageops::FilterType::Triangle);
    let out = restored.to_rgba8().into_raw();
    if out.len() != expected {
        return None;
    }
    Some(base64::engine::general_purpose::STANDARD.encode(&out))
}

/// Split a `data:<mime>;...,<base64>` URI into (mime, base64). None if not a data URI.
pub fn split_data_uri(uri: &str) -> Option<(String, String)> {
    let rest = uri.strip_prefix("data:")?;
    let comma = rest.find(',')?;
    let mime = rest[..comma].split(';').next().unwrap_or("image/png");
    let mime = if mime.is_empty() { "image/png" } else { mime };
    Some((mime.to_string(), rest[comma + 1..].to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::GenericImageView;

    fn png_data_uri(w: u32, h: u32) -> String {
        let img = image::DynamicImage::ImageRgba8(image::RgbaImage::from_pixel(
            w,
            h,
            image::Rgba([120, 30, 200, 255]),
        ));
        let mut buf = Vec::new();
        img.write_to(&mut std::io::Cursor::new(&mut buf), image::ImageFormat::Png)
            .unwrap();
        format!(
            "data:image/png;base64,{}",
            base64::engine::general_purpose::STANDARD.encode(&buf)
        )
    }

    #[test]
    fn blur_downsamples_to_target_dims_as_png() {
        let uri = png_data_uri(100, 50);
        let out = blur_image_data_uri(&uri).expect("blur should succeed for a valid png");
        assert!(out.starts_with("data:image/png;base64,"));
        let (_, b64) = split_data_uri(&out).unwrap();
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(&b64)
            .unwrap();
        let decoded = image::load_from_memory(&bytes).unwrap();
        // target_dims(100, 50) with ratio 0.12 -> (12, 6).
        assert_eq!(decoded.dimensions(), (12, 6));
    }

    #[test]
    fn blur_rejects_non_image_data_uri() {
        assert!(blur_image_data_uri("data:text/plain;base64,aGVsbG8=").is_none());
        assert!(blur_image_data_uri("not a data uri").is_none());
    }

    #[test]
    fn pixelate_preserves_rgba_byte_length() {
        let (w, h) = (8u32, 8u32);
        let raw = vec![200u8; (w * h * 4) as usize];
        let b64 = base64::engine::general_purpose::STANDARD.encode(&raw);
        let out = pixelate_raw_rgba(&b64, w, h).expect("pixelate should succeed");
        let out_bytes = base64::engine::general_purpose::STANDARD
            .decode(&out)
            .unwrap();
        assert_eq!(out_bytes.len(), raw.len());
    }

    #[test]
    fn pixelate_rejects_wrong_length() {
        let b64 = base64::engine::general_purpose::STANDARD.encode([0u8; 10]);
        assert!(pixelate_raw_rgba(&b64, 8, 8).is_none());
    }
}
