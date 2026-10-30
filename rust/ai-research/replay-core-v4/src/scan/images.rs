//! Moves inline images out of a v4 block. Each raster data URI becomes an `image:v4` reference, and its decoded bytes
//! go to the flush's image pack. An image that the image scrub cannot read, or that is over a cap, becomes a
//! [`Declined`] marker, and its bytes are not stored.
//!
//! The scan is one pass over the colons, for `data:image/` in any case. A data URI looks the same in an attribute, a CSS `url()`, a
//! `srcset` candidate or stylesheet text, so the scan needs no knowledge of where it sits. Every other byte is
//! copied as it is. An SVG data URI stays inline, because SVG is text that the text scrub reads in place.

use std::borrow::Cow;
use std::collections::HashSet;

use base64::alphabet;
use base64::engine::general_purpose::{GeneralPurpose, GeneralPurposeConfig};
use base64::engine::DecodePaddingMode;
use base64::Engine;

use crate::bytescan as scan;
use crate::refs::{image_ref, reference_hash};

pub const DECLINED_PREFIX: &str = "image:v4:declined:";

/// Readers of the dataset accept only these exact markers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Declined {
    /// The dataset keeps no AVIF image, inline or fetched.
    Avif,
    OverLimit,
    Undecodable,
    Unsupported,
}

impl Declined {
    pub const ALL: [Declined; 4] = [
        Declined::Avif,
        Declined::OverLimit,
        Declined::Undecodable,
        Declined::Unsupported,
    ];

    pub const fn label(self) -> &'static str {
        match self {
            Declined::Avif => "avif",
            Declined::OverLimit => "over_limit",
            Declined::Undecodable => "undecodable",
            Declined::Unsupported => "unsupported",
        }
    }

    pub const fn marker(self) -> &'static str {
        match self {
            Declined::Avif => "image:v4:declined:avif",
            Declined::OverLimit => "image:v4:declined:over_limit",
            Declined::Undecodable => "image:v4:declined:undecodable",
            Declined::Unsupported => "image:v4:declined:unsupported",
        }
    }
}

/// Base64 as a browser reads a data URI: the padding is optional, and the bits after the last byte do not count.
const FORGIVING_BASE64: GeneralPurpose = GeneralPurpose::new(
    &alphabet::STANDARD,
    GeneralPurposeConfig::new()
        .with_decode_padding_mode(DecodePaddingMode::Indifferent)
        .with_decode_allow_trailing_bits(true),
);

/// The longest media type and parameters a data URI has before its comma. A raster type with parameters, such as
/// `image/png;charset=utf-8;base64`, fits. The bound keeps the scan linear.
const MAX_META: usize = 64;

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
    /// SVG data URIs, the only images left inline.
    pub left_inline: u32,
    /// Indexed by [`Declined`].
    pub declined: [u32; Declined::ALL.len()],
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
            declined: [0; Declined::ALL.len()],
        }
    }

    /// The bytes name the media type, because a page can label a data URI with any type: a font as `image/ttf`, or
    /// nothing at all.
    pub(crate) fn take(&mut self, bytes: Vec<u8>) -> String {
        match self.store(bytes) {
            Ok(reference) => reference,
            Err(reason) => self.decline(reason),
        }
    }

    pub(crate) fn take_base64(&mut self, payload: &[u8]) -> String {
        if payload.len() > self.limits.max_image_bytes.div_ceil(3) * 4 {
            return self.decline(Declined::OverLimit);
        }
        match FORGIVING_BASE64.decode(payload) {
            Ok(bytes) => self.take(bytes),
            Err(_) => self.decline(Declined::Undecodable),
        }
    }

    pub(crate) fn decline(&mut self, reason: Declined) -> String {
        self.declined[reason as usize] += 1;
        reason.marker().to_owned()
    }

    fn store(&mut self, bytes: Vec<u8>) -> Result<String, Declined> {
        if bytes.len() > self.limits.max_image_bytes {
            return Err(Declined::OverLimit);
        }
        if is_avif_header(&bytes) {
            return Err(Declined::Avif);
        }
        let mime = raster_type(&bytes).ok_or(Declined::Unsupported)?;
        let reference = image_ref(
            self.team_id,
            self.key_month,
            &reference_hash(self.content_key, &bytes),
        );
        // An image repeated in one message is stored once and referenced at every place it appears, past the caps too.
        if self.seen.contains(&reference) {
            return Ok(reference);
        }
        if self.images.len() >= self.limits.max_images
            || self.total_bytes + bytes.len() > self.limits.max_total_bytes
        {
            return Err(Declined::OverLimit);
        }
        self.seen.insert(reference.clone());
        self.total_bytes += bytes.len();
        self.images.push(Image {
            reference: reference.clone(),
            mime: mime.to_owned(),
            bytes,
        });
        Ok(reference)
    }
}

