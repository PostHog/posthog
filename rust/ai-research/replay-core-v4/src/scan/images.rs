//! Moves inline images out of a v4 block. Each raster data URI becomes an `image:v4` reference, and its decoded bytes
//! go to the flush's image pack. An image the image scrub cannot read, or one over a cap, becomes an [`ImageDecline`]
//! marker.
//!
//! The scan looks for `data:image/` in any case, at each colon and near each CSS escape, because a stylesheet can write
//! any character of a data URI's header as an escape. A data URI looks the same in an attribute, a CSS `url()`, a
//! `srcset` candidate or stylesheet text, so the scan needs no knowledge of where it sits. Every other byte is
//! copied as it is. An SVG data URI stays inline, because SVG is text that the text scrub reads in place.

use std::borrow::Cow;
use std::collections::HashSet;

use base64::alphabet;
use base64::engine::general_purpose::{GeneralPurpose, GeneralPurposeConfig};
use base64::engine::DecodePaddingMode;
use base64::Engine;

use crate::v4_image_refs::{image_ref, ImageDecline};

use crate::bytescan as scan;
use crate::refs::reference_hash;

/// Base64 as a browser reads a data URI: the padding is optional, and the bits after the last byte do not count.
const FORGIVING_BASE64: GeneralPurpose = GeneralPurpose::new(
    &alphabet::STANDARD,
    GeneralPurposeConfig::new()
        .with_decode_padding_mode(DecodePaddingMode::Indifferent)
        .with_decode_allow_trailing_bits(true),
);

/// The payload bytes read past whitespace and a byte order mark to find the `<` that starts SVG markup.
const SNIFFED_PAYLOAD_BYTES: usize = 64;

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
    pub declined: [u32; ImageDecline::ALL.len()],
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
            declined: [0; ImageDecline::ALL.len()],
        }
    }

    /// The bytes name the media type, because a page can label a data URI with any type: a font as `image/ttf`, or nothing at all.
    pub(crate) fn take(&mut self, bytes: Vec<u8>) -> String {
        match self.store(bytes) {
            Ok(reference) => reference,
            Err(reason) => self.decline(reason),
        }
    }

    /// Takes base64 that may hold `%` escapes. It checks the size first, so an oversized payload is never copied.
    pub(crate) fn take_base64(&mut self, payload: &[u8]) -> String {
        let escapes = payload
            .windows(3)
            .filter(|w| w[0] == b'%' && w[1].is_ascii_hexdigit() && w[2].is_ascii_hexdigit())
            .count();
        if payload.len() - 2 * escapes > self.limits.max_image_bytes.div_ceil(3) * 4 {
            return self.decline(ImageDecline::OverLimit);
        }
        match FORGIVING_BASE64.decode(percent_decoded_base64(payload)) {
            Ok(bytes) => self.take(bytes),
            Err(_) => self.decline(ImageDecline::Undecodable),
        }
    }

    pub(crate) fn decline(&mut self, reason: ImageDecline) -> String {
        self.declined[reason as usize] += 1;
        reason.marker().to_owned()
    }

    fn store(&mut self, bytes: Vec<u8>) -> Result<String, ImageDecline> {
        if bytes.len() > self.limits.max_image_bytes {
            return Err(ImageDecline::OverLimit);
        }
        let mime = match avif_header(&bytes) {
            Some(AvifHeader::Still) => "image/avif",
            Some(AvifHeader::NotStill) => return Err(ImageDecline::Avif),
            None => raster_type(&bytes).ok_or(ImageDecline::Unsupported)?,
        };
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
            return Err(ImageDecline::OverLimit);
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

/// The raster format of the bytes, by its signature: PNG, JPEG, GIF or WebP.
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
/// so the caller reads on with [`wrapped_end`]. Line-wrapped base64 continues it, and so does an escape inside it: an escaped
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
                    && (is_base64(byte) || byte == b'%')
                    && (line_break || !is_descriptor(bytes, position));
            }
            None => return false,
        }
    }
}

