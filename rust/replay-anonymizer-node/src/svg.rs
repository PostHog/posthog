//! The renderer has no text or raster-image support and every nested image reference is refused, so
//! the PNG holds only shapes and nothing beyond the document is read.

use posthog_replay_anonymizer::collect::DROP_SVG;
use posthog_replay_anonymizer::svg::{check_render_budget, MAX_SVG_BYTES};
use resvg::{tiny_skia, usvg};

const MIN_RASTER_SIDE: f32 = 256.0;
const MAX_RASTER_SIDE: f32 = 512.0;
pub const DROP_SVG_TOO_LARGE: &str = "image_svg_too_large";

pub fn rasterize_svg(document: &[u8]) -> Result<Vec<u8>, &'static str> {
    if document.len() > MAX_SVG_BYTES {
        return Err(DROP_SVG_TOO_LARGE);
    }
    check_render_budget(document)?;
    let options = usvg::Options {
        image_href_resolver: usvg::ImageHrefResolver {
            resolve_data: Box::new(|_, _, _| None),
            resolve_string: Box::new(|_, _| None),
        },
        ..usvg::Options::default()
    };
    let tree = usvg::Tree::from_data(document, &options).map_err(|_| DROP_SVG)?;
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

    fn png_dims(png: &[u8]) -> (u32, u32) {
        assert!(png.starts_with(b"\x89PNG"), "not a png");
        let be = |i: usize| u32::from_be_bytes(png[i..i + 4].try_into().unwrap());
        (be(16), be(20))
    }

    fn decode(png: &[u8]) -> Vec<[u8; 4]> {
        let pixmap = tiny_skia::Pixmap::decode_png(png).unwrap();
        pixmap
            .data()
            .chunks_exact(4)
            .map(|p| [p[0], p[1], p[2], p[3]])
            .collect()
    }

    #[test]
    fn renders_shapes_at_a_bounded_size() {
        let square = "<svg xmlns='http://www.w3.org/2000/svg' width='16' height='8'><rect width='16' height='8' fill='red'/></svg>";
        let png = rasterize_svg(square.as_bytes()).expect("renders");
        assert_eq!(png_dims(&png), (256, 128));
        assert!(decode(&png).iter().all(|p| *p == [255, 0, 0, 255]));
        let huge = "<svg xmlns='http://www.w3.org/2000/svg' width='100000' height='50000'/>";
        assert_eq!(
            png_dims(&rasterize_svg(huge.as_bytes()).unwrap()),
            (512, 256)
        );
    }

    #[test]
    fn draws_no_text_and_reads_no_files() {
        let text = "<svg xmlns='http://www.w3.org/2000/svg' width='64' height='64'><text x='0' y='32' font-size='32'>secret</text></svg>";
        let file = "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' width='64' height='64'><image width='64' height='64' xlink:href='/etc/hosts'/></svg>";
        for doc in [text, file] {
            let png = rasterize_svg(doc.as_bytes()).unwrap();
            assert!(
                decode(&png).iter().all(|p| p[3] == 0),
                "nothing drawn: {doc}"
            );
        }
    }

    #[test]
    fn refuses_what_the_lane_would_refuse() {
        assert_eq!(rasterize_svg(b"not svg"), Err(DROP_SVG));
        let mut big = b"<svg xmlns='http://www.w3.org/2000/svg'>".to_vec();
        big.resize(MAX_SVG_BYTES + 1, b' ');
        assert_eq!(rasterize_svg(&big), Err(DROP_SVG_TOO_LARGE));
    }
}