/// The raster format of the bytes, by its signature: PNG, JPEG, GIF or WebP, the formats the image fetcher also stores.
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
/// so the caller reads on with [`wrapped_end`]. Line-wrapped base64 continues it, and so does an escape inside it: an
/// escaped slash (`\/` or `\u002F`), or a CSS escape such as `\2f `, which arrives with its backslash doubled. Only the
/// `\"` that closes a quoted CSS url ends it for sure.
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
    Svg,
    /// The reference or marker, and where the URI ends.
    Replaced(String, usize),
}

/// The longest `ftyp` box the scan reads for its brands. Real files list a handful of brands in far fewer bytes.
const MAX_FTYP_BYTES: usize = 256;

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
/// escapes inside it. Also whether the scan read every escape, which only escaped slashes and line breaks are.
fn wrapped_end(bytes: &[u8], mut end: usize) -> (usize, bool) {
    let mut readable = true;
    while continues_past(bytes, end) {
        let before = end;
        loop {
            match bytes.get(end..) {
                Some([b'\\', b'"', ..]) => break,
                Some([b'\\', b'n' | b'r' | b't' | b'/', ..]) => end += 2,
                Some([b'\\', b'u', b'0', b'0', b'2', b'f' | b'F', ..]) => end += 6,
                Some([b'\\', _, ..]) => {
                    readable = false;
                    end += 2;
                }
                Some([b' ' | b'\t' | b'\n' | b'\r', ..]) => end += 1,
                _ => break,
            }
        }
        end += bytes[end..]
            .iter()
            .position(|&b| !is_base64(b))
            .unwrap_or(bytes.len() - end);
        if end == before {
            return (end, false);
        }
    }
    (end, readable)
}

fn wrapped_payload(bytes: &[u8], start: usize, end: usize) -> Vec<u8> {
    let mut base64 = Vec::with_capacity(end - start);
    let mut rest = &bytes[start..end];
    loop {
        rest = match rest {
            [b'\\', b'u', b'0', b'0', b'2', b'f' | b'F', tail @ ..] | [b'\\', b'/', tail @ ..] => {
                base64.push(b'/');
                tail
            }
            [b'\\', _, tail @ ..] | [b' ' | b'\t' | b'\n' | b'\r', tail @ ..] => tail,
            [byte, tail @ ..] => {
                base64.push(*byte);
                tail
            }
            [] => return base64,
        };
    }
}

/// Where a data URI ends whose payload is not base64: at the end of its JSON string, at the quote or parenthesis that
/// opened it, or at whitespace when no quote opened it, as in a srcset. Only its own quote ends a quoted URI, because a
/// URL may hold an unencoded `'` or `)`.
fn uri_end(bytes: &[u8], start: usize, from: usize) -> usize {
    let opener = start.checked_sub(1).map(|at| bytes[at]);
    // `\"` opens a quoted CSS url in stylesheet text. A `"` after an even number of backslashes opens the JSON string.
    let backslashes = bytes[..start.saturating_sub(1)]
        .iter()
        .rev()
        .take_while(|&&b| b == b'\\')
        .count();
    let quoted = match opener {
        Some(b'\'') => true,
        Some(b'"') => backslashes % 2 == 1,
        _ => false,
    };
    let close = match opener {
        Some(b'(') => Some(b')'),
        Some(b'\'') => Some(b'\''),
        _ => None,
    };
    let mut at = from;
    while let Some(&byte) = bytes.get(at) {
        match byte {
            b'"' => return at,
            b'\\' => match bytes.get(at + 1) {
                Some(b'"') => return at,
                Some(b'n' | b'r' | b't') if !quoted => return at,
                _ => at += 2,
            },
            b' ' | b'\t' | b'\n' | b'\r' if !quoted => return at,
            _ if Some(byte) == close => return at,
            _ => at += 1,
        }
    }
    bytes.len()
}

