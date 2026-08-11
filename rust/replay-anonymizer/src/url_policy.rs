//! The rules that decide whether a remote image URL may be fetched, and what its canonical forms
//! are.
//!
//! Separate from [`crate::url_collect`] on purpose. That module accumulates the URLs of one
//! message; this one holds the policy, and the policy has more than one consumer. The fetch lane
//! has to apply the same host rule again at request time, on the resolved address and on every
//! redirect hop, because a name that resolves publicly now can resolve privately later. The fetch
//! lane also has to canonicalize what it fetched to find its ledger entry.
//!
//! That second consumer is in another language, so `tests/fixtures/url-policy.json` pins these
//! rules as data. The Rust side checks itself against that file, and the fetch lane can check
//! itself against the same one, in the way `image-hash.json` already pins the image hash across
//! both engines.

use std::collections::HashSet;
use std::net::{IpAddr, Ipv4Addr};

use public_suffix::{EffectiveTLDProvider, DEFAULT_PROVIDER};

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
    // CloudFront canned policies. key-pair-id is vendor-specific enough to stand alone.
    "key-pair-id",
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
    // CloudFront canned policies pair Signature with Expires and Policy. Both are ordinary words
    // elsewhere: `expires` is a real cache hint, and `policy=thumb` is a plausible image selector.
    ("signature", &["signature", "expires", "policy"]),
    ("key-pair-id", &["policy", "expires"]),
];

/// Hosts whose short signature parameter is safe to remove, because the vendor owns the host.
const HOST_SCOPED_VOLATILE_PARAMS: &[(&str, &[&str])] = &[(".imgix.net", &["s", "expires"])];

/// Longer than this and we neither collect nor fetch it. Well past what a real image URL needs,
/// and it bounds what one message can pin in memory alongside the count cap.
pub const MAX_URL_LEN: usize = 2048;

/// The politeness unit for a host: the registrable domain, or the host itself when it has none.
///
/// A rate limit protects the operator that answers the request, not a DNS label, and a CDN that
/// shards over `img1..img8.cdn.example.com` would otherwise receive eight times the intended rate.
/// The fetch topic keys on this, so every URL of one operator lands on one partition and one pod
/// holds its budget without a distributed lock.
///
/// The public suffix list draws the boundary, and its private section is what makes this correct
/// for multi-tenant hosts. `d111.cloudfront.net`, `bucket.s3.amazonaws.com`, `user.github.io` and
/// `myapp.vercel.app` are each their own registrable domain, because `cloudfront.net`,
/// `s3.amazonaws.com`, `github.io` and `vercel.app` are all public suffixes. One tenant therefore
/// never shares a budget with an unrelated tenant of the same provider.
///
/// An IP literal has no registrable domain and returns unchanged, which is right: the address is
/// the operator.
pub fn politeness_key(host: &str) -> String {
    if host.parse::<IpAddr>().is_ok() || host.starts_with('[') {
        return host.to_string();
    }
    match DEFAULT_PROVIDER.effective_tld_plus_one(host) {
        Ok(domain) => domain.to_string(),
        // A host with no registrable domain is its own operator. `is_public_host` already declined
        // the bare names this could otherwise return.
        Err(_) => host.to_string(),
    }
}

/// The two forms of one URL. See the module docs for why both exist.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CanonicalUrl {
    pub fetch: String,
    pub dedup: String,
    pub host: String,
    /// The registrable domain of `host`. See [`politeness_key`].
    pub domain: String,
}

