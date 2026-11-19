//! Data URI helpers, and the stand-ins an image becomes when the scrub lane cannot take it.

/// A 1x1 transparent PNG: what an image the scrub lane cannot take becomes.
pub const BLANK_PNG_BASE64: &str =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNgAAIAAAUAAen63NgAAAAASUVORK5CYII=";

pub fn blank_image_data_uri() -> String {
    format!("data:image/png;base64,{BLANK_PNG_BASE64}")
}

pub fn is_image_data_uri(s: &str) -> bool {
    s.starts_with("data:image/")
}

/// Split a `data:<mime>;...,<base64>` URI into (mime, base64). None if not a data URI.
pub fn split_data_uri(uri: &str) -> Option<(String, String)> {
    let rest = uri.strip_prefix("data:")?;
    let comma = rest.find(',')?;
    let mime = rest[..comma].split(';').next().unwrap_or("image/png");
    let mime = if mime.is_empty() { "image/png" } else { mime };
    Some((mime.to_string(), rest[comma + 1..].to_string()))
}

/// What an image the scrub lane cannot take is replaced with; chosen per occurrence.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ImageFallback {
    /// Blank 1x1 PNG (inline images, canvas frames, css).
    Blank,
    /// The media placeholder SVG (media `src`-style attributes).
    Placeholder,
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::Engine;

    #[test]
    fn the_blank_image_decodes_to_one_transparent_pixel() {
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(BLANK_PNG_BASE64)
            .unwrap();
        let image = image::load_from_memory(&bytes).unwrap().to_rgba8();
        assert_eq!(image.dimensions(), (1, 1));
        assert_eq!(image.get_pixel(0, 0).0[3], 0);
    }
}
