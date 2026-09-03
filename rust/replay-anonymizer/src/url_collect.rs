//! Collect the original URLs of remote images, for the out-of-band fetch lane.
//!
//! The sibling of [`crate::collect`]. That module handles an image the page inlined into the
//! recording; this one handles an image the page referred to by URL. With collection enabled, a
//! media source attribute holding an `http(s)` URL keeps the media placeholder and a namespaced
//! sibling attribute carries the content ref. The message also carries the original URL back to
//! the caller.
//!
//! **Two forms of one URL come out of this module. Do not confuse them.**
//!
//! The *dedup* URL is canonical, and its volatile parameters are removed. It is the only input to
//! the hash, so it sets the ref and the dedup key of the fetch lane.
//!
//! The *fetch* URL keeps the original query bytes, and every permitted parameter stays. The
//! fetcher requests this one. URLs that carry credentials or signatures are refused before either
//! form is created.
//!
//! That split is what makes the ref stable across non-credential cache busters. A ref that appears
//! once joins to nothing downstream. Removing the volatile parameters matters more for that than
//! it does for the request count.
//!
//! The hash is a *keyed* HMAC. The caller derives one global URL key from the KMS-held secret. The
//! secret does not leave the ingester.

use std::collections::{HashMap, HashSet};

use base64::Engine;
use hmac::{Hmac, Mac};
use sha2::Sha256;

use crate::url_policy::{try_canonicalize, MAX_URL_LEN};
/// Distinct raw values one message may memoize.
///
/// Larger than [`MAX_URLS_PER_MESSAGE`] on purpose, because the memo also holds the values this
/// collector declined, and a decline is exactly what a repeat should not pay for twice. Past this
/// the memo stops growing and repeats fall back to the full check, which is slower and bounded
/// rather than unbounded.
const MAX_MEMO_ENTRIES: usize = 2048;

/// Distinct URLs collected from one message.
///
/// One message holds a batch of rrweb events for one session, so this budget covers a full snapshot
/// and every mutation after it, including those describing a different page after a navigation. A
/// message at the cap loses its later images rather than its least useful ones.
///
/// What bounds it is the payload: the whole set crosses the FFI boundary in one call, and each URL
/// can be [`MAX_URL_LEN`] bytes. Read ml_urls_declined{reason="over_cap"} against ml_urls_collected
/// before changing it, and keep [`MAX_MEMO_ENTRIES`] above it.
pub const MAX_URLS_PER_MESSAGE: usize = 512;

/// Enables URL collection for one anonymize call.
#[derive(Debug, Clone)]
pub struct UrlCollection {
    /// Global key for the URL HMAC. The caller derives it under a URL-specific domain separator.
    pub url_key: String,
}

/// One collected URL, on its way to the fetch topic.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CollectedUrl {
    /// First 22 base64url chars of `HMAC-SHA256(url_key, dedup_url)`.
    pub hash: String,
    /// The URL with its original query bytes intact. This is what the fetcher requests.
    pub url: String,
    /// The host the request goes to. robots.txt and the connection limit are scoped to this.
    pub host: String,
    /// The registrable domain of `host`, which the fetch topic uses as its Kafka key so every URL
    /// of one operator lands on one partition. See `url_policy::politeness_key`.
    pub domain: String,
}

/// First 22 base64url chars of `HMAC-SHA256(url_key, dedup_url)`. Same construction and width as
/// [`crate::collect::hash_image_bytes`], but carried under the `imageurl:` prefix, because this
/// hash names a URL rather than the bytes behind it.
pub fn hash_url(url_key: &[u8], dedup_url: &str) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(url_key).expect("hmac accepts any key length");
    mac.update(dedup_url.as_bytes());
    let digest = mac.finalize().into_bytes();
    let mut b64 = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(digest);
    b64.truncate(22);
    b64
}

/// Accumulates the remote image URLs of one message, deduplicated on the hash.
pub struct UrlCollector {
    url_key: String,
    urls: Vec<CollectedUrl>,
    seen: HashSet<String>,
    /// One image recurs many times in a message, so a repeat must not pay a parse and an HMAC
    /// again. A page controls these keys, hence [`MAX_MEMO_ENTRIES`].
    memo: HashMap<String, Option<String>>,
    /// A refusal is invisible in the collected count, so the lane would look like traffic carries
    /// fewer images than it does.
    declines: HashMap<&'static str, u32>,
}

