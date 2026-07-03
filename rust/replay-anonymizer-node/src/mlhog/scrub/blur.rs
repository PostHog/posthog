// Copied verbatim from MLHog prep/labeling/src/scrub/blur.rs — bench-only.

//! Downsample + Gaussian blur images. Falls back to a blank PNG.

use base64::Engine;
use image::{imageops, ImageEncoder};

const DOWNSAMPLE_RATIO: f32 = 0.12;
const BLUR_SIGMA: f32 = 2.34;
const MAX_LONG_SIDE: f32 = 96.0;

pub const BLANK_PNG_BASE64: &str =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

pub fn blank_image_data_uri() -> String {
    format!("data:image/png;base64,{BLANK_PNG_BASE64}")
}

pub fn is_image_data_uri(s: &str) -> bool {
    s.starts_with("data:image/")
}

fn target_dims(width: u32, height: u32) -> (u32, u32) {
    let w = width.max(1) as f32;
    let h = height.max(1) as f32;
    let scale = DOWNSAMPLE_RATIO.min(MAX_LONG_SIDE / w.max(h));
    let tw = ((w * scale).round() as u32).max(1);
    let th = ((h * scale).round() as u32).max(1);
    (tw, th)
}

pub fn blur_image_data_uri(s: &str) -> Option<String> {
    let rest = s.strip_prefix("data:")?;
    let (meta, payload) = rest.split_once(',')?;
    if !meta.contains("base64") || !meta.starts_with("image/") {
        return None;
    }
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(payload.as_bytes())
        .ok()?;
    let img = image::load_from_memory(&bytes).ok()?.to_rgba8();
    let (tw, th) = target_dims(img.width(), img.height());
    let small = imageops::resize(&img, tw, th, imageops::FilterType::Triangle);
    let blurred = imageops::blur(&small, BLUR_SIGMA);

    encode_png_data_uri(blurred.as_raw(), tw, th)
}

fn encode_png_data_uri(rgba: &[u8], w: u32, h: u32) -> Option<String> {
    let mut out = Vec::with_capacity(256);
    image::codecs::png::PngEncoder::new(&mut out)
        .write_image(rgba, w, h, image::ExtendedColorType::Rgba8)
        .ok()?;
    let encoded = base64::engine::general_purpose::STANDARD.encode(&out);
    let mut uri = String::with_capacity(22 + encoded.len());
    uri.push_str("data:image/png;base64,");
    uri.push_str(&encoded);
    Some(uri)
}

// Downsample+blur then scale back to W×H, keeping the 4·W·H byte length for a putImageData buffer.
pub fn pixelate_raw_rgba(rgba_base64: &str, width: u32, height: u32) -> Option<String> {
    let buf = base64::engine::general_purpose::STANDARD
        .decode(rgba_base64.as_bytes())
        .ok()?;
    let expected = (width as usize).checked_mul(height as usize)?.checked_mul(4)?;
    if buf.len() != expected {
        return None;
    }
    let img: image::RgbaImage = image::ImageBuffer::from_raw(width, height, buf)?;
    let (sw, sh) = target_dims(width, height);
    let small = imageops::blur(&imageops::resize(&img, sw, sh, imageops::FilterType::Triangle), BLUR_SIGMA);
    let back = imageops::resize(&small, width, height, imageops::FilterType::Triangle);
    let raw = back.as_raw();
    if raw.len() != expected {
        return None;
    }
    Some(base64::engine::general_purpose::STANDARD.encode(raw))
}