/// Whether one parameter of this URL is volatile.
///
/// `present` holds every parameter name on this URL, already lowercased, which is what lets a
/// scoped group require its marker. It is built once per URL: asking the question by scanning the
/// parameter list made the check quadratic in the parameter count, and a page controls both the
/// number of parameters and the number of URLs.
fn is_volatile(name: &str, host: &str, present: &HashSet<String>) -> bool {
    if VOLATILE_PARAMS.iter().any(|p| p.eq_ignore_ascii_case(name)) {
        return true;
    }
    for (marker, names) in SCOPED_VOLATILE_PARAMS {
        if names.iter().any(|p| p.eq_ignore_ascii_case(name)) && present.contains(*marker) {
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
/// metadata endpoint.
///
/// This is not a substitute for re-checking at fetch time. A name that resolves publicly now can
/// resolve privately later, so the fetcher still has to validate the address DNS returns, on the
/// first request and on every redirect hop.
pub fn is_public_host(host: &str) -> bool {
    let bare = host.trim_matches(|c| c == '[' || c == ']');
    // A trailing dot makes a name fully qualified and resolves identically. Without stripping it,
    // `rsplit('.')` yields the empty label after the dot, which matches no suffix, so `localhost.`
    // walked straight past the name list.
    let bare = bare.strip_suffix('.').unwrap_or(bare);
    if let Ok(ip) = bare.parse::<IpAddr>() {
        return is_public_ip(ip);
    }
    let lower = bare.to_ascii_lowercase();
    // A name with no dot cannot be a public domain, which covers `localhost` and every bare
    // container or service name.
    if !lower.contains('.') || lower.split('.').any(|label| label.is_empty()) {
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

/// Every address rule lives here, so an address expressed in IPv6 cannot skip a rule that the IPv4
/// path applies. IPv6 offers several ways to write an IPv4 address, and each one used to bypass
/// most of the list.
fn is_public_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => is_public_v4(v4),
        IpAddr::V6(v6) => {
            if v6.is_loopback() || v6.is_unspecified() || v6.is_multicast() {
                return false;
            }
            // Unique local (fc00::/7) and link-local (fe80::/10).
            let seg = v6.segments();
            if (seg[0] & 0xfe00) == 0xfc00 || (seg[0] & 0xffc0) == 0xfe80 {
                return false;
            }
            // Every embedding of an IPv4 address is judged by the IPv4 rules.
            if let Some(v4) = v6.to_ipv4_mapped().or_else(|| v6.to_ipv4()) {
                return is_public_v4(v4);
            }
            // 6to4 carries the address in the two segments after the 0x2002 prefix.
            if seg[0] == 0x2002 {
                let v4 = Ipv4Addr::new(
                    (seg[1] >> 8) as u8,
                    seg[1] as u8,
                    (seg[2] >> 8) as u8,
                    seg[2] as u8,
                );
                return is_public_v4(v4);
            }
            // NAT64 well-known prefix 64:ff9b::/96 carries it in the last two segments.
            if seg[0] == 0x0064 && seg[1] == 0xff9b && seg[2] == 0 && seg[3] == 0 && seg[4] == 0 {
                let v4 = Ipv4Addr::new(
                    (seg[6] >> 8) as u8,
                    seg[6] as u8,
                    (seg[7] >> 8) as u8,
                    seg[7] as u8,
                );
                return is_public_v4(v4);
            }
            true
        }
    }
}

fn is_public_v4(v4: Ipv4Addr) -> bool {
    let o = v4.octets();
    !(v4.is_loopback()
        || v4.is_private()
        || v4.is_link_local()
        || v4.is_broadcast()
        || v4.is_documentation()
        || v4.is_unspecified()
        || v4.is_multicast()
        // "This network", 0.0.0.0/8. A connect to 0.0.0.0 reaches loopback on Linux.
        || o[0] == 0
        // Carrier-grade NAT, 100.64.0.0/10.
        || (o[0] == 100 && (64..128).contains(&o[1]))
        // IETF protocol assignments, 192.0.0.0/24.
        || (o[0] == 192 && o[1] == 0 && o[2] == 0)
        // Benchmarking, 198.18.0.0/15.
        || (o[0] == 198 && (o[1] == 18 || o[1] == 19))
        // Reserved, 240.0.0.0/4.
        || o[0] >= 240)
}

/// Why a URL was not collected. Each variant is a label on the decline counter, so a lane that
/// silently collects less than it should can be read off a dashboard rather than guessed at.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Decline {
    /// Longer than [`MAX_URL_LEN`], before or after normalization.
    TooLong,
    /// Not parseable as an absolute URL. A relative `src` lands here, because the recording does
    /// not carry the base it would need to resolve against.
    NotAbsolute,
    /// A scheme we do not fetch, such as `data:`, `blob:` or `ftp:`.
    BadScheme,
    /// No host at all.
    NoHost,
    /// Loopback, private, link-local or an internal-only name. See [`is_public_host`].
    NonPublicHost,
}

impl Decline {
    /// The metric label. Stable, because a dashboard and an alert both key on it.
    pub fn label(self) -> &'static str {
        match self {
            Decline::TooLong => "too_long",
            Decline::NotAbsolute => "not_absolute",
            Decline::BadScheme => "bad_scheme",
            Decline::NoHost => "no_host",
            Decline::NonPublicHost => "non_public_host",
        }
    }
}

/// Canonicalize a remote image URL into its fetch and dedup forms, or say why it was refused.
pub fn canonicalize(raw: &str) -> Option<CanonicalUrl> {
    try_canonicalize(raw).ok()
}

pub fn try_canonicalize(raw: &str) -> Result<CanonicalUrl, Decline> {
    if raw.len() > MAX_URL_LEN {
        return Err(Decline::TooLong);
    }
    let mut url = Url::parse(raw).map_err(|_| Decline::NotAbsolute)?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err(Decline::BadScheme);
    }
    let host = url.host_str().ok_or(Decline::NoHost)?.to_string();
    if !is_public_host(&host) {
        return Err(Decline::NonPublicHost);
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
        return Err(Decline::TooLong);
    }

    let pairs: Vec<(String, String)> = url
        .query_pairs()
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect();
    let present: HashSet<String> = pairs.iter().map(|(k, _)| k.to_ascii_lowercase()).collect();
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

    let domain = politeness_key(&host);
    Ok(CanonicalUrl {
        fetch,
        dedup,
        host,
        domain,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn volatile(name: &str, host: &str, others: &[&str]) -> bool {
        let present: HashSet<String> = others.iter().map(|o| o.to_ascii_lowercase()).collect();
        is_volatile(name, host, &present)
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
    fn a_query_that_is_only_volatile_leaves_no_empty_question_mark() {
        let c = canonicalize("https://cdn.example.com/a.png?nocache=12345").unwrap();
        assert_eq!(c.dedup, "https://cdn.example.com/a.png");
    }

    #[test]
    fn a_generic_word_is_only_volatile_beside_its_vendor_marker() {
        // `policy=thumb` and `policy=full` are plausible image selectors on an ordinary host.
        let thumb = canonicalize("https://cdn.example.com/a.png?policy=thumb").unwrap();
        let full = canonicalize("https://cdn.example.com/a.png?policy=full").unwrap();
        assert_ne!(thumb.dedup, full.dedup);
        // Beside CloudFront's signature it is part of the signing set.
        assert!(volatile("policy", "cdn.example.com", &["signature"]));
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
    fn the_politeness_key_is_the_operator_not_the_dns_label() {
        // A CDN that shards over numbered subdomains must share one budget.
        assert_eq!(politeness_key("img1.cdn.example.com"), "example.com");
        assert_eq!(politeness_key("img8.cdn.example.com"), "example.com");
        assert_eq!(politeness_key("example.com"), "example.com");
    }

    #[test]
    fn a_multi_tenant_host_keeps_its_tenants_apart() {
        // The private section of the public suffix list is what makes this correct. Without it,
        // every CloudFront distribution on the internet would share one budget and one partition.
        assert_eq!(politeness_key("d111.cloudfront.net"), "d111.cloudfront.net");
        assert_eq!(
            politeness_key("bucket.s3.amazonaws.com"),
            "bucket.s3.amazonaws.com"
        );
        assert_eq!(politeness_key("user.github.io"), "user.github.io");
        // The app-hosting case: a tenant subdomain is its own operator for our purposes.
        assert_eq!(politeness_key("myapp.vercel.app"), "myapp.vercel.app");
        assert_eq!(politeness_key("site.netlify.app"), "site.netlify.app");
        assert_eq!(politeness_key("worker.workers.dev"), "worker.workers.dev");
    }

    #[test]
    fn an_ip_literal_is_its_own_operator() {
        assert_eq!(politeness_key("203.0.113.7"), "203.0.113.7");
        assert_eq!(politeness_key("[2606:4700::1111]"), "[2606:4700::1111]");
    }

    #[test]
    fn canonicalize_carries_the_politeness_key() {
        let c = canonicalize("https://img3.cdn.example.co.uk/a.png").unwrap();
        assert_eq!(c.host, "img3.cdn.example.co.uk");
        // A multi-label public suffix, which is why this cannot be "the last two labels".
        assert_eq!(c.domain, "example.co.uk");
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
            // A trailing dot makes a name fully qualified and resolves the same way. It used to
            // walk past the name list, because the label after the final dot is empty.
            "http://localhost./i.png",
            "http://metadata.internal./i.png",
            "http://LOCALHOST./i.png",
            // IPv6 offers several ways to write an IPv4 address. Each one used to skip the IPv4
            // rules entirely.
            "http://[::ffff:0.0.0.0]/i.png",
            "http://[::ffff:127.0.0.1]/i.png",
            "http://[::ffff:10.0.0.5]/i.png",
            "http://[::ffff:100.64.0.1]/i.png",
            "http://[::127.0.0.1]/i.png",
            "http://[2002:7f00:1::]/i.png",
            "http://[64:ff9b::7f00:1]/i.png",
            "http://[ff02::1]/i.png",
            // Ranges we would never legitimately fetch from.
            "http://224.0.0.1/i.png",
            "http://240.0.0.1/i.png",
            "http://198.18.0.1/i.png",
            "http://192.0.0.1/i.png",
            "http://0.0.0.0/i.png",
        ] {
            assert!(canonicalize(raw).is_none(), "{raw} must not be collected");
        }
        assert!(canonicalize("https://cdn.example.com/i.png").is_some());
        // A public name with a trailing dot is still public, so the fix must not over-reject.
        assert!(canonicalize("https://cdn.example.com./i.png").is_some());
        assert!(canonicalize("http://[2606:4700::1111]/i.png").is_some());
        assert!(canonicalize("http://8.8.8.8/i.png").is_some());
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
}
