//! Rasterizes SVG data URIs for the image scrub. The renderer has no text or raster-image support and
//! every nested image reference is refused, so the PNG holds only shapes and nothing is read from disk.

use base64::Engine;
use resvg::{tiny_skia, usvg};

use crate::collect::{DROP_SVG, DROP_TOO_LARGE};

/// Long-side bounds of the rendered PNG. Vector art loses nothing at either end, and the scrub
/// stores far smaller than the upper bound.
const MIN_RASTER_SIDE: f32 = 256.0;
const MAX_RASTER_SIDE: f32 = 1024.0;

pub(crate) fn rasterize_svg_data_uri(
    uri: &str,
    max_input_bytes: usize,
) -> Result<Vec<u8>, &'static str> {
    let (meta, payload) = uri
        .strip_prefix("data:")
        .and_then(|rest| rest.split_once(','))
        .ok_or(DROP_SVG)?;
    if payload.len() > max_input_bytes.saturating_mul(3) {
        return Err(DROP_TOO_LARGE);
    }
    let document: Vec<u8> = if meta.to_ascii_lowercase().contains(";base64") {
        base64::engine::general_purpose::STANDARD
            .decode(payload.as_bytes())
            .map_err(|_| DROP_SVG)?
    } else {
        percent_encoding::percent_decode_str(payload).collect()
    };
    if document.len() > max_input_bytes {
        return Err(DROP_TOO_LARGE);
    }

    let options = usvg::Options {
        image_href_resolver: usvg::ImageHrefResolver {
            resolve_data: Box::new(|_, _, _| None),
            resolve_string: Box::new(|_, _| None),
        },
        ..usvg::Options::default()
    };
    let tree = usvg::Tree::from_data(&document, &options).map_err(|_| DROP_SVG)?;
    let size = tree.size();
    let long = size.width().max(size.height());
    let scale = long.clamp(MIN_RASTER_SIDE, MAX_RASTER_SIDE) / long;
    let width = (size.width() * scale).ceil().max(1.0) as u32;
    let height = (size.height() * scale).ceil().max(1.0) as u32;
    let mut pixmap = tiny_skia::Pixmap::new(width, height).ok_or(DROP_SVG)?;
    resvg::render(
        &tree,
        tiny_skia::Transform::from_scale(scale, scale),
        &mut pixmap.as_mut(),
    );
    pixmap.encode_png().map_err(|_| DROP_SVG)
}

#[cfg(test)]
mod tests {
    use super::*;

    const SQUARE: &str =
        "<svg xmlns='http://www.w3.org/2000/svg' width='16' height='8'><rect width='16' height='8' fill='red'/></svg>";

    fn png_dims(png: &[u8]) -> (u32, u32) {
        assert!(png.starts_with(b"\x89PNG"), "not a png");
        let be = |i: usize| u32::from_be_bytes(png[i..i + 4].try_into().unwrap());
        (be(16), be(20))
    }

    #[test]
    fn renders_base64_and_url_encoded_svg_to_png_at_a_bounded_size() {
        let b64 = base64::engine::general_purpose::STANDARD.encode(SQUARE);
        let encoded: String =
            percent_encoding::utf8_percent_encode(SQUARE, percent_encoding::NON_ALPHANUMERIC)
                .to_string();
        for uri in [
            format!("data:image/svg+xml;base64,{b64}"),
            format!("data:image/svg+xml;utf8,{encoded}"),
            format!("data:image/svg+xml;charset=utf-8,{SQUARE}"),
        ] {
            let png = rasterize_svg_data_uri(&uri, 1 << 20).expect("renders");
            assert_eq!(png_dims(&png), (256, 128), "{uri}");
        }
    }

    #[test]
    fn caps_the_long_side() {
        let huge = "<svg xmlns='http://www.w3.org/2000/svg' width='100000' height='50000'/>";
        let png =
            rasterize_svg_data_uri(&format!("data:image/svg+xml;utf8,{huge}"), 1 << 20).unwrap();
        assert_eq!(png_dims(&png), (1024, 512));
    }

    #[test]
    fn refuses_what_it_cannot_render_or_hold() {
        assert_eq!(
            rasterize_svg_data_uri("data:image/svg+xml;utf8,<not-svg", 1 << 20),
            Err(DROP_SVG)
        );
        assert_eq!(
            rasterize_svg_data_uri(&format!("data:image/svg+xml;utf8,{SQUARE}"), 16),
            Err(DROP_TOO_LARGE)
        );
    }

    #[test]
    fn draws_no_text_and_reads_no_files() {
        let text = "<svg xmlns='http://www.w3.org/2000/svg' width='64' height='64'><text x='0' y='32' font-size='32'>secret</text></svg>";
        let file = "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' width='64' height='64'><image width='64' height='64' xlink:href='/etc/hosts'/></svg>";
        for doc in [text, file] {
            let png =
                rasterize_svg_data_uri(&format!("data:image/svg+xml;utf8,{doc}"), 1 << 20).unwrap();
            let decoded = image::load_from_memory(&png).unwrap().to_rgba8();
            assert!(
                decoded.pixels().all(|p| p.0[3] == 0),
                "nothing drawn: {doc}"
            );
        }
    }
}
