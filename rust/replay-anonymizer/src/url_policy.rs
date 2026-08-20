//! The rules that decide whether a remote image URL may be fetched, and what its canonical forms
//! are.
//!
//! Separate from [`crate::url_collect`] on purpose. That module accumulates the URLs of one
//! message. This one holds the policy, and the policy has more than one consumer.
//!
//! The fetch lane applies the same host rule again at request time. It applies it to the resolved
//! address, and to every redirect hop, because a name that resolves publicly now can resolve
//! privately later. The fetch lane also canonicalizes what it fetched, to find its ledger entry.
//!
//! The fetch lane runs in another language. The registrable domain therefore travels with each
//! URL as data, so that lane reads the result and never repeats the rule.

use std::collections::HashSet;
use std::net::{IpAddr, Ipv4Addr};

use public_suffix::{EffectiveTLDProvider, DEFAULT_PROVIDER};

use url::Url;

/// Query parameters that change on each page load without changing the image behind the URL.
///
/// **This is an allow list of names. It must stay one.**
///
/// Never add a rule about the *shape* of a value. "Looks random" and "is long" both describe real
/// image parameters.
///
/// **Never add a name that also selects an image.** `w`, `h`, `q`, `fm`, `dpr`, `fit`, `auto`,
/// `format`, `resize`, `crop` and `quality` all do. Collapsing those onto one ref would point one
/// ref at several genuinely different images, and nothing downstream can detect it.
///
/// Only unambiguous names live here. A short name that one vendor uses for a signature and another
/// uses for a size belongs in [`SCOPED_VOLATILE_PARAMS`], where a marker keeps it honest.
///
/// `s` is the name that forced the split. imgix signs with it. Gravatar sizes with it. Removing it
/// everywhere made a 48-pixel avatar and a 200-pixel avatar the same image.
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
/// A rate limit protects the operator that answers the request, not a DNS label. A CDN that shards
/// over `img1..img8.cdn.example.com` would otherwise receive eight times the intended rate.
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
    // `example.com.` and `example.com` are one operator, so two spellings must not take two
    // budgets, two breakers, and two partitions. Brackets stay, because an IPv6 literal keys in the
    // form the URL carries.
    let host = host.strip_suffix('.').unwrap_or(host);
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
/// The name set is built once per URL. A scan of the parameter list made this quadratic in the
/// parameter count, and a page controls both that count and the number of URLs.
fn is_volatile(name: &str, host: &str, names_on_this_url: &HashSet<String>) -> bool {
    if VOLATILE_PARAMS.iter().any(|p| p.eq_ignore_ascii_case(name)) {
        return true;
    }
    for (marker, names) in SCOPED_VOLATILE_PARAMS {
        if names.iter().any(|p| p.eq_ignore_ascii_case(name)) && names_on_this_url.contains(*marker)
        {
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
/// A page controls the URL set, and the set exists to be handed to something that makes outbound
/// requests from inside our network. A page carrying
/// `<img src="http://169.254.169.254/...">` must not become a fetch instruction for the cloud
/// metadata endpoint.
///
/// This is not a substitute for a check at fetch time. A name that resolves publicly now can
/// resolve privately later. The fetcher therefore validates the address DNS returns, on the first
/// request and on every redirect hop.
pub fn is_public_host(host: &str) -> bool {
    let host = without_brackets_or_trailing_dot(host);
    if let Ok(ip) = host.parse::<IpAddr>() {
        return is_public_ip(ip);
    }
    is_public_domain_name(&host.to_ascii_lowercase())
}

/// `[2606:4700::1111]` becomes `2606:4700::1111`, and `localhost.` becomes `localhost`.
///
/// A trailing dot makes a name fully qualified and resolves identically, so leaving it on let
/// `localhost.` past the name check below: the label after the final dot is empty and matches
/// nothing.
fn without_brackets_or_trailing_dot(host: &str) -> &str {
    let bare = host.trim_matches(|c| c == '[' || c == ']');
    bare.strip_suffix('.').unwrap_or(bare)
}

fn is_public_domain_name(lowercase_host: &str) -> bool {
    let has_no_dot = !lowercase_host.contains('.');
    let has_empty_label = lowercase_host.split('.').any(|label| label.is_empty());
    if has_no_dot || has_empty_label {
        return false;
    }
    !matches!(
        lowercase_host.rsplit('.').next(),
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

/// IPv6 offers several ways to write an IPv4 address, and each one used to bypass most of the IPv4
/// rules. Every embedding is now judged by [`is_public_v4`].
fn is_public_ip(ip: IpAddr) -> bool {
    let v6 = match ip {
        IpAddr::V4(v4) => return is_public_v4(v4),
        IpAddr::V6(v6) => v6,
    };
    if v6.is_loopback() || v6.is_unspecified() || v6.is_multicast() {
        return false;
    }
    let segments = v6.segments();
    let is_unique_local = (segments[0] & 0xfe00) == 0xfc00;
    let is_link_local = (segments[0] & 0xffc0) == 0xfe80;
    if is_unique_local || is_link_local {
        return false;
    }
    match v6
        .to_ipv4_mapped()
        .or_else(|| v6.to_ipv4())
        .or_else(|| ipv4_inside_6to4(segments))
        .or_else(|| ipv4_inside_nat64(segments))
    {
        Some(v4) => is_public_v4(v4),
        None => true,
    }
}

/// 6to4 carries the address in the two segments after the `2002::/16` prefix.
fn ipv4_inside_6to4(segments: [u16; 8]) -> Option<Ipv4Addr> {
    (segments[0] == 0x2002).then(|| ipv4_from_segments(segments[1], segments[2]))
}

/// The NAT64 well-known prefix `64:ff9b::/96` carries it in the last two segments.
fn ipv4_inside_nat64(segments: [u16; 8]) -> Option<Ipv4Addr> {
    let has_well_known_prefix = segments[0] == 0x0064
        && segments[1] == 0xff9b
        && segments[2] == 0
        && segments[3] == 0
        && segments[4] == 0;
    has_well_known_prefix.then(|| ipv4_from_segments(segments[6], segments[7]))
}

fn ipv4_from_segments(high: u16, low: u16) -> Ipv4Addr {
    Ipv4Addr::new((high >> 8) as u8, high as u8, (low >> 8) as u8, low as u8)
}

fn is_public_v4(v4: Ipv4Addr) -> bool {
    let [a, b, c, _] = v4.octets();
    let this_network = a == 0;
    let carrier_grade_nat = a == 100 && (64..128).contains(&b);
    let ietf_protocol_assignments = a == 192 && b == 0 && c == 0;
    let benchmarking = a == 198 && (b == 18 || b == 19);
    let reserved = a >= 240;

    !(v4.is_loopback()
        || v4.is_private()
        || v4.is_link_local()
        || v4.is_broadcast()
        || v4.is_documentation()
        || v4.is_unspecified()
        || v4.is_multicast()
        || this_network
        || carrier_grade_nat
        || ietf_protocol_assignments
        || benchmarking
        || reserved)
}

/// Why a URL was not collected. Each variant is a label on the decline counter. A lane
/// that collects less than it should then reads off a dashboard, rather than being guessed at.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Decline {
    /// Longer than [`MAX_URL_LEN`], before or after normalization.
    TooLong,
    /// Not parseable as an absolute URL. A relative `src` lands here, because the recording does
    /// not carry the base it would need to resolve against.
    NotAbsolute,
    /// A scheme we do not fetch. Only `https` passes, so plain `http` lands here too.
    BadScheme,
    /// A port the scheme does not own. See the port check in [`try_canonicalize`].
    BadPort,
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
            Decline::BadPort => "bad_port",
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
    // The browser blocks a plain `http` image on an HTTPS page as mixed content, so it never
    // rendered for the person we recorded, and a fetch puts the request on the wire in clear text
    // from our egress addresses.
    if url.scheme() != "https" {
        return Err(Decline::BadScheme);
    }
    // A port the scheme does not own makes the fetcher a port prober: a page names any host and
    // port, the connection leaves our egress addresses, and the outcome metric shows what answered.
    // Too few images are served on other ports to be worth that.
    //
    // This check limits which service on a host we reach. `is_public_host` and the address check at
    // request time limit which hosts we reach, because DNS for a name the attacker owns can point
    // anywhere.
    if url.port().is_some() {
        return Err(Decline::BadPort);
    }
    // `example.com.` and `example.com` name the same host, and the consumer compares the two as
    // strings in more than one place. The dot comes off the URL as well as off the host, so
    // everything downstream sees one spelling.
    let host_str = url.host_str().ok_or(Decline::NoHost)?;
    let host = host_str.strip_suffix('.').unwrap_or(host_str).to_string();
    if !is_public_host(&host) {
        return Err(Decline::NonPublicHost);
    }
    if host != host_str {
        url.set_host(Some(&host)).map_err(|_| Decline::NoHost)?;
    }

    remove_credentials_and_fragment(&mut url);
    let fetch = url.to_string();
    // Percent-encoding and IDNA can grow a URL, so the cap is re-checked on what we emit.
    if fetch.len() > MAX_URL_LEN {
        return Err(Decline::TooLong);
    }

    remove_volatile_params(&mut url, &host);
    let dedup = url.to_string();

    Ok(CanonicalUrl {
        fetch,
        dedup,
        domain: politeness_key(&host),
        host,
    })
}

fn remove_credentials_and_fragment(url: &mut Url) {
    // The setters fail only on a cannot-be-a-base URL, which the http(s) check already excluded.
    let _ = url.set_username("");
    let _ = url.set_password(None);
    url.set_fragment(None);
}

/// Rewrites the query of every URL that has one, whether or not it removed anything.
///
/// Rewriting only when something was removed made the result depend on an unrelated fact. Two
/// encodings of one query then hashed the same when a signature was present and differently when
/// it was absent, so one image could hold two refs.
fn remove_volatile_params(url: &mut Url, host: &str) {
    if url.query().is_none() {
        return;
    }
    let pairs: Vec<(String, String)> = url
        .query_pairs()
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect();
    let names_on_this_url: HashSet<String> =
        pairs.iter().map(|(k, _)| k.to_ascii_lowercase()).collect();
    let kept: Vec<&(String, String)> = pairs
        .iter()
        .filter(|(k, _)| !is_volatile(k, host, &names_on_this_url))
        .collect();

    if kept.is_empty() {
        url.set_query(None);
        return;
    }
    let mut query = url.query_pairs_mut();
    query.clear();
    for (name, value) in kept {
        query.append_pair(name, value);
    }
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
        // The Azure SAS names are volatile only when the signature of that set is also present.
        assert!(!volatile("sp", "cdn.example.com", &["w"]));
        assert!(volatile("sp", "acct.blob.core.windows.net", &["sig", "sv"]));
        // `expires` is a real cache hint until CloudFront's `signature` appears beside it.
        assert!(!volatile("expires", "cdn.example.com", &[]));
        assert!(volatile("expires", "cdn.example.com", &["signature"]));
    }

    #[test]
    fn only_https_on_its_own_port_is_collected() {
        assert_eq!(canonicalize("https://cdn.example.com:11211/a.png"), None);
        assert_eq!(canonicalize("https://cdn.example.com:8443/a.png"), None);
        assert_eq!(canonicalize("http://cdn.example.com/a.png"), None);
        assert_eq!(canonicalize("http://cdn.example.com:80/a.png"), None);
        // The parser normalizes the default port away, so `url.port()` is None and `:443` passes.
        assert!(canonicalize("https://cdn.example.com:443/a.png").is_some());
        assert!(canonicalize("https://cdn.example.com/a.png").is_some());
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
    fn a_fully_qualified_host_keys_the_same_as_the_bare_one() {
        assert_eq!(politeness_key("example.com."), "example.com");
        assert_eq!(politeness_key("img1.cdn.example.com."), "example.com");
        assert_eq!(politeness_key("user.github.io."), "user.github.io");
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
        // The URL set comes from page content, and the fetch lane runs inside our network. Every
        // one is https, or the scheme rule would refuse it before the host rule was reached.
        for raw in [
            "https://169.254.169.254/latest/meta-data/iam/security-credentials/",
            "https://localhost/admin/export.png",
            "https://127.0.0.1/i.png",
            "https://10.0.0.5/i.png",
            "https://192.168.1.1/i.png",
            "https://172.16.0.1/i.png",
            "https://[::1]/i.png",
            "https://[fd00::1]/i.png",
            "https://metadata.internal/i.png",
            "https://buildserver/i.png",
            // A trailing dot makes a name fully qualified and resolves the same way. It used to
            // walk past the name list, because the label after the final dot is empty.
            "https://localhost./i.png",
            "https://metadata.internal./i.png",
            "https://LOCALHOST./i.png",
            // IPv6 offers several ways to write an IPv4 address. Each one used to skip the IPv4
            // rules entirely.
            "https://[::ffff:0.0.0.0]/i.png",
            "https://[::ffff:127.0.0.1]/i.png",
            "https://[::ffff:10.0.0.5]/i.png",
            "https://[::ffff:100.64.0.1]/i.png",
            "https://[::127.0.0.1]/i.png",
            "https://[2002:7f00:1::]/i.png",
            "https://[64:ff9b::7f00:1]/i.png",
            "https://[ff02::1]/i.png",
            // Ranges we would never legitimately fetch from.
            "https://224.0.0.1/i.png",
            "https://240.0.0.1/i.png",
            "https://198.18.0.1/i.png",
            "https://192.0.0.1/i.png",
            "https://0.0.0.0/i.png",
        ] {
            assert!(canonicalize(raw).is_none(), "{raw} must not be collected");
        }
        assert!(canonicalize("https://cdn.example.com/i.png").is_some());
        // A public name with a trailing dot is still public, so the fix must not over-reject.
        assert!(canonicalize("https://cdn.example.com./i.png").is_some());
        // The address rule accepts a public address. Both use https, because the scheme rule
        // refuses plain http on its own.
        assert!(canonicalize("https://[2606:4700::1111]/i.png").is_some());
        assert!(canonicalize("https://8.8.8.8/i.png").is_some());
    }

    #[test]
    fn a_fully_qualified_host_survives_the_whole_lane() {
        let c = canonicalize("https://cdn.example.com./i.png").expect("collected");
        // The consumer compares `new URL(fetch).hostname` with `host`. A dot on one side only
        // makes every fully qualified host fail that comparison.
        assert_eq!(c.host, "cdn.example.com");
        assert_eq!(c.fetch, "https://cdn.example.com/i.png");
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
