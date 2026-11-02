//! Moves inline images out of a v4 block. Each base64 raster data URI becomes an `image:v4` reference, and its
//! decoded bytes go to the flush's image pack. A base64 AVIF data URI becomes [`AVIF_MARKER`], so the block holds no
//! AVIF image.
//!
//! The scan is one pass over the colons, for `data:image/` in any case. A data URI looks the same in an attribute, a CSS `url()`, a
//! `srcset` candidate or stylesheet text, so the scan needs no knowledge of where it sits. Every other byte is
//! copied as it is. Nothing here protects privacy, so an image the scan cannot take stays inline in the sealed block.

use std::borrow::Cow;
use std::collections::HashSet;

use base64::engine::general_purpose::STANDARD;
use base64::Engine;

use crate::refs::{image_ref, reference_hash};

/// What an AVIF data URI becomes. The dataset keeps no AVIF image, inline or fetched.
pub const AVIF_MARKER: &str = "image:v4:declined:avif";

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
    /// AVIF images replaced by [`AVIF_MARKER`].
    pub removed_avif: u32,
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
            removed_avif: 0,
        }
    }

    /// Takes a base64 image and returns its reference, with the caps of v3 `ImageCollector::collect`. The bytes name
    /// the media type, because a page can label a data URI with any type: a font as `image/ttf`, or nothing at all.
    pub(crate) fn take(&mut self, payload: &[u8]) -> Option<String> {
        if payload.len() > self.limits.max_image_bytes.div_ceil(3) * 4 {
            return None;
        }
        let bytes = STANDARD.decode(payload).ok()?;
        if bytes.len() > self.limits.max_image_bytes {
            return None;
        }
        let mime = raster_type(&bytes)?;
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

/// The raster format of the bytes, by its signature: PNG, JPEG, GIF or WebP, the formats the image fetcher also stores.
/// Anything else stays inline in the sealed block.
fn raster_type(bytes: &[u8]) -> Option<&'static str> {
    if bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        Some("image/png")
    } else if bytes.starts_with(b"\xff\xd8\xff") {
        Some("image/jpeg")
    } else if bytes.starts_with(b"GIF87a") || bytes.starts_with(b"GIF89a") {
        Some("image/gif")
    } else if bytes.starts_with(b"RIFF") && bytes.get(8..12) == Some(b"WEBP") {
        Some("image/webp")
    } else {
        None
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
    /// An AVIF image, and where its payload ends.
    Avif(usize),
}

/// The longest `ftyp` box the scan reads for its brands. Real files list a handful of brands in far fewer bytes.
const MAX_FTYP_BYTES: usize = 256;

/// The first bytes of a base64 payload, decoded across the line breaks, whitespace and escaped slashes that
/// [`wrapped_end`] also reads, so that a break inside the header does not hide it.
fn payload_head(bytes: &[u8], start: usize, decoded: usize) -> Vec<u8> {
    let want = decoded.div_ceil(3) * 4;
    let mut base64 = Vec::with_capacity(want);
    let mut position = start;
    while base64.len() < want {
        match bytes.get(position..) {
            Some([b'\\', b'n' | b'r' | b't', ..]) => position += 2,
            Some([b'\\', b'/', ..]) => {
                base64.push(b'/');
                position += 2;
            }
            Some([b'\\', b'u', b'0', b'0', b'2', b'f' | b'F', ..]) => {
                base64.push(b'/');
                position += 6;
            }
            // A space before a srcset descriptor such as `100w` ends the payload.
            Some([b' ', ..]) => {
                let next = position + bytes[position..].iter().take_while(|&&b| b == b' ').count();
                if is_descriptor(bytes, next) {
                    break;
                }
                position = next;
            }
            Some([b'\t' | b'\n' | b'\r', ..]) => position += 1,
            // Padding ends the payload.
            Some([b'=', ..]) => {
                base64.push(b'=');
                break;
            }
            Some([byte, ..]) if is_base64(*byte) => {
                base64.push(*byte);
                position += 1;
            }
            _ => break,
        }
    }
    if base64.last() == Some(&b'=') {
        while base64.len() % 4 != 0 {
            base64.push(b'=');
        }
    }
    base64.truncate(base64.len() / 4 * 4);
    STANDARD.decode(&base64).unwrap_or_default()
}

