//! Byte-level JSON span scanning: locate values, iterate object entries and array items, and read
//! scalars without building a tree. Powers the streaming rewrite in [`crate::snapshot`], which memcpys
//! pass-through spans and parses only the spans it must scrub (the MLHog labeling worker pioneered
//! this shape).
//!
//! The scanners assume structurally valid JSON (the payload is re-serialized by capture upstream) and
//! only report *structural* failures (unbalanced brackets, truncation). They never unescape strings;
//! callers that need decoded text use [`unescape`], and callers that meet an escaped **key** must fall
//! back to a real parse — a `\uXXXX` key could alias a routing key, and byte comparison would miss it.

/// Half-open byte range into the scanned buffer.
pub type Span = (usize, usize);

#[derive(Debug, PartialEq, Eq)]
pub struct ScanError(pub &'static str);

type Result<T> = std::result::Result<T, ScanError>;

fn is_ws(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | b'\r')
}

pub fn skip_ws(bytes: &[u8], mut pos: usize) -> usize {
    while pos < bytes.len() && is_ws(bytes[pos]) {
        pos += 1;
    }
    pos
}

/// True when the little-endian 8-byte word contains a `"` or `\` byte (the classic SWAR
/// zero-byte test), letting scanners consume 8 bytes per step with no memchr per-call setup.
#[inline]
fn word_has_quote_or_backslash(word: u64) -> bool {
    const LO: u64 = 0x0101_0101_0101_0101;
    const HI: u64 = 0x8080_8080_8080_8080;
    let q = word ^ (LO * b'"' as u64);
    let b = word ^ (LO * b'\\' as u64);
    ((q.wrapping_sub(LO) & !q) | (b.wrapping_sub(LO) & !b)) & HI != 0
}

#[inline]
fn word_has_backslash(word: u64) -> bool {
    const LO: u64 = 0x0101_0101_0101_0101;
    const HI: u64 = 0x8080_8080_8080_8080;
    let b = word ^ (LO * b'\\' as u64);
    b.wrapping_sub(LO) & !b & HI != 0
}

#[inline]
fn read_word(bytes: &[u8], pos: usize) -> u64 {
    u64::from_le_bytes(bytes[pos..pos + 8].try_into().expect("8 bytes"))
}

/// Position of the next `\` in `bytes[pos..end]`, or `end`. Same SWAR-then-memchr shape as
/// [`skip_string`], for the unescapers' clean-run scans.
#[inline]
fn next_backslash(bytes: &[u8], mut pos: usize, end: usize) -> usize {
    let mut words = 0u32;
    while pos + 8 <= end && words < 4 {
        if word_has_backslash(read_word(bytes, pos)) {
            while bytes[pos] != b'\\' {
                pos += 1;
            }
            return pos;
        }
        pos += 8;
        words += 1;
    }
    if words == 4 {
        return memchr::memchr(b'\\', &bytes[pos..end]).map_or(end, |j| pos + j);
    }
    while pos < end {
        if bytes[pos] == b'\\' {
            return pos;
        }
        pos += 1;
    }
    end
}

