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

use std::collections::HashSet;

use base64::Engine;
use hmac::{Hmac, Mac};
use sha2::Sha256;
use url::Url;

/// Query parameters that change on each page load without changing the image behind the URL.
///
/// **This is an allow list of names, and it must stay one.** Never add a rule about the *shape* of
/// a value: "looks random" and "is long" both describe real image parameters too. Every name here
/// comes from a vendor's own documentation for a signature, an expiry, or a cache buster.
///
/// Never add a name that selects a different image. `w`, `h`, `q`, `fm`, `dpr`, `fit`, `auto`,
/// `format`, `resize`, `crop` and `quality` all do, and collapsing those onto one ref would point
/// one ref at several genuinely different images. That failure is silent, which is what makes it
/// worth this warning.
const VOLATILE_PARAMS: &[&str] = &[
    // AWS SigV4 presigned (S3, CloudFront)
    "x-amz-algorithm",
    "x-amz-credential",
    "x-amz-date",
    "x-amz-expires",
    "x-amz-signedheaders",
    "x-amz-signature",
    "x-amz-security-token",
    // CloudFront canned and custom policies
    "expires",
    "signature",
    "key-pair-id",
    "policy",
    // Google Cloud Storage V4
    "x-goog-algorithm",
    "x-goog-credential",
    "x-goog-date",
    "x-goog-expires",
    "x-goog-signedheaders",
    "x-goog-signature",
    // Azure Blob shared access signatures
    "sv",
    "st",
    "se",
    "sp",
    "sr",
    "sig",
    "spr",
    "skoid",
    // Akamai token auth
    "hdnts",
    "hdnea",
    "hdntl",
    "__token__",
    // Imgix
    "s",
    // Meta CDN
    "_nc_ohc",
    "_nc_ht",
    "oh",
    "oe",
    "ccb",
    "stp",
    // Generic cache busters
    "v",
    "t",
    "ts",
    "_",
    "cb",
    "rnd",
    "nocache",
    "updated_at",
];

/// Longer than this and we neither collect nor fetch it. Well past what a real image URL needs,
/// and it bounds what one message can pin in memory alongside the count cap.
pub const MAX_URL_LEN: usize = 2048;

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
    /// The host, which the fetch topic uses as its Kafka key so one host lands on one partition.
    pub host: String,
}

/// The two forms of one URL. See the module docs for why both exist.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CanonicalUrl {
    pub fetch: String,
    pub dedup: String,
    pub host: String,
}

/// First 22 base64url chars of `HMAC-SHA256(url_key, dedup_url)`. Same construction and width as
/// [`crate::collect::hash_image_bytes`], so both kinds of ref parse under one regex downstream.
pub fn hash_url(url_key: &[u8], dedup_url: &str) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(url_key).expect("hmac accepts any key length");
    mac.update(dedup_url.as_bytes());
    let digest = mac.finalize().into_bytes();
    let mut b64 = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(digest);
    b64.truncate(22);
    b64
}

fn is_volatile(name: &str) -> bool {
    let lower = name.to_ascii_lowercase();
    VOLATILE_PARAMS.iter().any(|p| *p == lower)
}

/// Canonicalize a remote image URL into its fetch and dedup forms.
///
/// `None` for anything we will not fetch: a non-`http(s)` scheme, a URL with no host, or one past
/// [`MAX_URL_LEN`]. A relative URL also lands here, because the recording does not carry the base
/// it would need to resolve against.
pub fn canonicalize(raw: &str) -> Option<CanonicalUrl> {
    if raw.len() > MAX_URL_LEN {
        return None;
    }
    let mut url = Url::parse(raw).ok()?;
    if !matches!(url.scheme(), "http" | "https") {
        return None;
    }
    url.host_str()?;

    // Userinfo is credentials, so it never reaches the topic and never reaches the wire. The
    // setters fail only on a cannot-be-a-base URL, which the scheme check above already excluded.
    let _ = url.set_username("");
    let _ = url.set_password(None);
    url.set_fragment(None);

    // `Url` already lowercases the scheme and host and drops a default port on parse.
    let host = url.host_str()?.to_string();
    let fetch = url.to_string();

    let volatile: Vec<String> = url
        .query_pairs()
        .filter(|(k, _)| is_volatile(k))
        .map(|(k, _)| k.into_owned())
        .collect();
    if !volatile.is_empty() {
        let kept: Vec<(String, String)> = url
            .query_pairs()
            .filter(|(k, _)| !is_volatile(k))
            .map(|(k, v)| (k.into_owned(), v.into_owned()))
            .collect();
        // Rebuilt in the original order, minus the volatile names. Order is preserved because a
        // reordered query is a different URL to plenty of origins.
        {
            let mut q = url.query_pairs_mut();
            q.clear();
            for (k, v) in &kept {
                q.append_pair(k, v);
            }
        }
        if kept.is_empty() {
            url.set_query(None);
        }
    }
    let dedup = url.to_string();

    Some(CanonicalUrl { fetch, dedup, host })
}

