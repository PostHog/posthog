//! Case-insensitive allow lists of text words and URL path segments kept verbatim by the scrubbers.
//! Mirrors `anonymize/allow-lists.ts`.

// The lookups run once per word token of every text node; ahash beats SipHash on short strings and
// the sets are built from operator-controlled config, so hash-DoS resistance buys nothing here.
use ahash::AHashSet;

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
    text: AHashSet<String>,
    url: AHashSet<String>,
    /// Bit i set = the text set contains a word of byte length i (lengths >= 63 share bit 63).
    /// Most redacted tokens miss the mask and skip the hash entirely.
    text_lens: u64,
    url_lens: u64,
}

fn len_bit(s: &str) -> u64 {
    1u64 << s.len().min(63)
}

impl AllowLists {
    pub fn new<I, J>(text: I, url: J) -> Self
    where
        I: IntoIterator,
        I::Item: AsRef<str>,
        J: IntoIterator,
        J::Item: AsRef<str>,
    {
        let text: AHashSet<String> = text
            .into_iter()
            .map(|w| ascii_lowercase(w.as_ref()))
            .collect();
        let url: AHashSet<String> = url
            .into_iter()
            .map(|s| ascii_lowercase(s.as_ref()))
            .collect();
        let text_lens = text.iter().map(|w| len_bit(w)).fold(0, |a, b| a | b);
        let url_lens = url.iter().map(|w| len_bit(w)).fold(0, |a, b| a | b);
        Self {
            text,
            url,
            text_lens,
            url_lens,
        }
    }

    pub fn text_contains(&self, word: &str) -> bool {
        if self.text_lens & len_bit(word) == 0 {
            return false;
        }
        if has_upper_ascii(word) {
            self.text.contains(&ascii_lowercase(word))
        } else {
            self.text.contains(word)
        }
    }

    pub fn url_contains(&self, segment: &str) -> bool {
        if self.url_lens & len_bit(segment) == 0 {
            return false;
        }
        if has_upper_ascii(segment) {
            self.url.contains(&ascii_lowercase(segment))
        } else {
            self.url.contains(segment)
        }
    }
}
