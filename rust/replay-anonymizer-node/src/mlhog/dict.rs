// Copied (extracted) from MLHog prep/labeling/src/dict.rs — bench-only. Only the `AllowLists`
// struct with `new`/`text_contains`/`url_contains`; the JSON file loader, `Default` impl and the
// ~2000-line in-binary default word lists are intentionally not ported.

use rustc_hash::FxHashSet;

#[derive(Debug, Clone)]
pub struct AllowLists {
    text: FxHashSet<String>,
    url: FxHashSet<String>,
}

impl AllowLists {
    pub fn new<I, J, S>(text: I, url: J) -> Self
    where
        I: IntoIterator<Item = S>,
        J: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        Self {
            text: text
                .into_iter()
                .map(|s| s.as_ref().to_ascii_lowercase())
                .collect(),
            url: url
                .into_iter()
                .map(|s| s.as_ref().to_ascii_lowercase())
                .collect(),
        }
    }

    pub fn text_contains(&self, word: &str) -> bool {
        if word.bytes().all(|b| !b.is_ascii_uppercase()) {
            return self.text.contains(word);
        }
        self.text.contains(&word.to_ascii_lowercase())
    }

    pub fn url_contains(&self, segment: &str) -> bool {
        if segment.bytes().all(|b| !b.is_ascii_uppercase()) {
            return self.url.contains(segment);
        }
        self.url.contains(&segment.to_ascii_lowercase())
    }
}