/// `start` must be at an opening quote; returns the position just past the closing quote.
/// Each stretch is scanned SWAR-first (8-byte words, no per-call setup), escalating to memchr only
/// after 32 clean bytes: DOM JSON is mostly 5-20 byte strings and JSON-in-JSON has an escape every
/// ~15 bytes, so memchr-per-hop would be all setup — while long clean runs (blobs, base64 bodies)
/// still get real SIMD jumps.
pub fn skip_string(bytes: &[u8], start: usize) -> Result<usize> {
    debug_assert_eq!(bytes.get(start), Some(&b'"'));
    let mut pos = start + 1;
    'stretch: while pos < bytes.len() {
        let mut words = 0u32;
        while pos + 8 <= bytes.len() && words < 4 {
            if word_has_quote_or_backslash(read_word(bytes, pos)) {
                let word_end = pos + 8;
                while pos < word_end {
                    match bytes[pos] {
                        b'"' => return Ok(pos + 1),
                        b'\\' => {
                            pos += 2; // skip the escape and its payload byte
                            continue 'stretch;
                        }
                        _ => pos += 1,
                    }
                }
                continue 'stretch;
            }
            pos += 8;
            words += 1;
        }
        if words == 4 {
            // 32 clean bytes: a long run, worth memchr's setup.
            let Some(i) = memchr::memchr2(b'\\', b'"', &bytes[pos..]) else {
                break;
            };
            let at = pos + i;
            if bytes[at] == b'"' {
                return Ok(at + 1);
            }
            pos = at + 2;
            continue 'stretch;
        }
        // Tail: fewer than 8 bytes left.
        while pos < bytes.len() {
            match bytes[pos] {
                b'"' => return Ok(pos + 1),
                b'\\' => pos += 2,
                _ => pos += 1,
            }
        }
        break;
    }
    Err(ScanError("unterminated string"))
}

/// `start` must be at `open`; returns the position just past the matching `close`.
/// Stays bytewise between strings: `skip_string` already jumps string content, so the structural
/// gaps left here are a handful of bytes — too short for memchr's per-call setup to pay off
/// (measured: memchr3 here costs ~20% on bracket-dense mousemove payloads).
pub fn skip_balanced(bytes: &[u8], start: usize, open: u8, close: u8) -> Result<usize> {
    debug_assert_eq!(bytes.get(start), Some(&open));
    let mut depth: usize = 0;
    let mut pos = start;
    while pos < bytes.len() {
        let b = bytes[pos];
        if b == b'"' {
            pos = skip_string(bytes, pos)?;
            continue;
        }
        if b == open {
            depth += 1;
        } else if b == close {
            depth -= 1;
            if depth == 0 {
                return Ok(pos + 1);
            }
        }
        pos += 1;
    }
    Err(ScanError("unbalanced brackets"))
}

fn skip_scalar(bytes: &[u8], start: usize) -> usize {
    let mut pos = start;
    while pos < bytes.len() {
        let b = bytes[pos];
        if matches!(b, b',' | b'}' | b']') || is_ws(b) {
            return pos;
        }
        pos += 1;
    }
    pos
}

/// Span of the JSON value starting at (or after whitespace from) `start`.
pub fn locate_value(bytes: &[u8], start: usize) -> Result<Span> {
    let start = skip_ws(bytes, start);
    let end = match bytes.get(start) {
        Some(b'"') => skip_string(bytes, start)?,
        Some(b'{') => skip_balanced(bytes, start, b'{', b'}')?,
        Some(b'[') => skip_balanced(bytes, start, b'[', b']')?,
        Some(_) => skip_scalar(bytes, start),
        None => return Err(ScanError("expected a value")),
    };
    Ok((start, end))
}

/// One scanned object entry. `key` excludes the quotes and is *raw* (not unescaped);
/// `key_escaped` marks a backslash in the raw key — callers must treat such objects as unscannable.
pub struct Entry {
    pub key: Span,
    pub key_escaped: bool,
    pub value: Span,
}

/// Iterates the top-level entries of the object whose span is `obj` (must start at `{`).
pub struct ObjectEntries<'b> {
    bytes: &'b [u8],
    pos: usize,
    end: usize,
    done: bool,
    first: bool,
}

pub fn object_entries<'b>(bytes: &'b [u8], obj: Span) -> Result<ObjectEntries<'b>> {
    if bytes.get(obj.0) != Some(&b'{') {
        return Err(ScanError("not an object"));
    }
    Ok(ObjectEntries {
        bytes,
        pos: obj.0 + 1,
        end: obj.1,
        done: false,
        first: true,
    })
}

