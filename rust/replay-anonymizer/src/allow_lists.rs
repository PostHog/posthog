//! Case-insensitive allow lists of text words and URL path segments kept verbatim by the scrubbers.
//! Mirrors `anonymize/allow-lists.ts`.

// The lookups run once per word token of every text node; ahash beats SipHash on short strings and
// the sets are built from operator-controlled config, so hash-DoS resistance buys nothing here.
use ahash::AHashSet;
use anyhow::{Context, Result};
use serde::Deserialize;

/// Bounds for an untrusted allow-list document, mirroring the TS loader's hygiene
/// (`anonymize/allow-list-loader.ts`): a malformed or huge file cannot exhaust memory.
const MAX_ALLOW_LIST_ENTRIES: usize = 500_000;
const MAX_ALLOW_LIST_ENTRY_LEN: usize = 256;

// The TS pipeline's fail-safe default lists (`anonymize/default-dict.ts`), embedded so offline
// consumers with no access to the shipped allow lists scrub with production-equivalent vocabulary
// instead of redacting everything. `default_lists_match_the_ts_pipeline` keeps the copies in sync.
const DEFAULT_TEXT_WORDS: &str = include_str!("default_text_words.txt");
const DEFAULT_URL_SEGMENTS: &str = include_str!("default_url_segments.txt");

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

#[derive(Debug)]
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

/// The production default lists (English stopwords/UI vocabulary + safe URL segments) — the same
/// fallback the TS pipeline uses when the shipped lists can't be loaded. Consumers with explicit
/// lists should prefer [`AllowLists::from_json_bytes`]; [`AllowLists::new`] stays available for
/// deliberate empty construction (redact everything).
impl Default for AllowLists {
    fn default() -> Self {
        Self::new(DEFAULT_TEXT_WORDS.lines(), DEFAULT_URL_SEGMENTS.lines())
    }
}

#[derive(Deserialize)]
struct RawAllowLists {
    #[serde(default)]
    text: Option<serde_json::Value>,
    #[serde(default)]
    url: Option<serde_json::Value>,
}

/// The TS loader's sanitize pass: keep only string entries within the length bound, cap the count.
fn sanitize_entries(raw: Option<serde_json::Value>) -> Vec<String> {
    let Some(serde_json::Value::Array(items)) = raw else {
        return Vec::new();
    };
    items
        .into_iter()
        .filter_map(|v| match v {
            serde_json::Value::String(s) if s.len() <= MAX_ALLOW_LIST_ENTRY_LEN => Some(s),
            _ => None,
        })
        .take(MAX_ALLOW_LIST_ENTRIES)
        .collect()
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

    /// Parse the `{ "text": [...], "url": [...] }` allow-list document PostHog ships (the shape
    /// the Node addon loads from S3), with the TS loader's sanitize limits: non-string and
    /// over-long entries are dropped, each list is capped at 500k entries. Missing or non-array
    /// fields become empty lists (fail-safe: over-redaction, never under-redaction); only invalid
    /// JSON is an error.
    pub fn from_json_bytes(bytes: &[u8]) -> Result<Self> {
        let raw: RawAllowLists = serde_json::from_slice(bytes).context("parse allow-lists json")?;
        Ok(Self::new(
            sanitize_entries(raw.text),
            sanitize_entries(raw.url),
        ))
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;
    use std::path::Path;

    #[test]
    fn from_json_bytes_sanitizes_like_the_ts_loader() {
        let long = "x".repeat(MAX_ALLOW_LIST_ENTRY_LEN + 1);
        let doc = serde_json::json!({
            "text": ["Hello", 42, null, long, "world"],
            "url": ["Api"],
        });
        let allow = AllowLists::from_json_bytes(&serde_json::to_vec(&doc).unwrap()).unwrap();
        // Kept entries match case-insensitively, exactly like `AllowLists::new`.
        assert!(allow.text_contains("hello") && allow.text_contains("HELLO"));
        assert!(allow.text_contains("world"));
        assert!(allow.url_contains("api") && allow.url_contains("API"));
        // Non-string and over-long entries are dropped, not kept and not fatal.
        assert!(!allow.text_contains(&long));
        assert!(!allow.text_contains("42"));

        // Missing/non-array fields fail safe to empty lists; only invalid JSON errors.
        let empty = AllowLists::from_json_bytes(br#"{"text": "not an array"}"#).unwrap();
        assert!(!empty.text_contains("hello"));
        assert!(AllowLists::from_json_bytes(b"{nope").is_err());
    }

    #[test]
    fn defaults_allow_stopwords_and_still_redact_names() {
        let allow = AllowLists::default();
        // A word from the TS `DEFAULT_TEXT_WORDS` and a segment from `DEFAULT_URL_SEGMENTS`.
        assert!(allow.text_contains("the"));
        assert!(allow.url_contains("api"));
        assert_eq!(
            crate::text::scrub_text(&allow, "John Fakename accepted the request"),
            Some("**** ******** accepted the request".to_string()),
            "names must still redact under the default lists"
        );
    }

    /// Re-derives the default lists from the TS source when the monorepo checkout is present (CI
    /// runs there); a published crate tarball carries no TS file, so the check no-ops for
    /// crates.io consumers.
    #[test]
    fn default_lists_match_the_ts_pipeline() {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../nodejs/src/ingestion/pipelines/sessionreplay/anonymize/default-dict.ts");
        let Ok(ts) = std::fs::read_to_string(&path) else {
            return;
        };
        let mut text: BTreeSet<&str> = BTreeSet::new();
        let mut url: BTreeSet<&str> = BTreeSet::new();
        let mut current: Option<&mut BTreeSet<&str>> = None;
        for line in ts.lines() {
            if line.contains("DEFAULT_TEXT_WORDS") {
                current = Some(&mut text);
            } else if line.contains("DEFAULT_URL_SEGMENTS") {
                current = Some(&mut url);
            } else if line.starts_with(']') {
                current = None;
            } else if let Some(set) = current.as_mut() {
                let entry = line.trim();
                if let Some(word) = entry
                    .strip_prefix('\'')
                    .and_then(|e| e.strip_suffix("',"))
                    .or_else(|| entry.strip_prefix('"').and_then(|e| e.strip_suffix("\",")))
                {
                    set.insert(word);
                }
            }
        }
        assert!(text.len() > 1000, "TS parse must find the word list");
        let embedded = |s: &'static str| s.lines().collect::<BTreeSet<_>>();
        assert_eq!(
            embedded(DEFAULT_TEXT_WORDS),
            text,
            "default_text_words.txt is out of sync with default-dict.ts"
        );
        assert_eq!(
            embedded(DEFAULT_URL_SEGMENTS),
            url,
            "default_url_segments.txt is out of sync with default-dict.ts"
        );
    }
}
