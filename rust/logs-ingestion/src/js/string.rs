//! JavaScript strings, which are UTF-16 and can hold a lone surrogate.
//!
//! `JSON.parse('"\\ud800"')` and `str.slice(0, n)` across an emoji both make a lone surrogate.
//! `JSON.stringify` writes it back as `\ud800`, and `Buffer.from` writes it as U+FFFD. A Rust
//! `String` cannot hold it, so `JsString` stores WTF-8: UTF-8 that also encodes a lone surrogate
//! as its 3-byte generalized form (ED A0 80 to ED BF BF).

use std::borrow::Cow;
use std::fmt;

#[derive(Clone, PartialEq, Eq, Hash, Default, PartialOrd, Ord)]
pub struct JsString {
    /// WTF-8. Valid UTF-8 exactly when `lone_surrogates` is 0.
    bytes: Vec<u8>,
    /// The number of lone surrogates in `bytes`, so a joined pair needs no rescan.
    lone_surrogates: usize,
}

impl JsString {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            bytes: Vec::with_capacity(capacity),
            lone_surrogates: 0,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        if self.lone_surrogates > 0 {
            None
        } else {
            // SAFETY: without a lone surrogate the bytes are valid UTF-8 by construction.
            // A checked conversion would scan the whole string on every comparison and lookup.
            // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
            Some(unsafe { std::str::from_utf8_unchecked(&self.bytes) })
        }
    }

    /// The text as `Buffer.from(str)` would encode it: each lone surrogate becomes U+FFFD.
    pub fn to_utf8_lossy(&self) -> Cow<'_, str> {
        match self.as_str() {
            Some(s) => Cow::Borrowed(s),
            None => {
                let mut out = String::with_capacity(self.bytes.len());
                for unit in self.chars_or_surrogates() {
                    match unit {
                        CharOrSurrogate::Char(c) => out.push(c),
                        CharOrSurrogate::Surrogate(_) => out.push('\u{FFFD}'),
                    }
                }
                Cow::Owned(out)
            }
        }
    }

    pub fn into_string_lossy(self) -> String {
        if self.lone_surrogates > 0 {
            self.to_utf8_lossy().into_owned()
        } else {
            // SAFETY: as in `as_str`.
            // nosemgrep: rust.lang.security.unsafe-usage.unsafe-usage
            unsafe { String::from_utf8_unchecked(self.bytes) }
        }
    }

    pub fn push_str(&mut self, s: &str) {
        self.bytes.extend_from_slice(s.as_bytes());
    }

    pub fn push(&mut self, c: char) {
        let mut buf = [0u8; 4];
        self.bytes
            .extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
    }

    pub fn push_js(&mut self, other: &JsString) {
        // A join can happen only at the seam, so the bytes copy unless the seam joins.
        if other.lone_surrogates == 0
            || !other.starts_with_low_surrogate()
            || self.trailing_high_surrogate().is_none()
        {
            self.bytes.extend_from_slice(&other.bytes);
            self.lone_surrogates += other.lone_surrogates;
            return;
        }
        for unit in other.chars_or_surrogates() {
            match unit {
                CharOrSurrogate::Char(c) => self.push(c),
                CharOrSurrogate::Surrogate(s) => self.push_code_unit(s),
            }
        }
    }

    /// Appends one UTF-16 code unit. A low surrogate after a lone high surrogate joins it into
    /// one code point, as concatenation does in JavaScript.
    pub fn push_code_unit(&mut self, unit: u16) {
        if !(0xD800..=0xDFFF).contains(&unit) {
            self.push(char::from_u32(unit as u32).expect("non-surrogate unit is a char"));
            return;
        }
        if (0xDC00..=0xDFFF).contains(&unit) {
            if let Some(high) = self.trailing_high_surrogate() {
                self.bytes.truncate(self.bytes.len() - 3);
                let cp = 0x10000 + (((high as u32) - 0xD800) << 10) + ((unit as u32) - 0xDC00);
                self.push(char::from_u32(cp).expect("surrogate pair is a char"));
                self.lone_surrogates -= 1;
                return;
            }
        }
        self.bytes.push(0xE0 | ((unit >> 12) as u8));
        self.bytes.push(0x80 | (((unit >> 6) & 0x3F) as u8));
        self.bytes.push(0x80 | ((unit & 0x3F) as u8));
        self.lone_surrogates += 1;
    }

    fn trailing_high_surrogate(&self) -> Option<u16> {
        let n = self.bytes.len();
        if self.lone_surrogates == 0 || n < 3 {
            return None;
        }
        let b = &self.bytes[n - 3..];
        if b[0] == 0xED && (0xA0..=0xAF).contains(&b[1]) {
            Some(0xD000 | (((b[1] & 0x3F) as u16) << 6) | ((b[2] & 0x3F) as u16))
        } else {
            None
        }
    }

    fn starts_with_low_surrogate(&self) -> bool {
        matches!(self.bytes.as_slice(), [0xED, 0xB0..=0xBF, ..])
    }

    /// Cuts back to `len` bytes, where `lone_surrogates` is the count that the prefix had.
    pub(crate) fn truncate_to(&mut self, len: usize, lone_surrogates: usize) {
        self.bytes.truncate(len);
        self.lone_surrogates = lone_surrogates;
    }

    pub(crate) fn lone_surrogate_count(&self) -> usize {
        self.lone_surrogates
    }

    pub fn utf16_len(&self) -> usize {
        match self.as_str() {
            Some(s) => utf16_len(s),
            None => self
                .chars_or_surrogates()
                .map(|u| match u {
                    CharOrSurrogate::Char(c) => c.len_utf16(),
                    CharOrSurrogate::Surrogate(_) => 1,
                })
                .sum(),
        }
    }

    pub fn utf16_slice(&self, start: usize, end: usize) -> JsString {
        let mut out = JsString::new();
        let mut pos = 0usize;
        for unit in self.chars_or_surrogates() {
            if pos >= end {
                break;
            }
            match unit {
                CharOrSurrogate::Char(c) => {
                    let mut buf = [0u16; 2];
                    for &u in c.encode_utf16(&mut buf).iter() {
                        if pos >= start && pos < end {
                            out.push_code_unit(u);
                        }
                        pos += 1;
                    }
                }
                CharOrSurrogate::Surrogate(s) => {
                    if pos >= start && pos < end {
                        out.push_code_unit(s);
                    }
                    pos += 1;
                }
            }
        }
        out
    }

    pub fn bytes_wtf8(&self) -> &[u8] {
        &self.bytes
    }

    pub fn is_empty(&self) -> bool {
        self.bytes.is_empty()
    }

    pub fn chars_or_surrogates(&self) -> impl Iterator<Item = CharOrSurrogate> + '_ {
        Wtf8Iter {
            bytes: &self.bytes,
            pos: 0,
        }
    }

    /// `Buffer.byteLength(str)`: the UTF-8 length, three bytes per lone surrogate.
    pub fn utf8_byte_len(&self) -> usize {
        // WTF-8 encodes a lone surrogate in three bytes, the same as U+FFFD.
        self.bytes.len()
    }
}