fn percent_decoded(raw: &[u8]) -> Option<Vec<u8>> {
    let quoted = [b"\"".as_slice(), raw, b"\""].concat();
    let text = scan::unescape(&quoted, (0, quoted.len())).ok()?;
    Some(percent_encoding::percent_decode(text.as_bytes()).collect())
}

enum Meta {
    Read(String, usize),
    /// No payload follows: a quote or an escape comes before any comma, or whitespace marks the bytes as text.
    Unterminated,
    TooLong(String),
}

/// A JSON writer may escape a `/` as `\/` or `\u002F`, so both read as `/`.
fn read_meta(bytes: &[u8], start: usize) -> Meta {
    let mut meta = String::new();
    let mut at = start;
    let mut whitespace = false;
    while at - start <= MAX_META {
        match bytes.get(at..) {
            Some([b',', ..]) => return Meta::Read(meta, at),
            Some([b'\\', b'/', ..]) => {
                meta.push('/');
                at += 2;
            }
            Some([b'\\', b'u', b'0', b'0', b'2', b'f' | b'F', ..]) => {
                meta.push('/');
                at += 6;
            }
            Some([b'"' | b'\\', ..] | []) | None => return Meta::Unterminated,
            Some([byte, ..]) => {
                whitespace |= byte.is_ascii_whitespace();
                meta.push(char::from(byte.to_ascii_lowercase()));
                at += 1;
            }
        }
    }
    if whitespace {
        Meta::Unterminated
    } else {
        Meta::TooLong(meta)
    }
}

/// Reads the data URI whose `data:` starts at `start`, with the rules of v3 `collectable_data_uri_bytes`: the media
/// type and `base64` in any case, and any parameters before the comma.
fn read_data_uri(bytes: &[u8], start: usize, sink: &mut ImageSink<'_>) -> DataUri {
    let meta_start = start + b"data:".len();
    let (meta, comma) = match read_meta(bytes, meta_start) {
        Meta::Read(meta, comma) if meta.starts_with("image/") => (meta, comma),
        // A browser reads parameters of any length, so the URI can hold an image whose payload the scan cannot find.
        Meta::TooLong(meta) if meta.starts_with("image/") => {
            let end = uri_end(bytes, start, meta_start);
            return DataUri::Replaced(sink.decline(Declined::Undecodable), end);
        }
        _ => return DataUri::NotImage,
    };
    let media_type = meta.split(';').next().unwrap_or_default();
    let subtype = &media_type["image/".len()..];
    if subtype.starts_with("svg") {
        return DataUri::Svg;
    }
    let payload_start = comma + 1;
    if !meta.contains("base64") {
        let end = uri_end(bytes, start, payload_start);
        let replacement = match &bytes[payload_start..end] {
            [] => return DataUri::NotImage,
            _ if subtype.starts_with("avif") => sink.decline(Declined::Avif),
            raw => match percent_decoded(raw) {
                Some(image) => sink.take(image),
                None => sink.decline(Declined::Undecodable),
            },
        };
        return DataUri::Replaced(replacement, end);
    }
    let run_end = bytes[payload_start..]
        .iter()
        .position(|&b| !is_base64(b))
        .map_or(bytes.len(), |length| payload_start + length);
    let (end, readable) = if continues_past(bytes, run_end) {
        wrapped_end(bytes, run_end)
    } else {
        (run_end, true)
    };
    if end == payload_start {
        return DataUri::NotImage;
    }
    // The label or the bytes can name AVIF, so both count.
    let replacement = if subtype.starts_with("avif") {
        sink.decline(Declined::Avif)
    } else if !readable {
        sink.decline(Declined::Undecodable)
    } else if end == run_end {
        sink.take_base64(&bytes[payload_start..end])
    } else {
        sink.take_base64(&wrapped_payload(bytes, payload_start, end))
    };
    DataUri::Replaced(replacement, end)
}

