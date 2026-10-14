//! Rasterizes SVG data URIs for the image scrub. The renderer has no text or raster-image support and
//! every nested image reference is refused, so the PNG holds only shapes and nothing is read from disk.

use base64::Engine;
use resvg::{tiny_skia, usvg};

use crate::collect::{DROP_SVG, DROP_SVG_TOO_COMPLEX, DROP_TOO_LARGE};

/// Long-side bounds of the rendered PNG. Vector art loses nothing at either end, and the scrub
/// stores far smaller than the upper bound.
const MIN_RASTER_SIDE: f32 = 256.0;
const MAX_RASTER_SIDE: f32 = 512.0;

// Rendering runs on the mirror's own threads with no time limit, and its cost grows with element count
// times area, multiplied by filters, masks and `<use>` fan-out. Icons and logos sit far inside these.
const MAX_SVG_BYTES: usize = 256 * 1024;
const MAX_NODES: u32 = 2_000;
const MAX_DEPTH: usize = 32;
const MAX_USES: usize = 8;
const REFUSED_ELEMENTS: &[&str] = &["filter", "mask", "pattern", "foreignObject"];

fn refuses_effects(text: &str) -> bool {
    text.contains("filter") || text.contains("mask")
}

/// Refuse a document whose render cost is not bounded by its size. DTDs are refused outright, which
/// also rules out entity expansion.
fn check_render_budget(document: &[u8]) -> Result<(), &'static str> {
    let text = std::str::from_utf8(document).map_err(|_| DROP_SVG)?;
    let options = roxmltree::ParsingOptions {
        allow_dtd: false,
        nodes_limit: MAX_NODES,
        ..roxmltree::ParsingOptions::default()
    };
    let parsed =
        roxmltree::Document::parse_with_options(text, options).map_err(|error| match error {
            roxmltree::Error::NodesLimitReached => DROP_SVG_TOO_COMPLEX,
            _ => DROP_SVG,
        })?;
    let mut uses = 0;
    for node in parsed.descendants().filter(|node| node.is_element()) {
        let name = node.tag_name().name();
        if node.ancestors().count() > MAX_DEPTH || REFUSED_ELEMENTS.contains(&name) {
            return Err(DROP_SVG_TOO_COMPLEX);
        }
        if name == "use" {
            uses += 1;
        }
        if name == "style" && node.text().is_some_and(refuses_effects) {
            return Err(DROP_SVG_TOO_COMPLEX);
        }
        let effect_attribute = node.attributes().any(|attribute| {
            matches!(attribute.name(), "filter" | "mask")
                || (attribute.name() == "style" && refuses_effects(attribute.value()))
        });
        if effect_attribute || uses > MAX_USES {
            return Err(DROP_SVG_TOO_COMPLEX);
        }
    }
    Ok(())
}

pub(crate) fn rasterize_svg_data_uri(
    uri: &str,
    max_input_bytes: usize,
) -> Result<Vec<u8>, &'static str> {
    let (meta, payload) = uri
        .strip_prefix("data:")
        .and_then(|rest| rest.split_once(','))
        .ok_or(DROP_SVG)?;
    let max_input_bytes = max_input_bytes.min(MAX_SVG_BYTES);
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
    check_render_budget(&document)?;

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
            let pixel = image::load_from_memory(&png)
                .unwrap()
                .to_rgba8()
                .get_pixel(128, 64)
                .0;
            assert_eq!(pixel, [255, 0, 0, 255], "the shape is drawn: {uri}");
        }
    }

    #[test]
    fn caps_the_long_side() {
        let huge = "<svg xmlns='http://www.w3.org/2000/svg' width='100000' height='50000'/>";
        let png =
            rasterize_svg_data_uri(&format!("data:image/svg+xml;utf8,{huge}"), 1 << 20).unwrap();
        assert_eq!(png_dims(&png), (512, 256));
    }

    #[test]
    fn refuses_what_it_cannot_render_or_hold() {
        let svg = |body: &str| {
            format!("<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'>{body}</svg>")
        };
        let nested = format!("{}<rect/>{}", "<g>".repeat(40), "</g>".repeat(40));
        let uses = "<rect id='r'/>".to_string() + &"<use href='#r'/>".repeat(9);
        let rects = "<rect/>".repeat(2_500);
        let cases = [
            ("not svg".to_string(), DROP_SVG),
            (
                format!("<!DOCTYPE svg [<!ENTITY a 'b'>]>{}", svg("&a;")),
                DROP_SVG,
            ),
            (
                svg("<filter id='f'/><rect filter='url(#f)'/>"),
                DROP_SVG_TOO_COMPLEX,
            ),
            (
                svg("<rect style='filter: blur(4px)'/>"),
                DROP_SVG_TOO_COMPLEX,
            ),
            (
                svg("<style>rect { mask: url(#m) }</style><rect/>"),
                DROP_SVG_TOO_COMPLEX,
            ),
            (svg(&nested), DROP_SVG_TOO_COMPLEX),
            (svg(&uses), DROP_SVG_TOO_COMPLEX),
            (svg(&rects), DROP_SVG_TOO_COMPLEX),
            (svg(&" ".repeat(MAX_SVG_BYTES)), DROP_TOO_LARGE),
        ];
        for (doc, reason) in cases {
            let uri = format!("data:image/svg+xml;utf8,{doc}");
            assert_eq!(
                rasterize_svg_data_uri(&uri, 1 << 30),
                Err(reason),
                "{}",
                &doc[..doc.len().min(80)]
            );
        }
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