/// No raster format starts with `<`, and a browser shows raster bytes as an image whatever the label says, so an SVG label keeps a data URI inline only when this is true.
fn payload_is_markup(bytes: &[u8], payload_start: usize, base64: bool) -> bool {
    let mut chars = Vec::new();
    let mut rest = &bytes[payload_start..];
    while chars.len() < SNIFFED_PAYLOAD_BYTES * 3 {
        let (byte, tail) = match rest {
            [b'\\', b'u', b'0', b'0', b'2', b'f' | b'F', tail @ ..] | [b'\\', b'/', tail @ ..] => {
                (b'/', tail)
            }
            [b'\\', b't' | b'n' | b'r' | b'f', tail @ ..] => (b' ', tail),
            [b'"' | b'\\', ..] | [] => break,
            [byte, tail @ ..] => (*byte, tail),
        };
        if !byte.is_ascii_whitespace() {
            chars.push(byte);
        }
        rest = tail;
    }
    let mut decoded: Vec<u8> = percent_encoding::percent_decode(&chars).collect();
    if base64 {
        decoded.retain(|byte| !byte.is_ascii_whitespace());
        let run = decoded
            .iter()
            .position(|&byte| !is_base64(byte))
            .unwrap_or(decoded.len());
        decoded.truncate(run / 4 * 4);
        decoded = FORGIVING_BASE64.decode(&decoded).unwrap_or_default();
    }
    let text = decoded.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(&decoded);
    text.trim_ascii_start().first() == Some(&b'<')
}

enum DataUri {
    NotImage,
    Svg,
    Replaced { replacement: String, end: usize },
}

/// The longest `ftyp` box the scan reads for its brands. A longer AVIF box is not still, so that no brand past the limit can hide an animation.
const MAX_FTYP_BYTES: usize = 256;

enum AvifHeader {
    /// The only AVIF the image scrub decodes.
    Still,
    NotStill,
}

fn avif_header(bytes: &[u8]) -> Option<AvifHeader> {
    if bytes.get(4..8) != Some(b"ftyp") {
        return None;
    }
    let size = u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) as usize;
    let ftyp = &bytes[..size.clamp(8, MAX_FTYP_BYTES).min(bytes.len())];
    let major = ftyp.get(8..12)?;
    let compatible = ftyp.get(16..).unwrap_or_default().chunks_exact(4);
    let mut brands = std::iter::once(major).chain(compatible);
    if !brands
        .clone()
        .any(|brand| matches!(brand, b"avif" | b"avis"))
    {
        return None;
    }
    if major == b"avif" && size <= MAX_FTYP_BYTES && !brands.any(|brand| brand == b"avis") {
        Some(AvifHeader::Still)
    } else {
        Some(AvifHeader::NotStill)
    }
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
        end = base64_run_end(bytes, end);
        if end == before {
            return (end, false);
        }
    }
    (end, readable)
}

/// A browser percent-decodes a data URI before it decodes base64, so a run of base64 takes `%` escapes too.
fn base64_run_end(bytes: &[u8], from: usize) -> usize {
    let mut at = from;
    loop {
        match bytes.get(at..) {
            Some([b'%', high, low, ..]) if high.is_ascii_hexdigit() && low.is_ascii_hexdigit() => {
                at += 3
            }
            Some([byte, ..]) if is_base64(*byte) => at += 1,
            _ => return at,
        }
    }
}

fn percent_decoded_base64(raw: &[u8]) -> Cow<'_, [u8]> {
    if raw.contains(&b'%') {
        Cow::Owned(percent_encoding::percent_decode(raw).collect())
    } else {
        Cow::Borrowed(raw)
    }
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
/// opened it, or at whitespace when no quote opened it. A URL may hold a bare `'` or `)`, so a quoted URI ends only at its own quote.
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

/// Reads the header through CSS escapes and JSON escapes, and skips the tabs and line breaks that a browser removes from a URL, however they are written.
fn header_char(bytes: &[u8], at: usize, double_quoted: bool) -> Option<(char, usize)> {
    let mut removed = 0;
    loop {
        let (ch, len) = url_char(bytes, at + removed, double_quoted)?;
        if !matches!(ch, '\t' | '\n' | '\r') {
            return Some((ch, removed + len));
        }
        removed += len;
    }
}