/// Accumulates the remote image URLs of one message, deduplicated on the hash.
pub struct UrlCollector {
    pseudo_team: String,
    url_key: String,
    urls: Vec<CollectedUrl>,
    seen: HashSet<String>,
}

impl UrlCollector {
    pub fn new(collection: UrlCollection) -> Self {
        Self {
            pseudo_team: collection.pseudo_team,
            url_key: collection.url_key,
            urls: Vec::new(),
            seen: HashSet::new(),
        }
    }

    /// Collect a remote image URL and return its ref, or `None` when the URL is not fetchable or a
    /// cap says this one stays on the placeholder path.
    pub fn collect(&mut self, raw: &str) -> Option<String> {
        let canonical = canonicalize(raw)?;
        let hash = hash_url(self.url_key.as_bytes(), &canonical.dedup);
        if self.seen.contains(&hash) {
            return Some(crate::collect::image_ref(&self.pseudo_team, &hash));
        }
        if self.urls.len() >= MAX_URLS_PER_MESSAGE {
            return None;
        }
        self.seen.insert(hash.clone());
        self.urls.push(CollectedUrl {
            hash: hash.clone(),
            url: canonical.fetch,
            host: canonical.host,
        });
        Some(crate::collect::image_ref(&self.pseudo_team, &hash))
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
    fn ref_matches_the_consumer_shape() {
        let mut c = collector();
        let r = c.collect("https://example.com/a.png").unwrap();
        assert!(crate::collect::is_image_ref_strict(&r));
    }

    #[test]
    fn canonicalize_rejects_what_we_will_not_fetch() {
        for raw in [
            "ftp://example.com/a.png",
            "data:image/png;base64,aGk=",
            "/relative/a.png",
            "not a url",
            "//protocol-relative.example.com/a.png",
        ] {
            assert!(canonicalize(raw).is_none(), "{raw} should not canonicalize");
        }
        let long = format!("https://example.com/{}", "a".repeat(MAX_URL_LEN));
        assert!(canonicalize(&long).is_none());
    }

    #[test]
    fn canonicalize_normalizes_and_strips_credentials() {
        let c = canonicalize("HTTPS://User:Pass@Example.COM:443/A.png#frag").unwrap();
        assert_eq!(c.fetch, "https://example.com/A.png");
        assert_eq!(c.host, "example.com");
        assert!(!c.fetch.contains("User"));
        assert!(!c.fetch.contains("Pass"));
    }

    #[test]
    fn the_signature_stays_on_the_fetch_url_and_leaves_the_dedup_url() {
        let signed = "https://cdn.example.com/a.png?w=200&X-Amz-Signature=deadbeef&X-Amz-Date=20260810T000000Z";
        let c = canonicalize(signed).unwrap();
        // The fetcher needs the signature, or the request 403s.
        assert!(c.fetch.contains("X-Amz-Signature=deadbeef"));
        // The ref must not move when the signature does.
        assert_eq!(c.dedup, "https://cdn.example.com/a.png?w=200");
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
    fn a_query_that_is_only_volatile_leaves_no_empty_question_mark() {
        let c = canonicalize("https://cdn.example.com/a.png?v=12345").unwrap();
        assert_eq!(c.dedup, "https://cdn.example.com/a.png");
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
    fn volatile_names_never_include_a_name_that_selects_an_image() {
        for name in [
            "w", "h", "q", "fm", "dpr", "fit", "auto", "format", "resize", "crop", "quality",
        ] {
            assert!(
                !is_volatile(name),
                "{name} changes the image and must be kept"
            );
        }
    }
}
