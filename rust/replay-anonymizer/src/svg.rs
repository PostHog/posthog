//! The scrub renders an SVG under a deadline, because render cost is not bounded by document size.

use base64::Engine;

use crate::collect::{DROP_SVG, DROP_SVG_TOO_COMPLEX, DROP_TOO_LARGE};

pub const MAX_SVG_BYTES: usize = 256 * 1024;
const MAX_NODES: u32 = 2_000;
const MAX_DEPTH: usize = 32;
const MAX_USES: usize = 8;
const REFUSED_ELEMENTS: &[&str] = &["filter", "mask", "pattern", "foreignObject"];

fn refuses_effects(text: &str) -> bool {
    text.contains("filter") || text.contains("mask")
}

/// Refusing DTDs also rules out entity expansion.
pub fn check_render_budget(document: &[u8]) -> Result<(), &'static str> {
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
    check_render_budget(&document)?;
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
    fn refuses_what_it_cannot_parse_or_render_in_bounded_time() {
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