/// A browser keeps every character but the end of the JSON string, and in a double-quoted CSS url an escaped quote, which ends the URL there.
fn url_char(bytes: &[u8], at: usize, double_quoted: bool) -> Option<(char, usize)> {
    match bytes.get(at..)? {
        [b'\\', b'\\', escaped @ ..] => css_escape(escaped).map(|(ch, len)| (ch, 2 + len)),
        [b'\\', b'"', ..] if double_quoted => None,
        [b'\\', escaped @ ..] => json_escape(escaped).map(|(ch, len)| (ch, 1 + len)),
        [b'"', ..] | [] => None,
        [byte, ..] => Some((char::from(*byte), 1)),
    }
}

/// The length counts from after the backslash.
fn json_escape(escaped: &[u8]) -> Option<(char, usize)> {
    match escaped {
        [b'u', hex @ ..] => {
            let code = std::str::from_utf8(hex.get(..4)?)
                .ok()
                .and_then(|hex| u32::from_str_radix(hex, 16).ok())?;
            Some((
                char::from_u32(code).unwrap_or(char::REPLACEMENT_CHARACTER),
                5,
            ))
        }
        [b'b', ..] => Some(('\u{8}', 1)),
        [b'f', ..] => Some(('\u{c}', 1)),
        [b'n', ..] => Some(('\n', 1)),
        [b'r', ..] => Some(('\r', 1)),
        [b't', ..] => Some(('\t', 1)),
        [byte @ (b'"' | b'/' | b'\\'), ..] => Some((char::from(*byte), 1)),
        _ => None,
    }
}

/// The length counts from after the backslash, and a hex escape takes the one whitespace after it, as CSS reads it.
fn css_escape(escaped: &[u8]) -> Option<(char, usize)> {
    let digits = escaped
        .iter()
        .take(6)
        .take_while(|b| b.is_ascii_hexdigit())
        .count();
    if digits == 0 {
        return match escaped {
            [b'\\', rest @ ..] => json_escape(rest).map(|(ch, len)| (ch, 1 + len)),
            [b'"', ..] | [] => None,
            [byte, ..] => Some((char::from(*byte), 1)),
        };
    }
    let code = escaped[..digits].iter().fold(0u32, |code, &digit| {
        code * 16 + char::from(digit).to_digit(16).unwrap_or_default()
    });
    let whitespace = match &escaped[digits..] {
        [b'\\', b'r', b'\\', b'n', ..] => 4,
        [b'\\', b'n' | b'r' | b't' | b'f', ..] => 2,
        [b' ', ..] => 1,
        _ => 0,
    };
    let ch = char::from_u32(code).unwrap_or(char::REPLACEMENT_CHARACTER);
    Some((ch, digits + whitespace))
}

/// A browser removes tabs and line breaks inside the scheme too, but the first letter is read as it is, so a read that starts at an escaped tab stops there and the search stays linear.
fn after_data_scheme(bytes: &[u8], start: usize) -> Option<usize> {
    let (first, len) = url_char(bytes, start, true)?;
    if !first.eq_ignore_ascii_case(&'d') {
        return None;
    }
    let mut at = start + len;
    for expected in "ata:".chars() {
        let (ch, len) = header_char(bytes, at, true)?;
        if ch.to_ascii_lowercase() != expected {
            return None;
        }
        at += len;
    }
    Some(at)
}

enum Header {
    Image { meta: String, payload_start: usize },
    Other { read_to: usize },
}

/// A browser reads parameters of any length, so the header has no length limit.
fn read_header(bytes: &[u8], meta_start: usize, double_quoted: bool) -> Header {
    const IMAGE: &[u8] = b"image/";
    let mut meta = String::new();
    let mut at = meta_start;
    while let Some((ch, len)) = header_char(bytes, at, double_quoted) {
        let ch = ch.to_ascii_lowercase();
        if meta.len() < IMAGE.len() && Some(ch) != IMAGE.get(meta.len()).copied().map(char::from) {
            return Header::Other { read_to: at };
        }
        if ch == ',' {
            return Header::Image {
                meta,
                payload_start: at + len,
            };
        }
        meta.push(ch);
        at += len;
    }
    Header::Other { read_to: at }
}