impl<'b> Iterator for ObjectEntries<'b> {
    type Item = Result<Entry>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.done {
            return None;
        }
        let bytes = self.bytes;
        let mut pos = skip_ws(bytes, self.pos);
        if pos + 1 == self.end && bytes.get(pos) == Some(&b'}') {
            self.done = true;
            return None;
        }
        if !self.first {
            if bytes.get(pos) != Some(&b',') {
                self.done = true;
                return Some(Err(ScanError("expected ',' between object entries")));
            }
            pos = skip_ws(bytes, pos + 1);
        }
        self.first = false;
        if bytes.get(pos) != Some(&b'"') {
            self.done = true;
            return Some(Err(ScanError("expected object key")));
        }
        let key_end = match skip_string(bytes, pos) {
            Ok(e) => e,
            Err(e) => {
                self.done = true;
                return Some(Err(e));
            }
        };
        let key = (pos + 1, key_end - 1);
        let key_escaped = bytes[key.0..key.1].contains(&b'\\');
        pos = skip_ws(bytes, key_end);
        if bytes.get(pos) != Some(&b':') {
            self.done = true;
            return Some(Err(ScanError("expected ':' after object key")));
        }
        let value = match locate_value(bytes, pos + 1) {
            Ok(v) => v,
            Err(e) => {
                self.done = true;
                return Some(Err(e));
            }
        };
        self.pos = value.1;
        Some(Ok(Entry {
            key,
            key_escaped,
            value,
        }))
    }
}

/// Iterates the top-level item spans of the array whose span is `arr` (must start at `[`).
pub struct ArrayItems<'b> {
    bytes: &'b [u8],
    pos: usize,
    end: usize,
    done: bool,
    first: bool,
}

pub fn array_items<'b>(bytes: &'b [u8], arr: Span) -> Result<ArrayItems<'b>> {
    if bytes.get(arr.0) != Some(&b'[') {
        return Err(ScanError("not an array"));
    }
    Ok(ArrayItems {
        bytes,
        pos: arr.0 + 1,
        end: arr.1,
        done: false,
        first: true,
    })
}

impl<'b> Iterator for ArrayItems<'b> {
    type Item = Result<Span>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.done {
            return None;
        }
        let bytes = self.bytes;
        let mut pos = skip_ws(bytes, self.pos);
        if pos + 1 == self.end && bytes.get(pos) == Some(&b']') {
            self.done = true;
            return None;
        }
        if !self.first {
            if bytes.get(pos) != Some(&b',') {
                self.done = true;
                return Some(Err(ScanError("expected ',' between array items")));
            }
            pos += 1;
        }
        self.first = false;
        let item = match locate_value(bytes, pos) {
            Ok(v) => v,
            Err(e) => {
                self.done = true;
                return Some(Err(e));
            }
        };
        self.pos = item.1;
        Some(Ok(item))
    }
}

/// Parse a scanned scalar span as a JSON number, mirroring what `JSON.parse` would produce (an f64).
/// Returns `None` for non-numbers. Accepts the full JSON number grammar (fractions, exponents); the
/// charset pre-check keeps Rust-isms like `inf`/`NaN` out.
pub fn parse_number(bytes: &[u8], span: Span) -> Option<f64> {
    let raw = bytes.get(span.0..span.1)?;
    let first = *raw.first()?;
    if first != b'-' && !first.is_ascii_digit() {
        return None;
    }
    if !raw
        .iter()
        .all(|b| b.is_ascii_digit() || matches!(b, b'-' | b'+' | b'.' | b'e' | b'E'))
    {
        return None;
    }
    std::str::from_utf8(raw).ok()?.parse::<f64>().ok()
}

/// True when the span is exactly the JSON literal `null`.
pub fn is_null(bytes: &[u8], span: Span) -> bool {
    bytes.get(span.0..span.1) == Some(b"null")
}

/// True when the span is a JSON string (starts with a quote).
pub fn is_string(bytes: &[u8], span: Span) -> bool {
    bytes.get(span.0) == Some(&b'"')
}

/// True when the span is a JSON object.
pub fn is_object(bytes: &[u8], span: Span) -> bool {
    bytes.get(span.0) == Some(&b'{')
}

/// True when the span is a JSON array.
pub fn is_array(bytes: &[u8], span: Span) -> bool {
    bytes.get(span.0) == Some(&b'[')
}

