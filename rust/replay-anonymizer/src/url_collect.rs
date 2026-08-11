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
use std::net::IpAddr;

use url::Url;

/// Query parameters that change on each page load without changing the image behind the URL.
///
/// **This is an allow list of names, and it must stay one.** Never add a rule about the *shape* of
/// a value: "looks random" and "is long" both describe real image parameters too.
///
/// **Never add a name that also selects an image.** `w`, `h`, `q`, `fm`, `dpr`, `fit`, `auto`,
/// `format`, `resize`, `crop` and `quality` all do. Collapsing those onto one ref would point one
/// ref at several genuinely different images, and nothing downstream can detect it.
///
/// Only unambiguous names live here. A short name that one vendor uses for a signature and another
/// uses for a size belongs in [`SCOPED_VOLATILE_PARAMS`], where a marker keeps it honest. `s` is
/// the example that forced the split: imgix signs with it, and Gravatar sizes with it, so removing
/// it unconditionally made a 48-pixel avatar and a 200-pixel avatar the same image.
const VOLATILE_PARAMS: &[&str] = &[
    // AWS SigV4 presigned (S3, CloudFront). Long and vendor-prefixed, so unambiguous.
    "x-amz-algorithm",
    "x-amz-credential",
    "x-amz-date",
    "x-amz-expires",
    "x-amz-signedheaders",
    "x-amz-signature",
    "x-amz-security-token",
    // CloudFront canned and custom policies.
    "key-pair-id",
    "policy",
    // Google Cloud Storage V4.
    "x-goog-algorithm",
    "x-goog-credential",
    "x-goog-date",
    "x-goog-expires",
    "x-goog-signedheaders",
    "x-goog-signature",
    // Akamai token auth.
    "hdnts",
    "hdnea",
    "hdntl",
    "__token__",
    // Cache busters whose names say so.
    "cb",
    "rnd",
    "nocache",
];

/// Volatile names that are only volatile in a known context.
///
/// Each entry is `(marker, names)`. The names are removed only when the query also carries the
/// marker, which is a parameter the vendor always sends alongside them. Without the marker the
/// names are left alone, because on another host they select an image.
const SCOPED_VOLATILE_PARAMS: &[(&str, &[&str])] = &[
    // Azure Blob shared access signatures always carry sig, and sv alongside the rest.
    (
        "sig",
        &["sv", "st", "se", "sp", "sr", "sig", "spr", "skoid"],
    ),
    // Meta's CDN always carries _nc_ohc with the rest of its rotating set. stp encodes a crop, so
    // it is only safe to drop when the whole set is present and the URL is therefore one of theirs.
    ("_nc_ohc", &["_nc_ohc", "_nc_ht", "oh", "oe", "ccb", "stp"]),
    // CloudFront canned policies pair Signature with Expires. Expires alone is a real cache hint on
    // plenty of other hosts, so it needs the marker.
    ("signature", &["signature", "expires"]),
];

/// Hosts whose short signature parameter is safe to remove, because the vendor owns the host.
const HOST_SCOPED_VOLATILE_PARAMS: &[(&str, &[&str])] = &[(".imgix.net", &["s", "expires"])];

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

/// Whether one parameter of this URL is volatile.
///
/// `present` answers whether the URL carries a given parameter, which is what lets a scoped group
/// require its marker. Comparison is case-insensitive and allocates nothing.
fn is_volatile(name: &str, host: &str, present: &dyn Fn(&str) -> bool) -> bool {
    if VOLATILE_PARAMS.iter().any(|p| p.eq_ignore_ascii_case(name)) {
        return true;
    }
    for (marker, names) in SCOPED_VOLATILE_PARAMS {
        if names.iter().any(|p| p.eq_ignore_ascii_case(name)) && present(marker) {
            return true;
        }
    }
    for (suffix, names) in HOST_SCOPED_VOLATILE_PARAMS {
        if host.ends_with(suffix) && names.iter().any(|p| p.eq_ignore_ascii_case(name)) {
            return true;
        }
    }
    false
}