/// Whether the bytes start with an ISO-BMFF `ftyp` box that names an AVIF brand, as its major brand or as one of its
/// compatible brands.
fn is_avif_header(bytes: &[u8]) -> bool {
    if bytes.get(4..8) != Some(b"ftyp") {
        return false;
    }
    let size = u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) as usize;
    let ftyp = &bytes[..size.clamp(8, MAX_FTYP_BYTES).min(bytes.len())];
    let is_avif = |brand: &[u8]| matches!(brand, b"avif" | b"avis");
    ftyp.get(8..12).is_some_and(is_avif)
        || ftyp
            .get(16..)
            .is_some_and(|brands| brands.chunks_exact(4).any(is_avif))
}

/// Where a base64 payload that `continues_past` its first break really ends: after the line breaks, whitespace and
/// escaped slashes inside it. `None` when it holds an escape that the scan does not read, so the URI cannot be cut out.
fn wrapped_end(bytes: &[u8], mut end: usize) -> Option<usize> {
    while continues_past(bytes, end) {
        let before = end;
        loop {
            match bytes.get(end..) {
                Some([b'\\', b'n' | b'r' | b't' | b'/', ..]) => end += 2,
                Some([b'\\', b'u', b'0', b'0', b'2', b'f' | b'F', ..]) => end += 6,
                Some([b' ' | b'\t' | b'\n' | b'\r', ..]) => end += 1,
                Some([b'\\', ..]) => return None,
                _ => break,
            }
        }
        end += bytes[end..]
            .iter()
            .position(|&b| !is_base64(b))
            .unwrap_or(bytes.len() - end);
        if end == before {
            return None;
        }
    }
    Some(end)
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
    let subtype = &media_type["image/".len()..];
    if !meta.contains("base64") {
        return DataUri::Inline;
    }
    let payload_start = meta_start + comma + 1;
    let end = bytes[payload_start..]
        .iter()
        .position(|&b| !is_base64(b))
        .map_or(bytes.len(), |length| payload_start + length);
    // The label or the bytes can name AVIF, so both count.
    if subtype.starts_with("avif")
        || is_avif_header(&payload_head(bytes, payload_start, MAX_FTYP_BYTES))
    {
        return match wrapped_end(bytes, end) {
            Some(end) => DataUri::Avif(end),
            None => DataUri::Inline,
        };
    }
    if raster_mime(subtype).is_none() {
        return DataUri::Inline;
    }
    if continues_past(bytes, end) {
        return DataUri::Inline;
    }
    match sink.take(&bytes[payload_start..end]) {
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
            DataUri::Avif(end) => {
                sink.removed_avif += 1;
                let out = out.get_or_insert_with(|| Vec::with_capacity(bytes.len()));
                out.extend_from_slice(&bytes[copied_to..start]);
                out.extend_from_slice(AVIF_MARKER.as_bytes());
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

    /// Image bytes that start with a raster signature, so that the scan takes them.
    fn png(body: &[u8]) -> Vec<u8> {
        [b"\x89PNG\r\n\x1a\n".as_slice(), body].concat()
    }

    fn jpeg(body: &[u8]) -> Vec<u8> {
        [b"\xff\xd8\xff".as_slice(), body].concat()
    }

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
        let png = data_uri("image/png", &png(b"png bytes"));
        let jpeg = data_uri("image/JPEG", &jpeg(b"jpeg bytes"));
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
        let big = png(&[1u8; 992]);
        let cases = [
            (data_uri("image/svg+xml", b"<svg/>"), ImageLimits::default()),
            (data_uri("image/bmp", b"BM"), ImageLimits::default()),
            // The bytes name the type, so a font, an icon, an empty payload or a mislabeled text stays inline.
            (
                data_uri("image/ttf", b"\x00\x01\x00\x00font"),
                ImageLimits::default(),
            ),
            (
                data_uri("image/x-icon", b"\x00\x00\x01\x00icon"),
                ImageLimits::default(),
            ),
            ("data:image/gif;base64,".to_owned(), ImageLimits::default()),
            (
                data_uri("image/png", b"not an image"),
                ImageLimits::default(),
            ),
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
                    data_uri("image/png", &png(&[7; 52])),
                    STANDARD.encode([8; 30])
                ),
                ImageLimits::default(),
            ),
            // Line-wrapped base64: the run before the break is only part of the image.
            (
                format!(
                    "{}\\n{}",
                    data_uri("image/png", &png(&[7; 52])),
                    STANDARD.encode([8; 30])
                ),
                ImageLimits::default(),
            ),
            // A wrapped tail that looks like a srcset descriptor.
            (
                format!("{}\\n123x", data_uri("image/png", &png(&[7; 52]))),
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
    fn replaces_every_avif_data_uri_with_the_marker() {
        let avif = STANDARD.encode(b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf");
        // AVIF as a compatible brand only, under the major brand `mif1`.
        let compatible = STANDARD.encode(b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00miafavif");
        for uri in [
            format!("data:image/png;base64,{compatible}"),
            // A break inside the header under another label.
            format!("data:image/png;base64,{}\\n{}", &avif[..8], &avif[8..]),
            format!("data:image/avif;base64,{avif}"),
            // The bytes name AVIF under another label.
            format!("data:image/png;base64,{avif}"),
            // A line-wrapped payload is cut out whole.
            format!("data:image/avif;base64,{}\\n{}", &avif[..16], &avif[16..]),
        ] {
            let event = format!(r#"{{"src":"{uri}","alt":"x"}}"#);
            let mut images = sink(ImageLimits::default());
            let out = extract_images(event.as_bytes(), &mut images);
            assert_eq!(
                String::from_utf8_lossy(&out),
                format!(r#"{{"src":"{AVIF_MARKER}","alt":"x"}}"#),
                "{uri}"
            );
            assert_eq!((images.images.len(), images.removed_avif), (0, 1), "{uri}");
        }
        // A short, padded payload before a srcset descriptor, under another label.
        let event = format!(r#"{{"srcset":"data:image/png;base64,{avif} 100w"}}"#);
        let mut images = sink(ImageLimits::default());
        let out = extract_images(event.as_bytes(), &mut images);
        assert_eq!(
            String::from_utf8_lossy(&out),
            format!(r#"{{"srcset":"{AVIF_MARKER} 100w"}}"#)
        );
    }

    #[test]
    fn takes_the_data_uris_v3_collects() {
        let payload = STANDARD.encode(png(b"icon bytes"));
        for uri in [
            format!("data:image/png;charset=utf-8;base64,{payload}"),
            format!("DATA:image/PNG;BASE64,{payload}"),
            // A label that does not name the bytes: the stored type comes from the bytes.
            format!("data:image/jpeg;base64,{payload}"),
            format!("data:image/png+xml;base64,{payload}"),
        ] {
            let event = format!(r#"{{"src":"{uri}"}}"#);
            let mut images = sink(ImageLimits::default());
            let out = extract_images(event.as_bytes(), &mut images);
            assert_eq!(images.images.len(), 1, "{uri}");
            assert_eq!(images.images[0].mime, "image/png", "{uri}");
            assert_eq!(
                out.as_ref(),
                format!(r#"{{"src":"{}"}}"#, images.images[0].reference).as_bytes()
            );
        }
    }

    #[test]
    fn references_a_repeated_image_after_the_count_cap() {
        let first = data_uri("image/png", &png(b"first"));
        let event = format!(
            r#"["{first}","{}","{first}"]"#,
            data_uri("image/png", &png(b"second"))
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