impl UrlCollector {
    pub fn new(collection: UrlCollection) -> Self {
        Self {
            url_key: collection.url_key,
            urls: Vec::new(),
            seen: HashSet::new(),
            memo: HashMap::new(),
            declines: HashMap::new(),
        }
    }

    /// Collect a remote image URL and return its ref, or `None` when the URL is not fetchable or a
    /// cap says this one stays on the placeholder path.
    pub fn collect(&mut self, raw: &str) -> Option<String> {
        if let Some(remembered) = self.memo.get(raw) {
            return remembered.clone();
        }
        if self.is_full() {
            self.decline("over_cap");
            return None;
        }
        let result = self.collect_uncached(raw);
        if self.is_worth_remembering(raw) {
            self.memo.insert(raw.to_string(), result.clone());
        }
        result
    }

    fn is_full(&self) -> bool {
        self.urls.len() >= MAX_URLS_PER_MESSAGE
    }

    /// An over-length value is refused by a length check alone, so remembering it would only store
    /// the longest strings a page offers.
    fn is_worth_remembering(&self, raw: &str) -> bool {
        raw.len() <= MAX_URL_LEN && self.memo.len() < MAX_MEMO_ENTRIES
    }

    fn decline(&mut self, reason: &'static str) {
        *self.declines.entry(reason).or_insert(0) += 1;
    }

    fn collect_uncached(&mut self, raw: &str) -> Option<String> {
        let canonical = match try_canonicalize(raw) {
            Ok(c) => c,
            Err(reason) => {
                self.decline(reason.label());
                return None;
            }
        };
        let hash = hash_url(self.url_key.as_bytes(), &canonical.dedup);
        if self.seen.contains(&hash) {
            return Some(crate::collect::url_ref(&hash));
        }
        self.seen.insert(hash.clone());
        self.urls.push(CollectedUrl {
            hash: hash.clone(),
            url: canonical.fetch,
            host: canonical.host,
            domain: canonical.domain,
        });
        Some(crate::collect::url_ref(&hash))
    }

    /// Counts by reason for the URLs this collector refused.
    pub fn into_declines(&self) -> Vec<(String, u32)> {
        let mut out: Vec<(String, u32)> = self
            .declines
            .iter()
            .map(|(k, v)| ((*k).to_string(), *v))
            .collect();
        out.sort_by(|a, b| a.0.cmp(&b.0));
        out
    }

