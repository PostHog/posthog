//! Moves inline images out of a v4 block. Each base64 raster data URI becomes an `image:v4` reference, and its
//! decoded bytes go to the flush's image pack.
//!
//! The scan is one pass over the colons, for `data:image/` in any case. A data URI looks the same in an attribute, a CSS `url()`, a
//! `srcset` candidate or stylesheet text, so the scan needs no knowledge of where it sits. Every other byte is
//! copied as it is. Nothing here protects privacy, so an image the scan cannot take stays inline in the sealed block.

use std::borrow::Cow;
use std::collections::HashSet;

use base64::engine::general_purpose::STANDARD;
use base64::Engine;

use crate::refs::{image_ref, reference_hash};

/// The longest media type and parameters a taken data URI has before its comma. A raster type with parameters, such
/// as `image/png;charset=utf-8;base64`, fits. The bound keeps the scan linear.
const MAX_META: usize = 64;
const MAX_SUBTYPE: usize = 32;

#[derive(Debug, Clone, Copy)]
pub struct ImageLimits {
    pub max_image_bytes: usize,
    pub max_images: usize,
    pub max_total_bytes: usize,
}

impl Default for ImageLimits {
    /// The per-image and per-message caps of the v3 collector.
    fn default() -> Self {
        Self {
            max_image_bytes: 900 * 1024,
            max_images: 4096,
            max_total_bytes: 64 * 1024 * 1024,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Image {
    pub reference: String,
    pub mime: String,
    pub bytes: Vec<u8>,
}

/// Collects the images of one message. One sink per message keeps the caps per message, as in v3.
pub struct ImageSink<'k> {
    content_key: &'k [u8; 32],
    team_id: i64,
    key_month: &'k str,
    limits: ImageLimits,
    seen: HashSet<String>,
    total_bytes: usize,
    pub images: Vec<Image>,
    /// Images left inline: over a cap, not decodable, or not a supported raster type.
    pub left_inline: u32,
}

impl<'k> ImageSink<'k> {
    pub fn new(
        content_key: &'k [u8; 32],
        team_id: i64,
        key_month: &'k str,
        limits: ImageLimits,
    ) -> Self {
        Self {
            content_key,
            team_id,
            key_month,
            limits,
            seen: HashSet::new(),
            total_bytes: 0,
            images: Vec::new(),
            left_inline: 0,
        }
    }

    /// Takes a base64 image and returns its reference, with the checks and caps of v3 `ImageCollector::collect`.
    pub(crate) fn take(&mut self, mime: &str, payload: &[u8]) -> Option<String> {
        if payload.len() > self.limits.max_image_bytes.div_ceil(3) * 4 {
            return None;
        }
        let bytes = STANDARD.decode(payload).ok()?;
        // v3 refuses BMP and ISO-BMFF (AVIF, HEIC) bytes under any label.
        if bytes.len() > self.limits.max_image_bytes
            || bytes.starts_with(b"BM")
            || bytes.get(4..8) == Some(b"ftyp")
        {
            return None;
        }
        let reference = image_ref(
            self.team_id,
            self.key_month,
            &reference_hash(self.content_key, &bytes),
        );
        // An image repeated in one message is stored once and referenced at every place it appears, past the caps too.
        if self.seen.contains(&reference) {
            return Some(reference);
        }
        if self.images.len() >= self.limits.max_images
            || self.total_bytes + bytes.len() > self.limits.max_total_bytes
        {
            return None;
        }
        self.seen.insert(reference.clone());
        self.total_bytes += bytes.len();
        self.images.push(Image {
            reference: reference.clone(),
            mime: mime.to_owned(),
            bytes,
        });
        Some(reference)
    }
}

/// The media type of a raster subtype, or `None` for a type v3 does not collect. SVG stays inline on purpose.
fn raster_mime(subtype: &str) -> Option<String> {
    if subtype.starts_with("svg") || subtype.contains("bmp") || subtype.contains("avif") {
        return None;
    }
    if subtype.is_empty()
        || subtype.len() > MAX_SUBTYPE
        || !subtype
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'+' | b'-'))
    {
        return None;
    }
    Some(match subtype {
        "jpg" | "pjpeg" => "image/jpeg".to_owned(),
        _ => format!("image/{subtype}"),
    })
}

fn is_base64(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'+' | b'/' | b'=')
}

/// A srcset descriptor such as `2x` or `100w`, which may follow a data URI after a space. A word of that shape counts
/// only when a comma or the end of the string follows it, because wrapped base64 can end in such a word too.
fn is_descriptor(bytes: &[u8], start: usize) -> bool {
    let length = bytes[start..]
        .iter()
        .position(|&b| !is_base64(b))
        .unwrap_or(bytes.len() - start);
    let word = &bytes[start..start + length];
    let shaped = match word.split_last() {
        Some((unit, number)) => {
            matches!(unit, b'w' | b'x' | b'h')
                && !number.is_empty()
                && number.iter().all(|&b| b.is_ascii_digit() || b == b'.')
        }
        None => false,
    };
    let mut after = start + length;
    while bytes.get(after) == Some(&b' ') {
        after += 1;
    }
    shaped
        && match bytes.get(after) {
            None | Some(b',' | b'"') => true,
            Some(b'\\') => bytes.get(after + 1) == Some(&b'"'),
            Some(_) => false,
        }
}