pub enum CharOrSurrogate {
    Char(char),
    Surrogate(u16),
}

impl CharOrSurrogate {
    pub fn as_char(&self) -> Result<char, u16> {
        match self {
            CharOrSurrogate::Char(c) => Ok(*c),
            CharOrSurrogate::Surrogate(s) => Err(*s),
        }
    }
}

struct Wtf8Iter<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl Iterator for Wtf8Iter<'_> {
    type Item = CharOrSurrogate;

    fn next(&mut self) -> Option<CharOrSurrogate> {
        let b = self.bytes;
        let i = self.pos;
        if i >= b.len() {
            return None;
        }
        let first = b[i];
        let (cp, len) = if first < 0x80 {
            (first as u32, 1)
        } else if first < 0xE0 {
            (
                (((first & 0x1F) as u32) << 6) | ((b[i + 1] & 0x3F) as u32),
                2,
            )
        } else if first < 0xF0 {
            (
                (((first & 0x0F) as u32) << 12)
                    | (((b[i + 1] & 0x3F) as u32) << 6)
                    | ((b[i + 2] & 0x3F) as u32),
                3,
            )
        } else {
            (
                (((first & 0x07) as u32) << 18)
                    | (((b[i + 1] & 0x3F) as u32) << 12)
                    | (((b[i + 2] & 0x3F) as u32) << 6)
                    | ((b[i + 3] & 0x3F) as u32),
                4,
            )
        };
        self.pos += len;
        Some(match char::from_u32(cp) {
            Some(c) => CharOrSurrogate::Char(c),
            None => CharOrSurrogate::Surrogate(cp as u16),
        })
    }
}