/// Reads the data URI whose `data:` starts at `start`, with the rules of v3 `collectable_data_uri_bytes`: the media
/// type and `base64` in any case, and any parameters before the comma. Unlike v3, `base64` counts only at the end.
fn read_data_uri(
    bytes: &[u8],
    start: usize,
    meta: &str,
    payload_start: usize,
    sink: &mut ImageSink<'_>,
) -> DataUri {
    if holds_css_escape(&bytes[start..payload_start]) && css_opener(bytes, start).is_none() {
        return DataUri::Replaced {
            replacement: sink.decline(ImageDecline::Undecodable),
            end: json_string_end(bytes, payload_start),
        };
    }
    let media_type = meta.split(';').next().unwrap_or_default();
    let subtype = &media_type["image/".len()..];
    let base64 = ends_with_base64(meta);
    if subtype.starts_with("svg") && payload_is_markup(bytes, payload_start, base64) {
        return DataUri::Svg;
    }
    // A browser drops a data URL's fragment before it decodes the payload, so the fragment is no part of the image, and
    // it leaves the block with the image.
    if !base64 {
        let end = uri_end(bytes, start, payload_start);
        let payload_end =
            memchr::memchr(b'#', &bytes[payload_start..end]).map_or(end, |at| payload_start + at);
        let replacement = match &bytes[payload_start..payload_end] {
            [] => return DataUri::NotImage,
            raw => match percent_decoded(raw) {
                Some(image) => sink.take(image),
                None => sink.decline(ImageDecline::Undecodable),
            },
        };
        return DataUri::Replaced { replacement, end };
    }
    let run_end = base64_run_end(bytes, payload_start);
    let (payload_end, readable) = if continues_past(bytes, run_end) {
        wrapped_end(bytes, run_end)
    } else {
        (run_end, true)
    };
    if payload_end == payload_start {
        return DataUri::NotImage;
    }
    let replacement = if !readable {
        sink.decline(ImageDecline::Undecodable)
    } else if payload_end == run_end {
        sink.take_base64(&bytes[payload_start..payload_end])
    } else {
        sink.take_base64(&wrapped_payload(bytes, payload_start, payload_end))
    };
    let end = match bytes.get(payload_end) {
        Some(b'#') => uri_end(bytes, start, payload_end),
        _ => payload_end,
    };
    DataUri::Replaced { replacement, end }
}

/// A browser decodes the payload as base64 only when `;base64` ends the header.
fn ends_with_base64(meta: &str) -> bool {
    meta.trim_ascii()
        .strip_suffix("base64")
        .is_some_and(|rest| rest.trim_end_matches(' ').ends_with(';'))
}

fn holds_css_escape(bytes: &[u8]) -> bool {
    bytes.windows(2).any(|pair| pair == br"\\")
}

/// CSS reads an escape as its character, but an attribute such as `src` holds it as text, so outside CSS a browser can
/// read the header another way, for example past an escaped comma to a later one. Whitespace before the URI, in any
/// spelling, does not change where it sits.
fn css_opener(bytes: &[u8], start: usize) -> Option<u8> {
    let mut start = start;
    loop {
        start = match &bytes[..start] {
            [.., b' '] => start - 1,
            [.., b'\\', b't' | b'n' | b'r' | b'f'] => start - 2,
            _ => match css_hex_escape_before(bytes, start) {
                Some((escape_start, 0x9 | 0xa | 0xc | 0xd | 0x20)) => escape_start,
                _ => break,
            },
        };
    }
    let opener = start.checked_sub(1).map(|at| bytes[at])?;
    let escaped_quote = || {
        bytes[..start - 1]
            .iter()
            .rev()
            .take_while(|&&b| b == b'\\')
            .count()
            % 2
            == 1
    };
    match opener {
        b'(' | b'\'' => Some(opener),
        b'"' if escaped_quote() => Some(opener),
        _ => None,
    }
}

fn json_string_end(bytes: &[u8], from: usize) -> usize {
    let mut at = from;
    while let Some(&byte) = bytes.get(at) {
        match byte {
            b'"' => return at,
            b'\\' => at += 2,
            _ => at += 1,
        }
    }
    bytes.len()
}