/// Decode a JSON string span (including its quotes), handling all JSON escapes including surrogate
/// pairs. Escape-free strings (the overwhelming majority) borrow the input — zero copy.
pub fn unescape<'b>(bytes: &'b [u8], span: Span) -> Result<std::borrow::Cow<'b, str>> {
    let raw = bytes
        .get(span.0..span.1)
        .ok_or(ScanError("string span out of range"))?;
    if raw.len() < 2 || raw[0] != b'"' || raw[raw.len() - 1] != b'"' {
        return Err(ScanError("not a string span"));
    }
    let inner = &raw[1..raw.len() - 1];
    if !inner.contains(&b'\\') {
        return std::str::from_utf8(inner)
            .map(std::borrow::Cow::Borrowed)
            .map_err(|_| ScanError("invalid utf-8 in string"));
    }
    let mut out = Vec::with_capacity(inner.len());
    let mut i = 0;
    while i < inner.len() {
        // Bulk-copy the clean run up to the next escape: one slice push per run, not per byte.
        let run_start = i;
        i = next_backslash(inner, i, inner.len());
        out.extend_from_slice(&inner[run_start..i]);
        if i >= inner.len() {
            break;
        }
        let esc = *inner.get(i + 1).ok_or(ScanError("truncated escape"))?;
        i += 2;
        match esc {
            b'"' => out.push(b'"'),
            b'\\' => out.push(b'\\'),
            b'/' => out.push(b'/'),
            b'b' => out.push(0x08),
            b'f' => out.push(0x0c),
            b'n' => out.push(b'\n'),
            b'r' => out.push(b'\r'),
            b't' => out.push(b'\t'),
            b'u' => {
                let (ch, consumed) = decode_unicode(inner, i)?;
                i += consumed;
                let mut buf = [0u8; 4];
                out.extend_from_slice(ch.encode_utf8(&mut buf).as_bytes());
            }
            _ => return Err(ScanError("bad escape")),
        }
    }
    String::from_utf8(out)
        .map(std::borrow::Cow::Owned)
        .map_err(|_| ScanError("invalid utf-8 in string"))
}

/// Decode the `XXXX` (possibly a surrogate pair `XXXX\uYYYY`) after a `\u`, `at` pointing at the
/// first hex digit. Returns the char and how many bytes were consumed.
fn decode_unicode(bytes: &[u8], at: usize) -> Result<(char, usize)> {
    let cp = hex4(bytes, at)?;
    if (0xD800..0xDC00).contains(&cp) {
        // High surrogate: pair it with the following \uXXXX low surrogate.
        if bytes.get(at + 4) == Some(&b'\\') && bytes.get(at + 5) == Some(&b'u') {
            let low = hex4(bytes, at + 6)?;
            if (0xDC00..0xE000).contains(&low) {
                let c = 0x10000 + ((cp as u32 - 0xD800) << 10) + (low as u32 - 0xDC00);
                let ch = char::from_u32(c).ok_or(ScanError("invalid surrogate pair"))?;
                return Ok((ch, 10));
            }
        }
        return Ok((char::REPLACEMENT_CHARACTER, 4));
    }
    if (0xDC00..0xE000).contains(&cp) {
        // Lone low surrogate.
        return Ok((char::REPLACEMENT_CHARACTER, 4));
    }
    char::from_u32(cp as u32)
        .map(|ch| (ch, 4))
        .ok_or(ScanError("invalid codepoint"))
}

