//! Canvas mutations: the `ImageBitmap(Blob(ArrayBuffer))` frames of posthog-js, and the buffers, `ImageData` and pixel arrays of rrweb's command recorder.
//! The data URI scan reads an `HTMLImageElement` `src`, and a remote `src` holds no image bytes.

use crate::bytescan::{self as scan, Span};

const INCREMENTAL_SNAPSHOT: u8 = 3;
const CANVAS_MUTATION: u8 = 9;
/// Typed arrays whose numbers can be pixels, as in `ImageData` or WebGL's `texImage2D`: the set the text scrub drops.
const PIXEL_ARRAYS: &[&str] = &["Uint8Array", "Uint8ClampedArray"];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CanvasImage {
    Base64(Span),
    Pixels(Span),
}

impl CanvasImage {
    pub fn span(self) -> Span {
        match self {
            CanvasImage::Base64(span) | CanvasImage::Pixels(span) => span,
        }
    }
}

fn is_text(bytes: &[u8], span: Span, text: &str) -> bool {
    scan::is_string(bytes, span) && scan::unescape(bytes, span).is_ok_and(|v| v == text)
}

fn is_container(bytes: &[u8], span: Span) -> bool {
    scan::is_array(bytes, span) || scan::is_object(bytes, span)
}

/// In byte order. The walk keeps its own stack, so no depth of nested arguments can overflow the call stack.
pub fn canvas_images(
    bytes: &[u8],
    kind: Option<u8>,
    source: Option<u8>,
    data: Span,
) -> Vec<CanvasImage> {
    let mut images = Vec::new();
    if kind != Some(INCREMENTAL_SNAPSHOT) || source != Some(CANVAS_MUTATION) {
        return images;
    }
    let mut values = vec![data];
    while let Some(value) = values.pop() {
        if scan::is_array(bytes, value) {
            values.extend(
                scan::array_items(bytes, value)
                    .into_iter()
                    .flatten()
                    .flatten()
                    .filter(|&item| is_container(bytes, item)),
            );
        } else if scan::is_object(bytes, value) {
            visit_object(bytes, value, &mut images, &mut values);
        }
    }
    images.sort_unstable_by_key(|image| image.span().0);
    images
}

fn visit_object(bytes: &[u8], object: Span, images: &mut Vec<CanvasImage>, values: &mut Vec<Span>) {
    let entries: Vec<scan::Entry> = scan::object_entries(bytes, object)
        .into_iter()
        .flatten()
        .flatten()
        .collect();
    // Each copy of a repeated `rr_type` counts, so the walk covers the one the player reads.
    let has_type = |names: &[&str]| {
        entries.iter().any(|entry| {
            &bytes[entry.key.0..entry.key.1] == b"rr_type"
                && names.iter().any(|name| is_text(bytes, entry.value, name))
        })
    };
    let image_data = has_type(&["ImageData"]);
    let pixel_array = has_type(PIXEL_ARRAYS);
    for entry in &entries {
        match &bytes[entry.key.0..entry.key.1] {
            b"base64" if scan::is_string(bytes, entry.value) => {
                images.push(CanvasImage::Base64(entry.value))
            }
            b"args" if (image_data || pixel_array) && scan::is_array(bytes, entry.value) => {
                let mut args = scan::array_items(bytes, entry.value)
                    .into_iter()
                    .flatten()
                    .flatten();
                if let Some(first) = args.next() {
                    if scan::is_array(bytes, first) || (image_data && scan::is_object(bytes, first))
                    {
                        images.push(CanvasImage::Pixels(first));
                    } else if is_container(bytes, first) {
                        values.push(first);
                    }
                }
                values.extend(args.filter(|&arg| is_container(bytes, arg)));
            }
            _ if is_container(bytes, entry.value) => values.push(entry.value),
            _ => {}
        }
    }
}