/// A six-digit CSS escape such as `\000020` ends at its last digit, so the letter after it starts a word.
fn starts_inside_a_word(bytes: &[u8], start: usize) -> bool {
    start
        .checked_sub(1)
        .is_some_and(|before| bytes[before].is_ascii_alphanumeric())
        && css_hex_escape_before(bytes, start)
            .is_none_or(|(escape_start, _)| start - escape_start != 8)
}

/// The CSS hex escape that ends right before `at`, as where its doubled backslash starts and the code it names.
fn css_hex_escape_before(bytes: &[u8], at: usize) -> Option<(usize, u32)> {
    let digits = bytes[..at]
        .iter()
        .rev()
        .take(6)
        .take_while(|b| b.is_ascii_hexdigit())
        .count();
    let escape_start = at.checked_sub(digits + 2)?;
    if digits == 0 || bytes[escape_start..escape_start + 2] != *br"\\" {
        return None;
    }
    let code = std::str::from_utf8(&bytes[at - digits..at])
        .ok()
        .and_then(|hex| u32::from_str_radix(hex, 16).ok())?;
    Some((escape_start, code))
}

/// Each `data:` that an escape or a removed tab or line break spells, as where it starts and where its media type
/// starts, in order. Before its first backslash such a scheme holds only literal letters of `data`, so it starts at
/// most four letters before a backslash, or at a CSS escape.
fn escaped_schemes(bytes: &[u8]) -> impl Iterator<Item = (usize, usize)> + '_ {
    memchr::memchr_iter(b'\\', bytes).flat_map(move |backslash| {
        let literal_starts = (1..=b"data".len())
            .rev()
            .filter_map(move |letters| backslash.checked_sub(letters))
            .filter(move |&start| {
                bytes[start..backslash].eq_ignore_ascii_case(&b"data"[..backslash - start])
            });
        let escape_start = (bytes.get(backslash + 1) == Some(&b'\\')).then_some(backslash);
        literal_starts
            .chain(escape_start)
            .filter(move |&start| !starts_inside_a_word(bytes, start))
            .filter_map(move |start| {
                after_data_scheme(bytes, start).map(|meta_start| (start, meta_start))
            })
    })
}

fn data_schemes(bytes: &[u8]) -> impl Iterator<Item = (usize, usize)> + '_ {
    let mut plain = memchr::memchr_iter(b':', bytes)
        .filter_map(|colon| {
            let start = colon.checked_sub(b"data".len())?;
            (bytes[start..colon].eq_ignore_ascii_case(b"data")
                && !starts_inside_a_word(bytes, start))
            .then_some((start, colon + 1))
        })
        .peekable();
    let mut escaped = escaped_schemes(bytes).peekable();
    std::iter::from_fn(move || match (plain.peek(), escaped.peek()) {
        (Some(plain_scheme), Some(escaped_scheme)) if escaped_scheme < plain_scheme => {
            escaped.next()
        }
        (Some(_), _) => plain.next(),
        (None, _) => escaped.next(),
    })
}