/// Unescape a JSON string span (including quotes) *in place*: decoded bytes are written over the
/// span's own start (an unescaped string is never longer than its escaped form, so the write cursor
/// trails the read cursor). Returns the decoded byte length, starting at `span.0 + 1`.
///
/// The buffer past the decoded bytes is left as scrap — callers must treat the span as consumed.
/// The decoded bytes are NOT validated as UTF-8; callers that need a `str` must check.
pub fn unescape_in_place(bytes: &mut [u8], span: Span) -> Result<usize> {
    let raw_len = span.1.checked_sub(span.0).ok_or(ScanError("bad span"))?;
    if raw_len < 2 || bytes.get(span.0) != Some(&b'"') || bytes.get(span.1 - 1) != Some(&b'"') {
        return Err(ScanError("not a string span"));
    }
    let (start, end) = (span.0 + 1, span.1 - 1);
    let Some(first) = memchr::memchr(b'\\', &bytes[start..end]) else {
        return Ok(end - start); // escape-free: the bytes are already in place
    };
    let mut rd = start + first;
    let mut wr = rd;
    while rd < end {
        if bytes[rd] != b'\\' {
            // Clean run: locate its end, then one copy_within.
            let run_start = rd;
            rd = next_backslash(bytes, rd, end);
            bytes.copy_within(run_start..rd, wr);
            wr += rd - run_start;
            continue;
        }
        if rd + 1 >= end {
            return Err(ScanError("truncated escape"));
        }
        let esc = bytes[rd + 1];
        rd += 2;
        let simple = match esc {
            b'"' => b'"',
            b'\\' => b'\\',
            b'/' => b'/',
            b'b' => 0x08,
            b'f' => 0x0c,
            b'n' => b'\n',
            b'r' => b'\r',
            b't' => b'\t',
            b'u' => {
                let (ch, consumed) = decode_unicode(&bytes[..end], rd)?;
                rd += consumed;
                let mut buf = [0u8; 4];
                let encoded = ch.encode_utf8(&mut buf).as_bytes();
                bytes[wr..wr + encoded.len()].copy_from_slice(encoded);
                wr += encoded.len();
                continue;
            }
            _ => return Err(ScanError("bad escape")),
        };
        bytes[wr] = simple;
        wr += 1;
    }
    Ok(wr - start)
}

fn hex4(bytes: &[u8], at: usize) -> Result<u16> {
    let mut v: u16 = 0;
    for k in 0..4 {
        let d = (*bytes.get(at + k).ok_or(ScanError("truncated \\u escape"))? as char)
            .to_digit(16)
            .ok_or(ScanError("bad hex digit"))?;
        v = (v << 4) | d as u16;
    }
    Ok(v)
}

