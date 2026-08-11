//! Collect the original URLs of remote images, for the out-of-band fetch lane.
//!
//! The sibling of [`crate::collect`]. That module handles an image the page inlined into the
//! recording; this one handles an image the page referred to by URL. With collection enabled, a
//! media source attribute holding an `http(s)` URL is replaced by a content ref instead of the
//! media placeholder, and the original URL rides back to the caller on the message.
//!
//! **Two URLs come out of this module and they must not be confused.** The *dedup* URL is
//! canonical with the volatile parameters removed, and it is the only input to the hash, so it
//! sets both the ref and the fetch lane's dedup key. The *fetch* URL is canonical with every
//! parameter intact, and it is what the fetcher actually requests. A signed URL only works as the
//! second, and only dedups as the first.
//!
//! That split is what makes the ref stable. A URL carrying a fresh signature on every page load
//! would otherwise mint a new ref each time, and a ref that appears once can never join to
//! anything downstream. Removing the volatile parameters matters more for that than it does for
//! the request count.
//!
//! The hash is a *keyed* HMAC for the same reason as the image hash: the ML bucket is unencrypted,
//! and an unkeyed digest of a URL would let a bucket reader learn which sites a team's users
//! visited. The per-team key is derived by the caller from the same KMS-held secret as the team
//! pseudonym, so neither leaves the ingester.

use std::collections::{HashMap, HashSet};

use base64::Engine;
use hmac::{Hmac, Mac};
use sha2::Sha256;

use crate::url_policy::{canonicalize, MAX_URL_LEN};
/// Distinct raw values one message may memoize.
///
/// Larger than [`MAX_URLS_PER_MESSAGE`] on purpose, because the memo also holds the values this
/// collector declined, and a decline is exactly what a repeat should not pay for twice. Past this
/// the memo stops growing and repeats fall back to the full check, which is slower and bounded
/// rather than unbounded.
const MAX_MEMO_ENTRIES: usize = 1024;

/// Distinct URLs collected from one message. A page with more media than this is already past the
/// point where the extra images teach a model anything, and the cap bounds the Kafka fan-out.
pub const MAX_URLS_PER_MESSAGE: usize = 256;

/// Enables URL collection for one anonymize call.
#[derive(Debug, Clone)]
pub struct UrlCollection {
    /// The non-reversible HMAC team pseudonym (32 hex chars), computed by the caller. Embedded
    /// verbatim in every emitted ref, exactly as on the image lane.
    pub pseudo_team: String,
    /// Per-team key for the URL HMAC, derived by the caller under its own domain separator so a
    /// URL ref and an image ref cannot collide even for the same team.
    pub url_key: String,
}

/// One collected URL, on its way to the fetch topic.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CollectedUrl {
    /// First 22 base64url chars of `HMAC-SHA256(url_key, dedup_url)`.
    pub hash: String,
    /// The canonical URL with every parameter intact. This is what the fetcher requests.
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
    pseudo_team: String,
    url_key: String,
    urls: Vec<CollectedUrl>,
    seen: HashSet<String>,
    /// Raw attribute value to the ref it produced, or `None` when it was declined.
    ///
    /// One image recurs many times in a message: a background on every row of a list, a sprite
    /// re-added by every mutation. The image lane memoizes its blur for the same reason. Without
    /// this, each repeat pays a WHATWG parse, a query walk, and an HMAC.
    ///
    /// Bounded by [`MAX_MEMO_ENTRIES`], because the keys are attacker-controlled. Every other
    /// structure here is capped by [`MAX_URLS_PER_MESSAGE`], and a page carrying thousands of
    /// distinct `src` values would otherwise pin a second copy of all of them, including the ones
    /// this collector declined.
    memo: HashMap<String, Option<String>>,
}

impl UrlCollector {
    pub fn new(collection: UrlCollection) -> Self {
        Self {
            pseudo_team: collection.pseudo_team,
            url_key: collection.url_key,
            urls: Vec::new(),
            seen: HashSet::new(),
            memo: HashMap::new(),
        }
    }

    /// Collect a remote image URL and return its ref, or `None` when the URL is not fetchable or a
    /// cap says this one stays on the placeholder path.
    pub fn collect(&mut self, raw: &str) -> Option<String> {
        if let Some(hit) = self.memo.get(raw) {
            return hit.clone();
        }
        // Past the cap a new spelling cannot be collected. The only thing canonicalizing it could
        // still do is match the hash of one already held, and that is not worth a parse and an
        // HMAC for every distinct value on a payload built to carry many of them.
        if self.urls.len() >= MAX_URLS_PER_MESSAGE {
            return None;
        }
        let result = self.collect_uncached(raw);
        // A value past the length cap is rejected by an O(1) check, so caching it buys nothing and
        // would store the longest strings on offer. The entry cap bounds the rest.
        if raw.len() <= MAX_URL_LEN && self.memo.len() < MAX_MEMO_ENTRIES {
            self.memo.insert(raw.to_string(), result.clone());
        }
        result
    }

    fn collect_uncached(&mut self, raw: &str) -> Option<String> {
        let canonical = canonicalize(raw)?;
        let hash = hash_url(self.url_key.as_bytes(), &canonical.dedup);
        if self.seen.contains(&hash) {
            return Some(crate::collect::url_ref(&self.pseudo_team, &hash));
        }
        if self.urls.len() >= MAX_URLS_PER_MESSAGE {
            return None;
        }
        self.seen.insert(hash.clone());
        self.urls.push(CollectedUrl {
            hash: hash.clone(),
            url: canonical.fetch,
            host: canonical.host,
            domain: canonical.domain,
        });
        Some(crate::collect::url_ref(&self.pseudo_team, &hash))
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
            pseudo_team: "a".repeat(32),
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
    fn two_signatures_of_one_image_share_a_ref() {
        let mut c = collector();
        let first = c
            .collect("https://cdn.example.com/a.png?X-Amz-Signature=aaa")
            .unwrap();
        let second = c
            .collect("https://cdn.example.com/a.png?X-Amz-Signature=bbb")
            .unwrap();
        assert_eq!(first, second);
        // One entry, and it keeps the URL of the first sighting, which is a URL that still works.
        let urls = c.into_urls();
        assert_eq!(urls.len(), 1);
        assert!(urls[0].url.contains("X-Amz-Signature=aaa"));
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