/// Whether the payload may go on past the break at `end`. The run before the break is then only a prefix of the image,
/// so the caller leaves the URI inline. Line-wrapped base64 continues it, and so does an escape inside it: an escaped
/// slash (`\/` or `\u002F`), or a CSS escape such as `\2f `, which arrives with its backslash doubled. Only the `\"`
/// that closes a quoted CSS url ends it for sure.
fn continues_past(bytes: &[u8], end: usize) -> bool {
    let mut position = end;
    let mut line_break = false;
    loop {
        match bytes.get(position) {
            Some(b'\\') => match bytes.get(position + 1) {
                Some(b'"') => return false,
                Some(b'n' | b'r' | b't') => {
                    line_break = true;
                    position += 2;
                }
                _ => return true,
            },
            Some(b' ' | b'\t' | b'\n' | b'\r') => position += 1,
            Some(&byte) => {
                // Wrapped base64 breaks at a line break, so a descriptor counts only after plain spaces.
                return position > end
                    && is_base64(byte)
                    && (line_break || !is_descriptor(bytes, position));
            }
            None => return false,
        }
    }
}

enum DataUri {
    NotImage,
    Inline,
    /// The reference, and where the payload ends.
    Taken(String, usize),
}

/// Reads the data URI whose `data:` starts at `start`, with the rules of v3 `collectable_data_uri_bytes`: the media
/// type and `base64` in any case, and any parameters before the comma.
fn read_data_uri(bytes: &[u8], start: usize, sink: &mut ImageSink<'_>) -> DataUri {
    let meta_start = start + b"data:".len();
    let window = &bytes[meta_start..bytes.len().min(meta_start + MAX_META + 1)];
    if !window
        .get(..b"image/".len())
        .is_some_and(|prefix| prefix.eq_ignore_ascii_case(b"image/"))
    {
        return DataUri::NotImage;
    }
    // A quote or a backslash cannot be in the media type. A comma after one is outside the JSON string of the URI.
    let Some(comma) = window
        .iter()
        .position(|&b| matches!(b, b',' | b'"' | b'\\'))
        .filter(|&at| window[at] == b',')
    else {
        return DataUri::Inline;
    };
    let meta = String::from_utf8_lossy(&window[..comma]).to_ascii_lowercase();
    let media_type = meta.split(';').next().unwrap_or_default();
    let Some(mime) = raster_mime(&media_type["image/".len()..]).filter(|_| meta.contains("base64"))
    else {
        return DataUri::Inline;
    };
    let payload_start = meta_start + comma + 1;
    let end = bytes[payload_start..]
        .iter()
        .position(|&b| !is_base64(b))
        .map_or(bytes.len(), |length| payload_start + length);
    if continues_past(bytes, end) {
        return DataUri::Inline;
    }
    match sink.take(&mime, &bytes[payload_start..end]) {
        Some(reference) => DataUri::Taken(reference, end),
        None => DataUri::Inline,
    }
}

