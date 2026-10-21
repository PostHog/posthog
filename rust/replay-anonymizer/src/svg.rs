//! The scrub parses and renders an SVG in a process it kills at a deadline, because neither cost is
//! bounded by document size. Only the bytes are checked here, so nothing here can be made slow.

use base64::Engine;

use crate::collect::{DROP_SVG, DROP_TOO_LARGE};

pub const MAX_SVG_BYTES: usize = 256 * 1024;

/// The scrub tells an SVG from a raster image by its leading `<`.
fn starts_with_markup(document: &[u8]) -> bool {
    let body = document.strip_prefix(b"\xef\xbb\xbf").unwrap_or(document);
    body.iter().find(|b| !b.is_ascii_whitespace()) == Some(&b'<')
}

pub(crate) fn svg_document(
    meta: &str,
    payload: &str,
    max_input_bytes: usize,
) -> Result<Vec<u8>, &'static str> {
    let max_input_bytes = max_input_bytes.min(MAX_SVG_BYTES);
    if payload.len() > max_input_bytes.saturating_mul(3) {
        return Err(DROP_TOO_LARGE);
    }
    let document: Vec<u8> = if meta.contains(";base64") {
        base64::engine::general_purpose::STANDARD
            .decode(payload.as_bytes())
            .map_err(|_| DROP_SVG)?
    } else {
        percent_encoding::percent_decode_str(payload).collect()
    };
    if document.len() > max_input_bytes {
        return Err(DROP_TOO_LARGE);
    }
    if !starts_with_markup(&document) {
        return Err(DROP_SVG);
    }
    Ok(document)
}
#[cfg(test)]
mod tests {
    use super::*;

    const SQUARE: &str =
        "<svg xmlns='http://www.w3.org/2000/svg' width='16' height='8'><rect width='16' height='8' fill='red'/></svg>";

    #[test]
    fn decodes_base64_and_url_encoded_documents() {
        let b64 = base64::engine::general_purpose::STANDARD.encode(SQUARE);
        let encoded: String =
            percent_encoding::utf8_percent_encode(SQUARE, percent_encoding::NON_ALPHANUMERIC)
                .to_string();
        for (meta, payload) in [
            ("image/svg+xml;base64", b64.as_str()),
            ("image/svg+xml;utf8", encoded.as_str()),
            ("image/svg+xml;charset=utf-8", SQUARE),
        ] {
            assert_eq!(
                svg_document(meta, payload, 1 << 20).as_deref(),
                Ok(SQUARE.as_bytes()),
                "{meta}"
            );
        }
    }

    #[test]
    fn refuses_what_the_scrub_would_not_take_as_svg() {
        let cases = [
            ("not svg".to_string(), DROP_SVG),
            (
                format!("<svg>{}</svg>", " ".repeat(MAX_SVG_BYTES)),
                DROP_TOO_LARGE,
            ),
        ];
        for (doc, reason) in cases {
            assert_eq!(
                svg_document("image/svg+xml;utf8", &doc, 1 << 30),
                Err(reason),
                "{}",
                &doc[..doc.len().min(80)]
            );
        }
        assert_eq!(
            svg_document("image/svg+xml;utf8", SQUARE, 16),
            Err(DROP_TOO_LARGE)
        );
    }
}