/// Whether a host is one we would ever fetch from.
///
/// The URL set is built from page content, which an attacker controls, and it exists to be handed
/// to something that makes outbound requests from inside our network. A page carrying
/// `<img src="http://169.254.169.254/...">` must not become a fetch instruction for the cloud
/// metadata endpoint. Rejecting here also keeps hosts we could never reach out of the measurement.
///
/// This is not a substitute for re-checking at fetch time. A name that resolves publicly now can
/// resolve privately later, so the fetcher still has to validate what DNS returns.
fn is_public_host(host: &str) -> bool {
    let h = host.trim_matches(|c| c == '[' || c == ']');
    if let Ok(ip) = h.parse::<IpAddr>() {
        return match ip {
            IpAddr::V4(v4) => {
                !(v4.is_loopback()
                    || v4.is_private()
                    || v4.is_link_local()
                    || v4.is_broadcast()
                    || v4.is_documentation()
                    || v4.is_unspecified()
                    || v4.octets()[0] == 0
                    // 100.64.0.0/10, carrier-grade NAT.
                    || (v4.octets()[0] == 100 && (64..128).contains(&v4.octets()[1]))
                    // 169.254.169.254 is covered by is_link_local, kept explicit for the reader.
                    || v4.octets() == [169, 254, 169, 254])
            }
            IpAddr::V6(v6) => {
                !(v6.is_loopback()
                    || v6.is_unspecified()
                    // Unique local (fc00::/7) and link-local (fe80::/10).
                    || (v6.segments()[0] & 0xfe00) == 0xfc00
                    || (v6.segments()[0] & 0xffc0) == 0xfe80
                    || v6.to_ipv4_mapped().is_some_and(|v4| {
                        v4.is_loopback() || v4.is_private() || v4.is_link_local()
                    }))
            }
        };
    }
    let lower = h.to_ascii_lowercase();
    // A name with no dot cannot be a public domain, which covers `localhost` and every bare
    // container or service name.
    if !lower.contains('.') {
        return false;
    }
    !matches!(
        lower.rsplit('.').next(),
        Some(
            "localhost"
                | "local"
                | "internal"
                | "intranet"
                | "lan"
                | "home"
                | "corp"
                | "test"
                | "invalid"
                | "example"
        )
    )
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
    let host = url.host_str()?.to_string();
    if !is_public_host(&host) {
        return None;
    }

    // Userinfo is credentials, so it never reaches the topic and never reaches the wire. The
    // setters fail only on a cannot-be-a-base URL, which the scheme check above already excluded.
    let _ = url.set_username("");
    let _ = url.set_password(None);
    url.set_fragment(None);

    // `Url` already lowercases the scheme and host and drops a default port on parse.
    let fetch = url.to_string();
    // Percent-encoding and IDNA can both grow a URL, so the cap is re-checked on what we emit
    // rather than only on what we were handed.
    if fetch.len() > MAX_URL_LEN {
        return None;
    }

    let pairs: Vec<(String, String)> = url
        .query_pairs()
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect();
    let present = |name: &str| pairs.iter().any(|(k, _)| k.eq_ignore_ascii_case(name));
    let kept: Vec<&(String, String)> = pairs
        .iter()
        .filter(|(k, _)| !is_volatile(k, &host, &present))
        .collect();

    // The query is rebuilt on every URL that has one, not only when something was removed.
    // Rebuilding conditionally made the dedup URL depend on whether a volatile parameter happened
    // to be present: two encodings of one query would then hash the same when a signature rode
    // along, and differently when it did not, so one image could hold two refs.
    if url.query().is_some() {
        if kept.is_empty() {
            url.set_query(None);
        } else {
            let mut q = url.query_pairs_mut();
            q.clear();
            for (k, v) in &kept {
                q.append_pair(k, v);
            }
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
    /// Raw attribute value to the ref it produced, or `None` when it was declined.
    ///
    /// One image recurs many times in a message: a background on every row of a list, a sprite
    /// re-added by every mutation. The image lane memoizes its blur for the same reason. Without
    /// this, each repeat pays a WHATWG parse, a query walk, and an HMAC.
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
        let result = self.collect_uncached(raw);
        self.memo.insert(raw.to_string(), result.clone());
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
        let c = canonicalize("https://cdn.example.com/a.png?nocache=12345").unwrap();
        assert_eq!(c.dedup, "https://cdn.example.com/a.png");
    }

    #[test]
    fn an_ambiguous_cache_buster_is_kept() {
        // `v` and `t` are cache busters on some hosts and content-version or variant markers on
        // others. Keeping them costs a missed dedup. Removing them merges two different images.
        let a = canonicalize("https://cdn.example.com/a.png?v=thumb").unwrap();
        let b = canonicalize("https://cdn.example.com/a.png?v=full").unwrap();
        assert_ne!(a.dedup, b.dedup);
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

    fn volatile(name: &str, host: &str, others: &[&str]) -> bool {
        let present = |n: &str| others.iter().any(|o| o.eq_ignore_ascii_case(n));
        is_volatile(name, host, &present)
    }

    #[test]
    fn volatile_names_never_include_a_name_that_selects_an_image() {
        for name in [
            "w", "h", "q", "fm", "dpr", "fit", "auto", "format", "resize", "crop", "quality",
        ] {
            assert!(
                !volatile(name, "cdn.example.com", &[]),
                "{name} changes the image and must be kept"
            );
        }
    }

    #[test]
    fn a_short_name_is_only_volatile_where_the_vendor_owns_it() {
        // `s` sizes a Gravatar avatar and signs an imgix URL. Stripping it everywhere made a
        // 48-pixel avatar and a 200-pixel avatar the same image.
        assert!(!volatile("s", "www.gravatar.com", &[]));
        assert!(volatile("s", "images.imgix.net", &[]));
        // The Azure SAS names only go when the signature that identifies the set rides along.
        assert!(!volatile("sp", "cdn.example.com", &["w"]));
        assert!(volatile("sp", "acct.blob.core.windows.net", &["sig", "sv"]));
        // `expires` is a real cache hint until CloudFront's `signature` appears beside it.
        assert!(!volatile("expires", "cdn.example.com", &[]));
        assert!(volatile("expires", "cdn.example.com", &["signature"]));
    }

    #[test]
    fn a_gravatar_size_is_not_stripped() {
        let big = canonicalize("https://www.gravatar.com/avatar/abc?s=200").unwrap();
        let small = canonicalize("https://www.gravatar.com/avatar/abc?s=48").unwrap();
        assert_ne!(
            big.dedup, small.dedup,
            "two avatar sizes are two images and must not share a ref"
        );
    }

    #[test]
    fn a_non_public_host_is_never_collected() {
        // The URL set comes from page content, and the fetch lane runs inside our network.
        for raw in [
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            "http://localhost:8000/admin/export.png",
            "http://127.0.0.1/i.png",
            "http://10.0.0.5/i.png",
            "http://192.168.1.1/i.png",
            "http://172.16.0.1/i.png",
            "http://[::1]/i.png",
            "http://[fd00::1]/i.png",
            "http://metadata.internal/i.png",
            "http://buildserver/i.png",
        ] {
            assert!(canonicalize(raw).is_none(), "{raw} must not be collected");
        }
        assert!(canonicalize("https://cdn.example.com/i.png").is_some());
    }

    #[test]
    fn the_dedup_url_does_not_depend_on_whether_a_signature_rode_along() {
        // The query used to be re-encoded only when something was stripped, so one image could
        // hold two refs depending on an unrelated condition.
        let plain = canonicalize("https://cdn.example.com/a.png?a=1&b=2").unwrap();
        let signed =
            canonicalize("https://cdn.example.com/a.png?a=1&b=2&X-Amz-Signature=zz").unwrap();
        assert_eq!(plain.dedup, signed.dedup);
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
    fn a_declined_url_is_memoized_too() {
        let mut c = collector();
        assert!(c.collect("http://localhost/i.png").is_none());
        assert!(c.collect("http://localhost/i.png").is_none());
        assert_eq!(c.memo.len(), 1);
    }
}