/// Replaces every inline raster image in `bytes` with its reference. Returns the input unchanged when it holds none.
pub fn extract_images<'b>(bytes: &'b [u8], sink: &mut ImageSink<'_>) -> Cow<'b, [u8]> {
    let mut out: Option<Vec<u8>> = None;
    let mut copied_to = 0;
    for colon in memchr::memchr_iter(b':', bytes) {
        let Some(start) = colon.checked_sub(b"data".len()) else {
            continue;
        };
        if start < copied_to
            || !bytes[start..colon].eq_ignore_ascii_case(b"data")
            || start
                .checked_sub(1)
                .is_some_and(|before| bytes[before].is_ascii_alphanumeric())
        {
            continue;
        }
        match read_data_uri(bytes, start, sink) {
            DataUri::NotImage => {}
            DataUri::Inline => sink.left_inline += 1,
            DataUri::Taken(reference, end) => {
                let out = out.get_or_insert_with(|| Vec::with_capacity(bytes.len()));
                out.extend_from_slice(&bytes[copied_to..start]);
                out.extend_from_slice(reference.as_bytes());
                copied_to = end;
            }
        }
    }
    match out {
        Some(mut out) => {
            out.extend_from_slice(&bytes[copied_to..]);
            Cow::Owned(out)
        }
        None => Cow::Borrowed(bytes),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const KEY: [u8; 32] = [3; 32];

    fn sink(limits: ImageLimits) -> ImageSink<'static> {
        ImageSink::new(&KEY, 7, "2026-10", limits)
    }

    fn data_uri(mime: &str, bytes: &[u8]) -> String {
        format!("data:{mime};base64,{}", STANDARD.encode(bytes))
    }

    /// Puts each image back in place of its reference, as a reader of the dataset does.
    fn reinline(bytes: &[u8], images: &[Image]) -> Vec<u8> {
        let mut text = String::from_utf8(bytes.to_vec()).unwrap();
        for image in images {
            text = text.replace(&image.reference, &data_uri(&image.mime, &image.bytes));
        }
        text.into_bytes()
    }

    #[test]
    fn moves_images_out_of_every_slot_and_back_without_changing_a_byte() {
        let png = data_uri("image/png", b"png bytes");
        let jpeg = data_uri("image/JPEG", b"jpeg bytes");
        // The stylesheet text sits inside a JSON string, so its quotes arrive escaped.
        let event = format!(
            r#"{{"type":2,"data":{{"node":{{"attributes":{{"src":"{png}","srcset":"{jpeg} 1x, {png} 2x","style":"background:url({jpeg})"}},"childNodes":[{{"textContent":".a{{background:url(\"{png}\")}}"}}]}}}}}}"#
        );
        let mut images = sink(ImageLimits::default());
        let out = extract_images(event.as_bytes(), &mut images);

        assert!(!String::from_utf8_lossy(&out).contains("base64"));
        assert_eq!(images.images.len(), 2, "each distinct image is stored once");
        assert_eq!(images.left_inline, 0);
        assert_eq!(
            reinline(&out, &images.images),
            event.replace("image/JPEG", "image/jpeg").into_bytes()
        );
    }

    #[test]
    fn leaves_what_it_cannot_take_inline() {
        let big = vec![1u8; 1000];
        let cases = [
            (data_uri("image/svg+xml", b"<svg/>"), ImageLimits::default()),
            (data_uri("image/bmp", b"BM"), ImageLimits::default()),
            ("data:image/png;utf8,abc".to_owned(), ImageLimits::default()),
            // A URI without a comma before its string ends: the next comma separates JSON fields.
            (
                r#"data:image/png;base64","alt":"x"#.to_owned(),
                ImageLimits::default(),
            ),
            (
                "data:image/png;base64,iVBOR\\u002Fw".to_owned(),
                ImageLimits::default(),
            ),
            // A CSS escape for `/`, with the backslash doubled by JSON.
            (
                format!(
                    "{}\\\\2f {}",
                    data_uri("image/png", &[7; 60]),
                    STANDARD.encode([8; 30])
                ),
                ImageLimits::default(),
            ),
            // Line-wrapped base64: the run before the break is only part of the image.
            (
                format!(
                    "{}\\n{}",
                    data_uri("image/png", &[7; 60]),
                    STANDARD.encode([8; 30])
                ),
                ImageLimits::default(),
            ),
            // A wrapped tail that looks like a srcset descriptor.
            (
                format!("{}\\n123x", data_uri("image/png", &[7; 60])),
                ImageLimits::default(),
            ),
            (
                data_uri("image/png", &big),
                ImageLimits {
                    max_image_bytes: 999,
                    ..ImageLimits::default()
                },
            ),
            (
                data_uri("image/png", &big),
                ImageLimits {
                    max_images: 0,
                    ..ImageLimits::default()
                },
            ),
        ];
        for (uri, limits) in cases {
            let event = format!(r#"{{"src":"{uri}"}}"#);
            let mut images = sink(limits);
            assert!(
                matches!(
                    extract_images(event.as_bytes(), &mut images),
                    Cow::Borrowed(_)
                ),
                "{uri}"
            );
            assert_eq!((images.images.len(), images.left_inline), (0, 1), "{uri}");
        }
    }

    #[test]
    fn takes_the_data_uris_v3_collects() {
        let payload = STANDARD.encode(b"icon bytes");
        for uri in [
            format!("data:image/png;charset=utf-8;base64,{payload}"),
            format!("DATA:image/PNG;BASE64,{payload}"),
            format!("data:image/x-icon;base64,{payload}"),
        ] {
            let event = format!(r#"{{"src":"{uri}"}}"#);
            let mut images = sink(ImageLimits::default());
            let out = extract_images(event.as_bytes(), &mut images);
            assert_eq!(images.images.len(), 1, "{uri}");
            assert_eq!(
                out.as_ref(),
                format!(r#"{{"src":"{}"}}"#, images.images[0].reference).as_bytes()
            );
        }
    }

    #[test]
    fn references_a_repeated_image_after_the_count_cap() {
        let first = data_uri("image/png", b"first");
        let event = format!(
            r#"["{first}","{}","{first}"]"#,
            data_uri("image/png", b"second")
        );
        let mut images = sink(ImageLimits {
            max_images: 1,
            ..ImageLimits::default()
        });
        let out = extract_images(event.as_bytes(), &mut images);
        let reference = &images.images[0].reference;
        assert_eq!(
            String::from_utf8_lossy(&out)
                .matches(reference.as_str())
                .count(),
            2
        );
        assert_eq!((images.images.len(), images.left_inline), (1, 1));
    }

    #[test]
    fn scans_unterminated_data_uris_in_linear_time() {
        // Without a bound, each match searches to the `;` at the end of the buffer for its subtype.
        let bytes = format!("{};", "data:image/".repeat(200_000));
        let started = std::time::Instant::now();
        let mut images = sink(ImageLimits::default());
        extract_images(bytes.as_bytes(), &mut images);
        assert_eq!(images.left_inline, 200_000);
        assert!(started.elapsed() < std::time::Duration::from_secs(5));
    }
}
