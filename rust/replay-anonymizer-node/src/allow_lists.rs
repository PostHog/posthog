//! Case-insensitive allow lists of text words and URL path segments kept verbatim by the scrubbers.
//! Mirrors `anonymize/allow-lists.ts`.

use std::collections::HashSet;

fn has_upper_ascii(s: &str) -> bool {
    s.bytes().any(|b| b.is_ascii_uppercase())
}

fn ascii_lowercase(s: &str) -> String {
    // Only ASCII A-Z is folded, exactly like the TS (which does not lowercase non-ASCII).
    let mut out = String::with_capacity(s.len());
    for ch in s.chars() {
        if ch.is_ascii_uppercase() {
            out.push(ch.to_ascii_lowercase());
        } else {
            out.push(ch);
        }
    }
    out
}

#[derive(Debug, Default)]
pub struct AllowLists {
    text: HashSet<String>,
    url: HashSet<String>,
}

impl AllowLists {
    pub fn new<I, J>(text: I, url: J) -> Self
    where
        I: IntoIterator,
        I::Item: AsRef<str>,
        J: IntoIterator,
        J::Item: AsRef<str>,
    {
        Self {
            text: text
                .into_iter()
                .map(|w| ascii_lowercase(w.as_ref()))
                .collect(),
            url: url
                .into_iter()
                .map(|s| ascii_lowercase(s.as_ref()))
                .collect(),
        }
    }

    pub fn text_contains(&self, word: &str) -> bool {
        if has_upper_ascii(word) {
            self.text.contains(&ascii_lowercase(word))
        } else {
            self.text.contains(word)
        }
    }

    pub fn url_contains(&self, segment: &str) -> bool {
        if has_upper_ascii(segment) {
            self.url.contains(&ascii_lowercase(segment))
        } else {
            self.url.contains(segment)
        }
    }
}