/// JSON-escape `s` into `out` as a quoted string, matching `JSON.stringify` byte-for-byte for the
/// escapes it emits (control chars as `\u00xx`, everything else verbatim UTF-8).
pub fn write_json_string(s: &str, out: &mut Vec<u8>) {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    out.push(b'"');
    for b in s.bytes() {
        match b {
            b'"' => out.extend_from_slice(b"\\\""),
            b'\\' => out.extend_from_slice(b"\\\\"),
            0x08 => out.extend_from_slice(b"\\b"),
            0x0c => out.extend_from_slice(b"\\f"),
            b'\n' => out.extend_from_slice(b"\\n"),
            b'\r' => out.extend_from_slice(b"\\r"),
            b'\t' => out.extend_from_slice(b"\\t"),
            0x00..=0x1f => out.extend_from_slice(&[
                b'\\',
                b'u',
                b'0',
                b'0',
                HEX[(b >> 4) as usize],
                HEX[(b & 0xf) as usize],
            ]),
            _ => out.push(b),
        }
    }
    out.push(b'"');
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entries(json: &str) -> Vec<(String, String)> {
        let bytes = json.as_bytes();
        let span = locate_value(bytes, 0).unwrap();
        object_entries(bytes, span)
            .unwrap()
            .map(|e| {
                let e = e.unwrap();
                (
                    String::from_utf8(bytes[e.key.0..e.key.1].to_vec()).unwrap(),
                    String::from_utf8(bytes[e.value.0..e.value.1].to_vec()).unwrap(),
                )
            })
            .collect()
    }

    #[test]
    fn object_scan_walks_nested_values_and_strings_with_brackets() {
        let got = entries(r#"{ "a" : {"x":[1,2,{"y":"}"}]}, "b":"[{", "c": -1.5e3 , "d": null }"#);
        assert_eq!(
            got,
            vec![
                ("a".into(), r#"{"x":[1,2,{"y":"}"}]}"#.into()),
                ("b".into(), r#""[{""#.into()),
                ("c".into(), "-1.5e3".into()),
                ("d".into(), "null".into()),
            ]
        );
    }

    #[test]
    fn array_scan_yields_item_spans() {
        let json = br#"[ {"a":1}, "two", 3, [4], null ]"#;
        let span = locate_value(json, 0).unwrap();
        let items: Vec<String> = array_items(json, span)
            .unwrap()
            .map(|s| {
                let s = s.unwrap();
                String::from_utf8(json[s.0..s.1].to_vec()).unwrap()
            })
            .collect();
        assert_eq!(items, vec![r#"{"a":1}"#, r#""two""#, "3", "[4]", "null"]);
    }

    #[test]
    fn malformed_structures_error_rather_than_hang_or_panic() {
        for bad in [
            r#"{"a" 1}"#,       // missing colon
            r#"{"a":1 "b":2}"#, // missing comma
            r#"{"a":"unterminated"#,
            r#"[1 2]"#,
            r#"{"a":{"#,
        ] {
            let bytes = bad.as_bytes();
            let Ok(span) = locate_value(bytes, 0) else {
                continue; // structurally rejected up front is fine too
            };
            let result: std::result::Result<(), ScanError> = if bad.starts_with('{') {
                match object_entries(bytes, span) {
                    Ok(mut it) => it.try_for_each(|r| r.map(|_| ())),
                    Err(e) => Err(e),
                }
            } else {
                match array_items(bytes, span) {
                    Ok(mut it) => it.try_for_each(|r| r.map(|_| ())),
                    Err(e) => Err(e),
                }
            };
            assert!(result.is_err(), "should reject: {bad}");
        }
    }

    #[test]
    fn number_parsing_matches_json_semantics() {
        let cases: &[(&str, Option<f64>)] = &[
            ("1234", Some(1234.0)),
            ("-1.5", Some(-1.5)),
            ("1.7e12", Some(1.7e12)),
            ("2E+2", Some(200.0)),
            ("1e999", Some(f64::INFINITY)), // JSON.parse("1e999") -> Infinity
            ("\"str\"", None),
            ("null", None),
            ("true", None),
            ("NaN", None),
        ];
        for (raw, expected) in cases {
            let got = parse_number(raw.as_bytes(), (0, raw.len()));
            assert_eq!(got, *expected, "case: {raw}");
        }
    }

    #[test]
    fn unescape_handles_escapes_and_surrogate_pairs() {
        let cases: &[(&str, &str)] = &[
            (r#""plain""#, "plain"),
            (r#""a\nb\t\"c\"""#, "a\nb\t\"c\""),
            (r#""é$""#, "é$"),
            (r#""😀""#, "😀"),
            (r#""\ud800x""#, "\u{FFFD}x"), // lone high surrogate
        ];
        for (raw, expected) in cases {
            let got = unescape(raw.as_bytes(), (0, raw.len())).unwrap();
            assert_eq!(&got, expected, "case: {raw}");
        }
    }

    #[test]
    fn write_json_string_round_trips_through_serde() {
        for s in ["plain", "with \"quotes\" and \\", "ctl\u{1}\n\t", "π😀"] {
            let mut out = Vec::new();
            write_json_string(s, &mut out);
            let parsed: String = serde_json::from_slice(&out).unwrap();
            assert_eq!(parsed, s);
        }
    }

    #[test]
    fn escaped_keys_are_flagged() {
        // `data` parses to the key `data`; a byte scanner can't see that, so it must flag the
        // escape and let the caller fall back to a real parse instead of missing a routing key.
        let json = br#"{"\u0064ata": 1}"#;
        let span = locate_value(json, 0).unwrap();
        let e = object_entries(json, span).unwrap().next().unwrap().unwrap();
        assert!(e.key_escaped, "escaped key must be flagged for fallback");
    }
}