    /// Drain, sorted by hash. A deterministic order that cannot depend on which engine walked the
    /// message, which is what lets the differential tests compare meta directly.
    pub fn into_urls(mut self) -> Vec<CollectedUrl> {
        self.urls.sort_by(|a, b| a.hash.cmp(&b.hash));
        self.urls
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const TEST_KEY: &[u8] = b"0123456789abcdef0123456789abcdef";

    fn collector() -> UrlCollector {
        UrlCollector::new(UrlCollection {
            url_key: String::from_utf8(TEST_KEY.to_vec()).unwrap(),
        })
    }

    #[test]
    fn hash_is_22_base64url_chars_and_keyed() {
        let hash = hash_url(TEST_KEY, "https://example.com/a.png");
        assert_eq!(hash.len(), 22);
        assert!(hash
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'));
        assert_ne!(hash, hash_url(b"another-key", "https://example.com/a.png"));
    }

    #[test]
    fn ref_matches_the_consumer_shape_and_says_it_came_from_a_url() {
        let mut c = collector();
        let r = c.collect("https://example.com/a.png").unwrap();
        assert!(crate::collect::is_image_ref_strict(&r));
        // The prefix is what tells a reader the hash names a URL, not the bytes behind it.
        assert!(r.starts_with("imageurl:"), "got {r}");
    }

    #[test]
    fn a_signed_url_produces_no_global_ref() {
        let mut c = collector();
        assert!(c
            .collect("https://cdn.example.com/a.png?X-Amz-Signature=aaa")
            .is_none());
        assert_eq!(c.into_declines(), vec![("credential".to_string(), 1)]);
        assert_eq!(c.into_urls(), Vec::new());
    }

    #[test]
    fn a_resize_parameter_is_not_volatile() {
        // Collapsing these onto one ref would point one ref at two different images.
        let mut c = collector();
        let small = c.collect("https://cdn.example.com/a.png?w=100").unwrap();
        let large = c.collect("https://cdn.example.com/a.png?w=900").unwrap();
        assert_ne!(small, large);
        assert_eq!(c.into_urls().len(), 2);
    }

    #[test]
    fn cache_busters_share_one_global_ref_and_fetch_candidate() {
        let mut c = collector();
        let first_url = "https://cdn.example.com/a.png?w=100&cb=first";
        let first = c.collect(first_url).unwrap();
        let second = c
            .collect("https://cdn.example.com/a.png?w=100&cb=second")
            .unwrap();

        assert_eq!(first, second);
        let urls = c.into_urls();
        assert_eq!(urls.len(), 1);
        assert_eq!(urls[0].url, first_url);
    }

    #[test]
    fn collect_stops_at_the_cap_but_still_refs_a_url_it_already_holds() {
        let mut c = collector();
        for i in 0..MAX_URLS_PER_MESSAGE {
            assert!(c.collect(&format!("https://example.com/{i}.png")).is_some());
        }
        assert!(c.collect("https://example.com/one-too-many.png").is_none());
        assert!(c.collect("https://example.com/0.png").is_some());
        assert_eq!(c.into_urls().len(), MAX_URLS_PER_MESSAGE);
    }

    #[test]
    fn into_urls_sorts_by_hash() {
        let mut c = collector();
        c.collect("https://example.com/b.png");
        c.collect("https://example.com/a.png");
        let urls = c.into_urls();
        assert!(urls[0].hash < urls[1].hash);
    }

    #[test]
    fn a_repeated_url_is_hashed_once() {
        let mut c = collector();
        let first = c.collect("https://cdn.example.com/sprite.png").unwrap();
        let second = c.collect("https://cdn.example.com/sprite.png").unwrap();
        assert_eq!(first, second);
        assert_eq!(c.memo.len(), 1, "the second occurrence comes from the memo");
        assert_eq!(c.into_urls().len(), 1);
    }

    #[test]
    fn past_the_cap_a_new_url_costs_no_parse() {
        // A payload can carry far more distinct URLs than the cap. Each one used to pay a full
        // canonicalization and an HMAC before the cap rejected it.
        let mut c = collector();
        for i in 0..MAX_URLS_PER_MESSAGE {
            assert!(c.collect(&format!("https://example.com/{i}.png")).is_some());
        }
        // Declined without being canonicalized, so it never reaches the memo either.
        let before = c.memo.len();
        assert!(c.collect("https://example.com/past-the-cap.png").is_none());
        assert_eq!(
            c.memo.len(),
            before,
            "a declined URL past the cap is not memoized"
        );
        // A URL already held still resolves, because its raw value is in the memo.
        assert!(c.collect("https://example.com/0.png").is_some());
    }

    #[test]
    fn the_memo_is_bounded_against_attacker_controlled_values() {
        // Declined values are the vector: they never reach the URL cap, so only the memo's own cap
        // bounds them. A page can carry as many distinct unfetchable `src` values as it likes.
        let mut c = collector();
        for i in 0..(MAX_MEMO_ENTRIES + 500) {
            assert!(c.collect(&format!("http://10.0.0.5/{i}.png")).is_none());
        }
        assert_eq!(c.memo.len(), MAX_MEMO_ENTRIES);

        // An over-length value is rejected by an O(1) check, so it is never worth storing.
        let mut c = collector();
        let long = format!("https://example.com/{}", "a".repeat(MAX_URL_LEN));
        assert!(c.collect(&long).is_none());
        assert!(c.memo.is_empty());
    }

    #[test]
    fn a_declined_url_is_memoized_too() {
        let mut c = collector();
        assert!(c.collect("http://localhost/i.png").is_none());
        assert!(c.collect("http://localhost/i.png").is_none());
        assert_eq!(c.memo.len(), 1);
    }
}