/// Replaces every inline image in `bytes` but SVG with its reference or a marker. Returns the input unchanged when it holds none.
/// A JSON escape of a letter hides an image from the scan, so give it bytes that [`canonical_strings`](crate::bytescan::canonical_strings) wrote.
pub fn extract_images<'b>(bytes: &'b [u8], sink: &mut ImageSink<'_>) -> Cow<'b, [u8]> {
    let mut out: Option<Vec<u8>> = None;
    let mut copied_to = 0;
    // A header can run to the end of its JSON string, so the scan reads each header once and takes a `data:` inside it as part of that URI, to stay linear. That `data:` ends at the same comma and the same `;base64`, so it reads the payload the same way.
    let mut headers_read_to = 0;
    for (start, meta_start) in data_schemes(bytes) {
        if start < copied_to.max(headers_read_to) {
            continue;
        }
        let (meta, payload_start) =
            match read_header(bytes, meta_start, css_opener(bytes, start) == Some(b'"')) {
                Header::Image {
                    meta,
                    payload_start,
                } => (meta, payload_start),
                Header::Other { read_to } => {
                    headers_read_to = read_to;
                    continue;
                }
            };
        headers_read_to = payload_start;
        match read_data_uri(bytes, start, &meta, payload_start, sink) {
            DataUri::NotImage => {}
            DataUri::Svg => sink.left_inline += 1,
            DataUri::Replaced { replacement, end } => {
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

/// Whether the scan keeps the image of this data URI, as a reference or inline as an SVG, by the rules for one image.
/// A message past its caps can still decline it.
pub fn keeps_inline_image(data_uri: &str) -> bool {
    let mut json = Vec::with_capacity(data_uri.len() + 2);
    scan::write_json_string(data_uri, &mut json);
    let mut sink = ImageSink::new(&[0; 32], 0, "", ImageLimits::default());
    extract_images(&json, &mut sink);
    sink.declined == [0; ImageDecline::ALL.len()]
        && (!sink.images.is_empty() || sink.left_inline > 0)
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

    fn declined(reason: ImageDecline) -> [u32; ImageDecline::ALL.len()] {
        let mut counts = [0; ImageDecline::ALL.len()];
        counts[reason as usize] = 1;
        counts
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
    fn takes_escaped_wrapped_unpadded_percent_encoded_and_long_data_uris() {
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
            (
                r#"{"src":""#,
                format!(
                    "data:image/png;base64,%69{}",
                    base64[1..].replace('/', "%2F").replace('=', "%3D")
                ),
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
            // A browser reads a data URL without its fragment, so the fragment leaves with the image.
            (
                r#"{"src":""#,
                format!("data:image/png;base64,{base64}#access_token=secret"),
                r#""}"#,
            ),
            (
                r#"{"style":"background:url("#,
                format!("data:image/png,{percent}#access_token=secret"),
                r#") no-repeat"}"#,
            ),
            (
                r#"{"textContent":".a{background:url(\""#,
                format!("data:image/png;base64,{head}\\n{tail}#access_token=secret"),
                r#"\")}"}"#,
            ),
            (
                r#"{"srcset":""#,
                format!("data:image/png;base64,{base64}#access_token=secret"),
                r#" 2x, https://example.com/a.png 1x"}"#,
            ),
            // CSS escapes in the header, with each backslash doubled by JSON.
            (
                r#"{"style":"background:url("#,
                format!(r"d\\61ta:image/png;base64,{base64}"),
                r#")"}"#,
            ),
            (
                r#"{"textContent":".a{background:url(\""#,
                format!(r"data\\3a image\\2F png;base64,{base64}"),
                r#"\")}"}"#,
            ),
            (
                r#"{"style":"background:url("#,
                format!(r"\\000044 ata\\:image/png;base64,{base64}"),
                r#")"}"#,
            ),
            (
                r#"{"textContent":".a{background:url(\"\\000020"#,
                format!(r"d\\61ta:image/png;base64,{base64}"),
                r#"\")}"}"#,
            ),
            (
                r#"{"textContent":".a{background:url(\""#,
                format!(r"d\\9 ata:image/png;base64,{base64}"),
                r#"\")}"}"#,
            ),
            (
                r#"{"textContent":".a{background:url(\""#,
                format!(r"d{}\\61ta:image/png;base64,{base64}", r"\t".repeat(25)),
                r#"\")}"}"#,
            ),
            (
                r#"{"style":"background:url("#,
                format!(r"data:image/png\\3b base64\\2c {base64}"),
                r#")"}"#,
            ),
            (
                r#"{"src":""#,
                format!("data:image/png;name=a photo of the harbour at dusk before the rain came in.png;base64,{base64}"),
                r#""}"#,
            ),
            (
                r#"{"src":""#,
                format!("data:image/png;name={};base64,{base64}", "a".repeat(80)),
                r#""}"#,
            ),
            (
                r#"{"src":""#,
                format!(r"data:image/png;\tbase64,{base64}"),
                r#""}"#,
            ),
            (
                r#"{"src":""#,
                format!(r"data:image/png;name=a\fb;base64,{base64}"),
                r#""}"#,
            ),
            (
                r#"{"src":""#,
                format!(r#"data:image/png;name=a\"b;base64,{base64}"#),
                r#""}"#,
            ),
            (
                r#"{"textContent":".a{background:url('"#,
                format!(r#"data:image/png;name=a\"b;base64,{base64}"#),
                r#"')}"}"#,
            ),
            (
                r#"{"textContent":".a{background:url(\""#,
                format!(r"data:i\\9mage/png;base64,{base64}"),
                r#"\")}"}"#,
            ),
            // Raster bytes under an SVG label, which a browser shows as an image.
            (r#"{"src":""#, format!("data:image/svg+xml,{percent}"), r#""}"#),
            (
                r#"{"src":""#,
                format!("data:image/svg+xml;base64, {base64}"),
                r#""}"#,
            ),
            (
                r#"{"textContent":".a{background:url("#,
                format!("data:image/svg+xml)}}.b{{background:url(data:image/png;base64,{base64}"),
                r#")}"}"#,
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
        let event = format!(
            r#"{{"textContent":"/*data:image/png;base64*/.a{{background:url(data:image/png,{percent})}}"}}"#
        );
        let mut images = sink(ImageLimits::default());
        let out = extract_images(event.as_bytes(), &mut images);
        assert_eq!(images.images.len(), 1, "{event}");
        assert!(
            !String::from_utf8_lossy(&out).contains(&percent[..12]),
            "{event}"
        );
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
                ImageDecline::OverLimit,
            ),
            (
                data_uri("image/png", &big),
                ImageLimits {
                    max_images: 0,
                    ..limits
                },
                ImageDecline::OverLimit,
            ),
            (
                data_uri("image/png", &big),
                ImageLimits {
                    max_total_bytes: 999,
                    ..limits
                },
                ImageDecline::OverLimit,
            ),
            (
                "data:image/png;base64,iVBORw0KG".to_owned(),
                limits,
                ImageDecline::Undecodable,
            ),
            (
                "data:image/png;base64,iVBO=Rw0KGgo".to_owned(),
                limits,
                ImageDecline::Undecodable,
            ),
            // A CSS escape for `/`, with the backslash doubled by JSON.
            (
                format!(r"{wrapped}\\2f {}", STANDARD.encode([8; 30])),
                limits,
                ImageDecline::Undecodable,
            ),
            (
                data_uri("image/ttf", b"\x00\x01\x00\x00font"),
                limits,
                ImageDecline::Unsupported,
            ),
            (
                data_uri("image/x-icon", b"\x00\x00\x01\x00icon"),
                limits,
                ImageDecline::Unsupported,
            ),
            (
                data_uri("image/bmp", b"BMbitmap"),
                limits,
                ImageDecline::Unsupported,
            ),
            (
                data_uri("image/png", b"not an image"),
                limits,
                ImageDecline::Unsupported,
            ),
            (
                "data:image/png;utf8,abc".to_owned(),
                limits,
                ImageDecline::Unsupported,
            ),
            (
                format!(
                    r"data:image/svg+xml;base64,\\69{}",
                    &STANDARD.encode(png(&[7; 52]))[1..]
                ),
                limits,
                ImageDecline::Undecodable,
            ),
            (
                format!(
                    r"data:image/png;name=base64;x=\\00002cQQ;base64,{}",
                    STANDARD.encode(png(&[7; 52]))
                ),
                limits,
                ImageDecline::Undecodable,
            ),
            // A browser reads a CSS escape in an attribute as text, so the label and `base64` are not what CSS reads.
            (
                format!(
                    r"data:image/sv\\67+xml;base64,{}",
                    STANDARD.encode(png(&[7; 52]))
                ),
                limits,
                ImageDecline::Undecodable,
            ),
            (
                format!(
                    r"data:image/png;name={};\\000062ase64,{}",
                    "a".repeat(80),
                    png(&[7; 52])
                        .iter()
                        .map(|b| format!("%{b:02X}"))
                        .collect::<String>()
                ),
                limits,
                ImageDecline::Undecodable,
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
            format!(
                r#"{{"src":"data:image/svg+xml;base64, {}"}}"#,
                STANDARD.encode(b"<svg/>")
            ),
            r#"{"src":"data:image/svg+xml;base64,P%48N2Zy8+"}"#.to_owned(),
            format!(
                r#"{{"src":"data:image/svg+xml;base64,{}{}"}}"#,
                " ".repeat(200),
                STANDARD.encode(b"<svg/>")
            ),
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
            assert_eq!(images.declined, [0; ImageDecline::ALL.len()], "{event}");
            assert_eq!(
                images.left_inline,
                u32::from(event.contains("svg")),
                "{event}"
            );
        }
    }

    #[test]
    fn stores_a_still_avif_and_declines_every_other_avif() {
        let brands_past_the_scan = [
            b"\x00\x00\x01\x04ftypavif\x00\x00\x00\x00".as_slice(),
            &b"mif1".repeat(60),
            b"avis",
        ]
        .concat();
        let cases: [(&str, &[u8], bool); 6] = [
            (
                "animation brand past the scan",
                &brands_past_the_scan,
                false,
            ),
            (
                "still",
                b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf",
                true,
            ),
            (
                "still without compatible brands",
                b"\x00\x00\x00\x10ftypavif\x00\x00\x00\x00",
                true,
            ),
            (
                "animation",
                b"\x00\x00\x00\x20ftypavis\x00\x00\x00\x00avisavifmif1msf1",
                false,
            ),
            (
                "compatible brand only",
                b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00miafavif",
                false,
            ),
            (
                "still brand beside an animation brand",
                b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00avifavis",
                false,
            ),
        ];
        for (case, header, stored) in cases {
            let payload = STANDARD.encode(header);
            for (event, expected) in [
                (
                    format!(r#"{{"src":"data:image/avif;base64,{payload}"}}"#),
                    r#"{"src":"@"}"#,
                ),
                (
                    format!(r#"{{"src":"data:image/png;base64,{payload}"}}"#),
                    r#"{"src":"@"}"#,
                ),
                // A line-wrapped payload is cut out whole, with the break in the `ftyp` box or after it.
                (
                    format!(
                        r#"{{"src":"data:image/png;base64,{}\n{}"}}"#,
                        &payload[..8],
                        &payload[8..]
                    ),
                    r#"{"src":"@"}"#,
                ),
                (
                    format!(
                        r#"{{"src":"data:image/avif;base64,{}\n{}"}}"#,
                        &payload[..16],
                        &payload[16..]
                    ),
                    r#"{"src":"@"}"#,
                ),
                // A short, padded payload before a srcset descriptor.
                (
                    format!(r#"{{"srcset":"data:image/png;base64,{payload} 100w"}}"#),
                    r#"{"srcset":"@ 100w"}"#,
                ),
            ] {
                let mut images = sink(ImageLimits::default());
                let out = extract_images(event.as_bytes(), &mut images);
                let replacement = match images.images.as_slice() {
                    [image] if stored => {
                        assert_eq!(
                            (image.mime.as_str(), image.bytes.as_slice()),
                            ("image/avif", header),
                            "{case}: {event}"
                        );
                        image.reference.clone()
                    }
                    [] if !stored => {
                        assert_eq!(
                            images.declined,
                            declined(ImageDecline::Avif),
                            "{case}: {event}"
                        );
                        ImageDecline::Avif.marker().to_owned()
                    }
                    other => panic!("{case}: {event} stored {} images", other.len()),
                };
                assert_eq!(
                    String::from_utf8_lossy(&out),
                    expected.replace('@', &replacement),
                    "{case}: {event}"
                );
            }
        }
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
                ImageDecline::OverLimit.marker()
            )
        );
        assert_eq!(
            (images.images.len(), images.declined),
            (1, declined(ImageDecline::OverLimit))
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
        let unbroken = format!("{};", "data:image/".repeat(200_000));
        let mut images = sink(ImageLimits::default());
        assert!(matches!(
            extract_images(unbroken.as_bytes(), &mut images),
            Cow::Borrowed(_)
        ));
        let escaped_tabs = format!("d{}x\"", r"\\9 ".repeat(200_000));
        let mut images = sink(ImageLimits::default());
        assert!(matches!(
            extract_images(escaped_tabs.as_bytes(), &mut images),
            Cow::Borrowed(_)
        ));
        assert!(started.elapsed() < std::time::Duration::from_secs(5));
    }
}