/// Replaces every inline image in `bytes` but SVG with its reference or a marker. Returns the input unchanged when it
/// holds none.
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
            DataUri::Svg => sink.left_inline += 1,
            DataUri::Replaced(replacement, end) => {
                let out = out.get_or_insert_with(|| Vec::with_capacity(bytes.len()));
                out.extend_from_slice(&bytes[copied_to..start]);
                out.extend_from_slice(replacement.as_bytes());
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
    use base64::engine::general_purpose::STANDARD;

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

    fn declined(reason: Declined) -> [u32; Declined::ALL.len()] {
        let mut counts = [0; Declined::ALL.len()];
        counts[reason as usize] = 1;
        counts
    }

    #[test]
    fn writes_only_the_markers_readers_accept() {
        assert_eq!(
            Declined::ALL.map(Declined::marker),
            [
                "image:v4:declined:avif",
                "image:v4:declined:over_limit",
                "image:v4:declined:undecodable",
                "image:v4:declined:unsupported",
            ]
        );
        for reason in Declined::ALL {
            assert_eq!(
                reason.marker(),
                format!("{DECLINED_PREFIX}{}", reason.label())
            );
        }
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
    fn takes_wrapped_escaped_unpadded_and_percent_encoded_payloads() {
        let image = png(&[0xfb; 62]);
        let base64 = STANDARD.encode(&image);
        assert!(base64.contains('/') && base64.ends_with('='));
        let (head, tail) = base64.split_at(40);
        let percent: String = image
            .iter()
            .map(|&b| {
                if b.is_ascii_alphanumeric() {
                    char::from(b).to_string()
                } else {
                    format!("%{b:02X}")
                }
            })
            .collect();
        let cases = [
            (
                r#"{"src":""#,
                format!(r"data:image/png;base64,{head}\n{tail}"),
                r#""}"#,
            ),
            (
                r#"{"src":""#,
                format!(r"data:image/png;base64,{head}\r\n  {tail}"),
                r#""}"#,
            ),
            (
                r#"{"src":""#,
                format!(r"data:image\/png;base64,{}", base64.replace('/', r"\/")),
                r#""}"#,
            ),
            (
                r#"{"src":""#,
                format!("data:image/png;base64,{}", base64.replace('/', r"\u002F")),
                r#""}"#,
            ),
            (
                r#"{"src":""#,
                format!("data:image/png;base64,{}", base64.trim_end_matches('=')),
                r#""}"#,
            ),
            (r#"{"src":""#, format!("data:image/png,{percent}"), r#""}"#),
            (
                r#"{"style":"background:url("#,
                format!("data:image/png,{percent}"),
                r#") no-repeat"}"#,
            ),
            (
                r#"{"textContent":".a{background:url(\""#,
                format!("data:image/png;charset=binary,{percent}"),
                r#"\")}"}"#,
            ),
            (
                r#"{"srcset":""#,
                format!("data:image/png,{percent}"),
                r#" 2x, https://example.com/a.png 1x"}"#,
            ),
        ];
        for (before, uri, after) in cases {
            let event = format!("{before}{uri}{after}");
            let mut images = sink(ImageLimits::default());
            let out = extract_images(event.as_bytes(), &mut images);
            assert_eq!(images.images.len(), 1, "{event}");
            assert_eq!(images.images[0].bytes, image, "{event}");
            assert_eq!(
                String::from_utf8_lossy(&out),
                format!("{before}{}{after}", images.images[0].reference),
                "{event}"
            );
        }
    }

    #[test]
    fn declines_each_image_the_image_scrub_cannot_read() {
        let big = png(&[1u8; 992]);
        let limits = ImageLimits::default();
        let wrapped = data_uri("image/png", &png(&[7; 52]));
        let cases = [
            (
                data_uri("image/png", &big),
                ImageLimits {
                    max_image_bytes: 999,
                    ..limits
                },
                Declined::OverLimit,
            ),
            (
                data_uri("image/png", &big),
                ImageLimits {
                    max_images: 0,
                    ..limits
                },
                Declined::OverLimit,
            ),
            (
                data_uri("image/png", &big),
                ImageLimits {
                    max_total_bytes: 999,
                    ..limits
                },
                Declined::OverLimit,
            ),
            (
                "data:image/png;base64,iVBORw0KG".to_owned(),
                limits,
                Declined::Undecodable,
            ),
            (
                "data:image/png;base64,iVBO=Rw0KGgo".to_owned(),
                limits,
                Declined::Undecodable,
            ),
            // A CSS escape for `/`, with the backslash doubled by JSON.
            (
                format!(r"{wrapped}\\2f {}", STANDARD.encode([8; 30])),
                limits,
                Declined::Undecodable,
            ),
            (
                format!(
                    "data:image/png;name={};base64,{}",
                    "a".repeat(80),
                    STANDARD.encode(png(b"x"))
                ),
                limits,
                Declined::Undecodable,
            ),
            (
                data_uri("image/ttf", b"\x00\x01\x00\x00font"),
                limits,
                Declined::Unsupported,
            ),
            (
                data_uri("image/x-icon", b"\x00\x00\x01\x00icon"),
                limits,
                Declined::Unsupported,
            ),
            (
                data_uri("image/bmp", b"BMbitmap"),
                limits,
                Declined::Unsupported,
            ),
            (
                data_uri("image/png", b"not an image"),
                limits,
                Declined::Unsupported,
            ),
            (
                "data:image/png;utf8,abc".to_owned(),
                limits,
                Declined::Unsupported,
            ),
        ];
        for (uri, limits, reason) in cases {
            let event = format!(r#"{{"src":"{uri}","alt":"x"}}"#);
            let mut images = sink(limits);
            let out = extract_images(event.as_bytes(), &mut images);
            assert_eq!(
                String::from_utf8_lossy(&out),
                format!(r#"{{"src":"{}","alt":"x"}}"#, reason.marker()),
                "{uri}"
            );
            assert_eq!(
                (images.images.len(), images.declined),
                (0, declined(reason)),
                "{uri}"
            );
        }
    }

    #[test]
    fn leaves_svg_and_data_uris_without_a_payload_as_they_are() {
        for event in [
            format!(r#"{{"src":"{}"}}"#, data_uri("image/svg+xml", b"<svg/>")),
            r#"{"src":"data:image/svg+xml,%3Csvg%2F%3E"}"#.to_owned(),
            r#"{"src":"data:image/gif;base64,"}"#.to_owned(),
            // A URI without a comma before its string ends: the next comma separates JSON fields.
            r#"{"src":"data:image/png;base64","alt":"x"}"#.to_owned(),
            r#"{"textContent":"Use data:image/png, data:image/gif, or a link"}"#.to_owned(),
            r#"{"textContent":"Paste a data:image/ URI in the box below and the page shows a preview of the image right here"}"#.to_owned(),
        ] {
            let mut images = sink(ImageLimits::default());
            assert!(
                matches!(
                    extract_images(event.as_bytes(), &mut images),
                    Cow::Borrowed(_)
                ),
                "{event}"
            );
            assert_eq!(images.declined, [0; Declined::ALL.len()], "{event}");
            assert_eq!(
                images.left_inline,
                u32::from(event.contains("svg")),
                "{event}"
            );
        }
    }

    #[test]
    fn replaces_every_avif_data_uri_with_the_marker() {
        let marker = Declined::Avif.marker();
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
                format!(r#"{{"src":"{marker}","alt":"x"}}"#),
                "{uri}"
            );
            assert_eq!(
                (images.images.len(), images.declined),
                (0, declined(Declined::Avif)),
                "{uri}"
            );
        }
        // A short, padded payload before a srcset descriptor, under another label.
        let event = format!(r#"{{"srcset":"data:image/png;base64,{avif} 100w"}}"#);
        let mut images = sink(ImageLimits::default());
        let out = extract_images(event.as_bytes(), &mut images);
        assert_eq!(
            String::from_utf8_lossy(&out),
            format!(r#"{{"srcset":"{marker} 100w"}}"#)
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
            format!("data:image/bmp;base64,{payload}"),
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
            String::from_utf8_lossy(&out),
            format!(
                r#"["{reference}","{}","{reference}"]"#,
                Declined::OverLimit.marker()
            )
        );
        assert_eq!(
            (images.images.len(), images.declined),
            (1, declined(Declined::OverLimit))
        );
    }

    #[test]
    fn scans_unterminated_data_uris_in_linear_time() {
        let started = std::time::Instant::now();
        // Without a bound, each match searches to the `"` at the end of the buffer for its comma.
        let spaced = format!("{}\"", "data:image/ ".repeat(200_000));
        let mut images = sink(ImageLimits::default());
        assert!(matches!(
            extract_images(spaced.as_bytes(), &mut images),
            Cow::Borrowed(_)
        ));
        // A run with no break at all could be the parameters of an image, so it goes in one piece.
        let unbroken = format!("{};", "data:image/".repeat(200_000));
        let mut images = sink(ImageLimits::default());
        assert_eq!(
            extract_images(unbroken.as_bytes(), &mut images).as_ref(),
            Declined::Undecodable.marker().as_bytes()
        );
        assert!(started.elapsed() < std::time::Duration::from_secs(5));
    }
}