impl From<&str> for JsString {
    fn from(s: &str) -> Self {
        Self {
            bytes: s.as_bytes().to_vec(),
            lone_surrogates: 0,
        }
    }
}

impl From<String> for JsString {
    fn from(s: String) -> Self {
        Self {
            bytes: s.into_bytes(),
            lone_surrogates: 0,
        }
    }
}

impl fmt::Debug for JsString {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Debug::fmt(&self.to_utf8_lossy(), f)
    }
}

impl fmt::Display for JsString {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.to_utf8_lossy())
    }
}

impl PartialEq<str> for JsString {
    fn eq(&self, other: &str) -> bool {
        self.as_str() == Some(other)
    }
}

impl PartialEq<&str> for JsString {
    fn eq(&self, other: &&str) -> bool {
        self.as_str() == Some(*other)
    }
}

pub fn utf16_len(s: &str) -> usize {
    if s.is_ascii() {
        return s.len();
    }
    s.chars().map(char::len_utf16).sum()
}

/// `str.slice(0, end)` written out as `Buffer.from` would: a split surrogate pair leaves a
/// lone high surrogate, which becomes U+FFFD. Use it only where the slice goes straight to
/// bytes, such as the pattern output cap; use `JsString::utf16_slice` where it can reach
/// `JSON.stringify`.
pub fn utf16_slice_lossy(s: &str, start: usize, end: usize) -> String {
    if s.is_ascii() {
        let end = end.min(s.len());
        let start = start.min(end);
        return s[start..end].to_string();
    }
    JsString::from(s)
        .utf16_slice(start, end)
        .into_string_lossy()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slicing_an_emoji_leaves_a_lone_surrogate() {
        let s = JsString::from("a🚀b");
        assert_eq!(s.utf16_len(), 4);
        let cut = s.utf16_slice(0, 2);
        assert_eq!(cut.utf16_len(), 2);
        assert!(cut.as_str().is_none());
        assert_eq!(cut.to_utf8_lossy(), "a\u{FFFD}");
        assert_eq!(utf16_slice_lossy("a🚀b", 0, 2), "a\u{FFFD}");
    }

    #[test]
    fn a_split_pair_rejoins_on_concatenation() {
        let s = JsString::from("🚀");
        let mut joined = s.utf16_slice(0, 1);
        joined.push_js(&s.utf16_slice(1, 2));
        assert_eq!(joined, JsString::from("🚀"));
        assert!(joined.as_str().is_some());

        let mut mixed = JsString::new();
        mixed.push_code_unit(0xD800);
        mixed.push_code_unit(0xD83D);
        mixed.push_code_unit(0xDE80);
        assert!(mixed.as_str().is_none(), "the first lone surrogate remains");
        assert_eq!(mixed.to_utf8_lossy(), "\u{FFFD}🚀");
    }
}
